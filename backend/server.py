"""
FastAPI Sunucusu ve REST/WebSocket API'leri (HAL & Yük Kontrolü Destekli)
"""
from contextlib import asynccontextmanager
import asyncio
import re
import statistics
import math
from typing import List
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import CONFIG
from .engine import MANAGER
from .hal.relay_selector import ArduinoRelaySelector

RELAY_SELECTOR = ArduinoRelaySelector(CONFIG.RELAY_PORT, CONFIG.RELAY_BAUDRATE)
LAST_MODULE_TEST_RESULTS = None


def test_source_current_limit(rated_power_w: float, voltage: float) -> float:
    """Cap nominal input power at 150% of the DUT rating, within PSU limits."""
    if not math.isfinite(rated_power_w) or not math.isfinite(voltage) or rated_power_w <= 0 or voltage <= 0:
        raise ValueError("A positive, finite DUT power and input voltage are required.")
    # Round down to the PSU's 1 mA programming resolution.
    amps = math.floor(min(CONFIG.PSU_TEST_CURRENT_LIMIT_A, rated_power_w * 1.5 / voltage) * 1000) / 1000
    if amps < 0.01:
        raise ValueError("Calculated current limit is below the PSU minimum.")
    return amps


def calculate_regulation(points: list, nominal_output_v: float) -> dict:
    """Regulation magnitudes normalized to catalogue nominal output voltage."""
    def usable(point):
        return (point is not None and point.get("input_voltage_verified")
                and point.get("load_verified") and point.get("output_voltage", 0) > 0)

    load_rows = []
    for name in ("Minimum", "Nominal", "Maximum"):
        pair = {p["load_percent"]: p for p in points if p["input_range_point"] == name}
        idle, full = pair.get(0), pair.get(100)
        valid = nominal_output_v > 0 and usable(idle) and usable(full)
        delta = abs(idle["output_voltage"] - full["output_voltage"]) if valid else None
        load_rows.append({"input_step": name, "valid": bool(valid),
                          "no_load_v": idle.get("output_voltage") if idle else None,
                          "full_load_v": full.get("output_voltage") if full else None,
                          "delta_v": delta,
                          "percent": delta / nominal_output_v * 100 if valid else None})
    line_rows = []
    for load in (0, 100):
        selected = [p for p in points if p["load_percent"] == load]
        valid = (nominal_output_v > 0 and len(selected) == 3
                 and {p["input_range_point"] for p in selected} == {"Minimum", "Nominal", "Maximum"}
                 and all(usable(p) for p in selected))
        volts = [p["output_voltage"] for p in selected] if valid else []
        delta = max(volts) - min(volts) if valid else None
        line_rows.append({"load_percent": load, "valid": bool(valid),
                          "min_output_v": min(volts) if valid else None,
                          "max_output_v": max(volts) if valid else None,
                          "delta_v": delta,
                          "percent": delta / nominal_output_v * 100 if valid else None})
    return {"reference_output_v": nominal_output_v, "load_regulation": load_rows,
            "line_regulation": line_rows}


def catalog_output_span_v(model: dict) -> float:
    """Return the voltage measured across all output rails for this model."""
    output_spec = str(model.get("vout", "")).replace("Â±", "±")
    symmetric_dual = re.search(r"±\s*(\d+(?:\.\d+)?)", output_spec)
    if symmetric_dual:
        return 2.0 * float(symmetric_dual.group(1))

    if model.get("family") == "3W" and "/" in output_spec:
        rails = [float(value) for value in re.findall(r"[+-]?\d+(?:\.\d+)?", output_spec)]
        if len(rails) >= 2:
            return max(rails) - min(rails)

    return abs(float(model.get("vout_val", 0.0)))

def relay_port_conflict(psu_port: str = "", load_port: str = "") -> bool:
    relay_port = RELAY_SELECTOR.port.strip().upper()
    active_ports = {str(port).strip().upper() for port in (psu_port, load_port) if port}
    return relay_port in active_ports

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Do not block HTTP startup on serial discovery or disconnected hardware.
    await MANAGER.start()
    yield
    # Kapanışta kaynakları temizle
    await MANAGER.stop()

app = FastAPI(title="DC-DC Telemetry Kiosk Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if any(path.endswith(ext) for ext in [".js", ".css", ".html", "/"]):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# REST İstek Modelleri
class ModeRequest(BaseModel):
    mode: str  # "SIMULATION" veya "HARDWARE"

class PortConfigRequest(BaseModel):
    hmp_port: str = ""
    psu_port: str = ""
    utl_port: str = ""

class LoadStateRequest(BaseModel):
    enabled: bool

class LoadCurrentRequest(BaseModel):
    current: float

class PSUStateRequest(BaseModel):
    enabled: bool
    slot: int | None = None

class SlotPowerRequest(BaseModel):
    slot: int
    voltage: float = 24.0

class SingleSlotTestRequest(BaseModel):
    slot: int
    rated_power_w: float = 20.0

class SlotCalibrationPointRequest(BaseModel):
    iin_a: float
    vin_source_v: float
    vin_dut_v: float
    iout_a: float
    vout_load_v: float
    vout_dut_v: float

class SlotCalibrationRequest(BaseModel):
    slot: int
    points: List[SlotCalibrationPointRequest]

class SlotCalibrationCaptureRequest(BaseModel):
    slot: int
    point: str
    output_current_a: float

class SlotCalibrationSaveRequest(BaseModel):
    slot: int
    references: dict

from fastapi.responses import Response
from .sweep_engine import SWEEP_ENGINE, SweepConfig
from .dut_catalog import DUT_CATALOG, POWER_FAMILIES, get_families, get_models_by_family, get_dut
from .slot_calibration import build_profile, save_profiles

ACTIVE_DUT_KEY = "OZP20S24SS33A"
MODULE_DETECTION_LOCK = asyncio.Lock()
SLOT_CALIBRATION_LOCK = asyncio.Lock()
SLOT_CALIBRATION_SESSION = None
SLOT_CALIBRATION_TIMER = None

async def finish_slot_calibration(session_id=None):
    global SLOT_CALIBRATION_SESSION, SLOT_CALIBRATION_TIMER
    session = SLOT_CALIBRATION_SESSION
    if session is None or (session_id is not None and session.get("id") != session_id):
        return
    MANAGER.set_load_state(False)
    MANAGER.set_load_current(0.0)
    source_disabled = MANAGER.set_psu_state(False)
    if source_disabled and await asyncio.to_thread(RELAY_SELECTOR.all_off):
        MANAGER.set_active_slot(None)
        await asyncio.to_thread(RELAY_SELECTOR.disconnect)
    MANAGER.is_sweep_active = False
    SLOT_CALIBRATION_SESSION = None
    timer = SLOT_CALIBRATION_TIMER
    SLOT_CALIBRATION_TIMER = None
    if timer is not None and timer is not asyncio.current_task():
        timer.cancel()

async def expire_slot_calibration(session_id):
    await asyncio.sleep(180.0)
    await finish_slot_calibration(session_id)

def require_test_not_stopped() -> None:
    if MANAGER.emergency_stop_latched:
        raise RuntimeError("Emergency stop is active; start a new test to resume.")

async def ensure_bench_instruments() -> bool:
    """Reconnect the assigned PSU/load before a hardware operation starts."""
    if MANAGER.mode != "HARDWARE":
        return False
    if MANAGER.psu.is_connected and MANAGER.load.is_connected:
        return True
    result = await ensure_default_ports()
    return result.get("status") == "success" and MANAGER.psu.is_connected and MANAGER.load.is_connected

async def guarded_test_sleep(seconds: float) -> None:
    deadline = asyncio.get_running_loop().time() + seconds
    next_sample = asyncio.get_running_loop().time()
    while True:
        require_test_not_stopped()
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return
        # The test owns serial access while normal telemetry is paused.
        # Keep the UI live during settling without a competing reader/task.
        if seconds > 0.25 and MANAGER.is_sweep_active and asyncio.get_running_loop().time() >= next_sample:
            await MANAGER.acquire_and_broadcast()
            require_test_not_stopped()
            next_sample = asyncio.get_running_loop().time() + CONFIG.SAMPLE_INTERVAL_SEC
            continue
        await asyncio.sleep(min(0.1, remaining))

@app.post("/api/module/detect")
async def detect_module():
    return await run_module_detection()


async def run_module_detection(only_slot: int | None = None, run_performance: bool = True,
                               power_family: str | None = None):
    """Use 24 V to detect a working module; use 10 V to classify its input range."""
    global ACTIVE_DUT_KEY, LAST_MODULE_TEST_RESULTS
    if SLOT_CALIBRATION_SESSION is not None:
        return {"status": "error", "message": "Yuva kalibrasyonu tamamlanmalı veya iptal edilmeli."}
    if SWEEP_ENGINE.is_running:
        return {"status": "error", "message": "Stop the efficiency sweep before module detection."}
    if MODULE_DETECTION_LOCK.locked():
        return {"status": "error", "message": "Module detection is already running."}
    if MANAGER.mode != "HARDWARE":
        return {"status": "error", "message": "Five-slot detection requires hardware mode."}
    await ensure_bench_instruments()
    if not MANAGER.psu.is_connected or not MANAGER.load.is_connected:
        return {"status": "error", "message": "Connect the PSU and electronic load before detection."}
    psu_port = getattr(MANAGER.psu, "port", "")
    load_port = getattr(MANAGER.load._driver, "port", "")
    if psu_port.strip().upper() == load_port.strip().upper():
        return {"status": "error", "message": "PSU and electronic load must use separate COM ports."}
    if relay_port_conflict(psu_port, load_port):
        return {"status": "error", "message": f"Arduino relay port {RELAY_SELECTOR.port} conflicts with a PSU/load port."}

    async with MODULE_DETECTION_LOCK:
        MANAGER.clear_emergency_stop()
        LAST_MODULE_TEST_RESULTS = None
        selected = DUT_CATALOG.get(ACTIVE_DUT_KEY, DUT_CATALOG["OZP50S48SS05A"])
        if power_family is not None:
            selected = next(model for model in DUT_CATALOG.values() if model.get("family") == power_family)
        family = selected.get("family")
        output_threshold = 2.5
        presence_check_current = 0.05
        previous_vin = float(getattr(MANAGER.psu, "nominal_vin", 48.0))
        previous_current = MANAGER.load.target_current
        previous_load_enabled = MANAGER.load.load_enabled
        previous_telemetry_pause = MANAGER.is_sweep_active
        slot_results = []

        async def check_at(voltage: float, target_current: float, rated_power_w: float = None) -> dict:
            require_test_not_stopped()
            power_rating = float(selected["power_val"]) if rated_power_w is None else rated_power_w
            source_current_limit = test_source_current_limit(power_rating, voltage)
            # Let the converter start unloaded, as in the manual slot-power flow.
            if not MANAGER.set_load_state(False):
                raise RuntimeError("Electronic load could not be disabled before startup.")
            if not MANAGER.set_load_current(0.0):
                raise RuntimeError("Electronic load current could not be reset before startup.")
            if not MANAGER.set_psu_state(False):
                raise RuntimeError("PSU could not be disabled before startup.")
            await guarded_test_sleep(1.0)
            if not MANAGER.psu.set_current_limit(source_current_limit):
                raise RuntimeError(f"PSU current limit could not be set to {source_current_limit:.3f} A.")
            # Voltage programming does not enable the output.
            MANAGER.set_psu_voltage(voltage)
            require_test_not_stopped()
            if not MANAGER.set_psu_state(True):
                raise RuntimeError("PSU could not be enabled for the probe test.")
            await guarded_test_sleep(1.0)
            require_test_not_stopped()
            if not MANAGER.set_load_current(target_current):
                raise RuntimeError("Electronic load current command failed.")
            load_enabled = target_current > 0
            if not MANAGER.set_load_state(load_enabled):
                raise RuntimeError("Electronic load could not be enabled.")
            load_settings = await asyncio.to_thread(
                MANAGER.load.verify_settings, target_current, load_enabled)
            require_test_not_stopped()
            await guarded_test_sleep(5.0)
            readings = []
            for _ in range(3):
                require_test_not_stopped()
                readings.append(await MANAGER.acquire_and_broadcast())
                await guarded_test_sleep(0.25)
            measured = {key: statistics.median(float(sample[key]) for sample in readings)
                        for key in ("v_in", "i_in", "p_in", "v_out", "i_out", "p_out", "eff")}
            raw_samples = [
                {key: round(float(sample[key]), 3 if key != "eff" else 2)
                 for key in ("v_in", "i_in", "p_in", "v_out", "i_out", "p_out", "eff")}
                for sample in readings
            ]
            input_verified = abs(measured["v_in"] - voltage) <= max(1.0, voltage * 0.10)
            regulated_output = (input_verified and measured["v_out"] >= output_threshold)
            return {"input_voltage": voltage,
                    "input_power_limit_w": power_rating * 1.5,
                    "source_current_limit_a": source_current_limit,
                    "load_settings": load_settings,
                    "measured_input_voltage": round(measured["v_in"], 3),
                    "input_current": round(measured["i_in"], 3),
                    "input_power": round(measured["p_in"], 3),
                    "output_voltage": round(measured["v_out"], 3),
                    "output_current": round(measured["i_out"], 3),
                    "output_power": round(measured["p_out"], 3),
                    "efficiency": round(measured["eff"], 2),
                    "input_voltage_verified": input_verified,
                    "regulated_output": regulated_output,
                    "presence_check_current": presence_check_current,
                    "raw_samples": raw_samples,
                    # Reject residual voltage from an empty slot: the output must
                    # sustain a small, real load as well as pass the voltage threshold.
                    "working": (regulated_output
                                and measured["i_out"] >= presence_check_current * 0.5
                                )}

        try:
            MANAGER.is_sweep_active = True
            if not await asyncio.to_thread(RELAY_SELECTOR.connect):
                return {"status": "error", "message": f"Arduino relay controller not available on {RELAY_SELECTOR.port}."}
            if not MANAGER.set_psu_state(False):
                raise RuntimeError("PSU output could not be disabled before relay selection.")
            if not MANAGER.set_load_current(0.0):
                raise RuntimeError("Electronic load initial current command failed.")
            if not MANAGER.set_load_state(False):
                raise RuntimeError("Electronic load could not be disabled before relay selection.")
            if not await asyncio.to_thread(RELAY_SELECTOR.all_off):
                return {"status": "error", "message": "Arduino did not acknowledge OFF; detection stopped safely."}
            MANAGER.set_active_slot(None)

            for slot in ([only_slot] if only_slot is not None else range(1, 6)):
                if not MANAGER.set_load_state(False):
                    raise RuntimeError("Electronic load could not be disabled before slot selection.")
                if not MANAGER.set_load_current(0.0):
                    raise RuntimeError("Electronic load current reset failed before slot selection.")
                if not MANAGER.set_psu_state(False):
                    raise RuntimeError("PSU output could not be disabled before changing relay slots.")
                # Give the DUT output capacitors time to discharge before switching slots.
                await guarded_test_sleep(1.0)
                require_test_not_stopped()
                if not await asyncio.to_thread(RELAY_SELECTOR.select_slot, slot):
                    raise RuntimeError(f"Arduino did not acknowledge relay slot {slot}.")
                MANAGER.set_active_slot(slot)
                # Allow one second for the new relay contacts and module to settle.
                await guarded_test_sleep(1.0)
                # A 50 mA probe load drains leftover output charge and confirms
                # that a slot can actually supply current before calling it present.
                tests = {"10V": await check_at(10.0, presence_check_current),
                         "24V": await check_at(24.0, presence_check_current)}
                result = {"slot": slot, "tests": tests, "model_key": None, "model": None,
                          "performance_tests": [],
                          "calibration_profile_applied": bool(
                              MANAGER.slot_calibrations.get(str(slot), {}).get("calibrated_at"))}
                if tests["24V"]["working"]:
                    low_input = tests["10V"]
                    measured_vout = tests["24V"]["output_voltage"]
                    result.update({
                        "status": "working",
                        "measured_output_voltage": measured_vout,
                        "inference": {
                            "measured_vout_at_24v": measured_vout,
                            "measured_vout_at_10v": low_input["output_voltage"],
                        },
                    })

                    if low_input["working"]:
                        nominal = 24
                        input_range = "9-36 VDC"
                        input_basis = "10 V input: regulated output and probe current confirmed"
                    elif (low_input["input_voltage_verified"]
                          and low_input["output_voltage"] >= output_threshold):
                        # Output voltage without confirmed probe current is ambiguous.
                        # Never escalate to 48 V on this evidence.
                        nominal = None
                        input_range = None
                        input_basis = "10 V output voltage present, probe current unconfirmed; higher voltage skipped."
                    elif low_input["input_voltage_verified"]:
                        nominal = 48
                        input_range = "18-72 VDC"
                        input_basis = "10 V input verified with no output above threshold; operated at 24 V"
                    else:
                        nominal = None
                        input_range = None
                        input_basis = "10 V giri? ?l??m? hedefi do?rulamad?"

                    result["inference"].update({
                        "input_range": input_range,
                        "input_range_basis": input_basis,
                    })
                    if nominal is None:
                        result.update({
                            "inference_status": "inconclusive",
                            "model_candidates": [],
                            "message": ("10 V output voltage was present but probe current was not confirmed; skipped 48 V for safety." if low_input["input_voltage_verified"] and low_input["output_voltage"] >= output_threshold else "24 V output was confirmed, but the 10 V input classification could not be verified."),
                        })
                    else:
                        result.update({
                            "nominal_input_voltage": nominal,
                            "input_range": input_range,
                            "input_range_basis": input_basis,
                        })
                        candidates = [(key, model) for key, model in DUT_CATALOG.items()
                                      if model.get("family") == family
                                      and abs(float(model.get("vin_nom", 0)) - nominal) < 0.1]
                        closest = min(candidates,
                                      key=lambda item: abs(catalog_output_span_v(item[1]) - measured_vout),
                                      default=None)
                        tolerance_matches = []
                        if closest:
                            expected = catalog_output_span_v(closest[1])
                            tolerance = max(0.5, expected * 0.05)
                            if abs(expected - measured_vout) <= tolerance:
                                tolerance_matches = [
                                    (key, model) for key, model in candidates
                                    if abs(catalog_output_span_v(model) - measured_vout)
                                    <= max(0.5, catalog_output_span_v(model) * 0.05)
                                ]

                        result["model_candidates"] = [
                            {"model_key": key, "model": model["model"],
                             "output": model["vout"], "vout_v": model["vout_val"],
                             "measured_output_span_v": catalog_output_span_v(model)}
                            for key, model in tolerance_matches
                        ]
                        result["inference"].update({
                            "model_status": ("identified" if len(tolerance_matches) == 1
                                             else "ambiguous" if len(tolerance_matches) > 1
                                             else "unmatched"),
                            "model_candidates": result["model_candidates"],
                        })

                        if len(tolerance_matches) == 1:
                            model_key, matched_model = tolerance_matches[0]
                            result.update({"model_key": model_key, "model": matched_model,
                                           "inference_status": "identified",
                                           "message": f"{matched_model['model']} tahmin edildi"})
                            expected_vout = catalog_output_span_v(matched_model)
                            rated_current = float(matched_model["imax_val"])
                            rated_power = float(matched_model["power_val"])
                            efficiency = float(matched_model.get("typ_eff", 85.0)) / 100.0
                            input_points = (
                                ("Minimum", float(matched_model["vin_min"])),
                                ("Nominal", float(matched_model["vin_nom"])),
                                ("Maximum", float(matched_model["vin_max"])),
                            )
                            full_load_current = math.floor(min(rated_current, rated_power / expected_vout) * 1000) / 1000
                            for input_label, input_voltage in (input_points if run_performance else ()):
                                source_power = input_voltage * test_source_current_limit(rated_power, input_voltage)
                                for load_percent in (0, 100):
                                    target_current = full_load_current if load_percent == 100 else 0.0
                                    if load_percent == 100 and (target_current > CONFIG.LOAD_TEST_MAX_CURRENT_A
                                            or expected_vout * target_current / efficiency > source_power):
                                        result["performance_tests"].append({
                                            "input_range_point": input_label, "input_voltage": input_voltage,
                                            "load_percent": 100, "target_current": target_current,
                                            "expected_output_voltage": expected_vout, "passed": False,
                                            "load_verified": False, "status": "skipped",
                                            "message": "Bench PSU/load capacity cannot support catalogue full load."})
                                        continue
                                    measurement = await check_at(
                                        input_voltage, target_current, rated_power)
                                    regulation_ok = abs(measurement["output_voltage"] - expected_vout) <= max(
                                        0.1, expected_vout * 0.05)
                                    current_ok = (abs(measurement["output_current"] - target_current) <= max(0.005, target_current * 0.05)
                                                  if load_percent == 100 else measurement["output_current"] <= 0.01)
                                    measurement.update({"target_current": target_current,
                                                        "load_percent": load_percent,
                                                        "input_range_point": input_label,
                                                        "expected_output_voltage": expected_vout,
                                                        "load_verified": current_ok,
                                                        "load_condition": "Full load" if load_percent else "No load",
                                                        "passed": measurement["input_voltage_verified"] and regulation_ok and current_ok})
                                    result["performance_tests"].append(measurement)
                            if run_performance:
                                result["regulation"] = calculate_regulation(result["performance_tests"], expected_vout)
                        elif tolerance_matches:
                            result.update({
                                "inference_status": "ambiguous",
                                "message": "??k?? gerilimi birden fazla katalog modeliyle e?le?iyor; tam model bu ?l??mle ay?rt edilemiyor.",
                            })
                        else:
                            result.update({
                                "inference_status": "unmatched",
                                "message": "Mod?l ?al???yor ancak ?l??len ??k?? se?ilen g?? ailesindeki bir katalog modeliyle e?le?medi.",
                            })
                else:
                    point24 = tests["24V"]
                    measured_vout = point24["output_voltage"]
                    measured_iout = point24["output_current"]
                    if not point24["input_voltage_verified"]:
                        status = "inconclusive"
                        inference_status = "input_not_verified"
                        message = "24 V PSU input was not verified; module presence cannot be decided."
                    elif measured_vout < output_threshold:
                        status = "fault_or_empty"
                        inference_status = "no_regulated_output"
                        message = "24 V input was verified, but output voltage is below the regulation threshold."
                    elif measured_iout < presence_check_current * 0.5:
                        status = "inconclusive"
                        inference_status = "voltage_without_probe_current"
                        message = (f"{measured_vout:.3f} V is present at 24 V, but the 0.05 A probe current was not measured; "
                                   "module presence is unconfirmed.")
                    else:
                        status = "inconclusive"
                        inference_status = "output_not_confirmed"
                        message = "The 24 V measurement did not conclusively confirm module output."
                    result.update({"status": status, "nominal_input_voltage": None,
                                   "measured_output_voltage": measured_vout,
                                   "inference_status": inference_status,
                                   "model_candidates": [],
                                   "inference": {"model_status": inference_status,
                                                 "measured_vout_at_24v": measured_vout,
                                                 "measured_iout_at_24v": measured_iout},
                                   "message": message})
                slot_results.append(result)

            completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
            LAST_MODULE_TEST_RESULTS = {"family": family, "completed_at": completed_at,
                                       "results": slot_results}
            return {"status": "complete", "family": family, "completed_at": completed_at,
                    "results": slot_results}
        except Exception as exc:
            return {"status": "error", "message": f"Detection stopped: {exc}", "results": slot_results}
        finally:
            # Leave the supply off before opening all relay paths.
            source_disabled = MANAGER.set_psu_state(False)
            if source_disabled:
                await asyncio.to_thread(RELAY_SELECTOR.all_off)
                MANAGER.set_active_slot(None)
            if not MANAGER.emergency_stop_latched:
                MANAGER.set_psu_voltage(previous_vin)
                if MANAGER.set_psu_state(False) and not source_disabled:
                    await asyncio.to_thread(RELAY_SELECTOR.all_off)
                MANAGER.set_load_current(previous_current)
                MANAGER.set_load_state(previous_load_enabled)
            MANAGER.is_sweep_active = previous_telemetry_pause

@app.post("/api/module/test-slot")
async def test_single_module_slot(req: SingleSlotTestRequest):
    """Use the same min/nom/max, no-load/full-load procedure for one slot."""
    if req.slot not in range(1, 6) or req.rated_power_w not in (20, 50, 100, 300):
        return {"status": "error", "message": "Invalid slot or rated power."}
    detection = await run_module_detection(
        only_slot=req.slot, run_performance=True, power_family=f"{int(req.rated_power_w)}W")
    item = next(iter(detection.get("results", [])), None)
    if detection.get("status") != "complete" or item is None:
        return detection
    points = item.get("performance_tests", [])
    passed = len(points) == 6 and all(p.get("passed") for p in points)
    nominal = [p for p in points if p["input_range_point"] == "Nominal" and p.get("status") != "skipped"]
    no_load = next((p for p in nominal if p["load_percent"] == 0), None)
    full_load = next((p for p in nominal if p["load_percent"] == 100), None)
    skipped = any(p.get("status") == "skipped" for p in points)
    return {**item, "status": "passed" if passed else "error" if skipped else "failed" if points or item.get("status") == "fault_or_empty" else "error",
            "target_power_w": float(req.rated_power_w),
            "message": "Min/nom/max input, no-load/full-load test passed." if passed else "Test incomplete or failed; inspect the per-point results and regulation report.",
            "no_load": no_load, "hold": full_load,
            "measurements": [{**p, "fraction": p["load_percent"] / 100,
                              "target_current_a": p["target_current"]} for p in nominal]}

@app.get("/api/module/export-excel")
async def export_module_results_excel():
    """Download five per-slot workbooks in one ZIP, including summary and raw samples."""
    if not LAST_MODULE_TEST_RESULTS:
        return {"status": "error", "message": "No completed five-slot test is available."}

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    archive = BytesIO()
    report = LAST_MODULE_TEST_RESULTS
    with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
        for item in report["results"]:
            workbook = Workbook()
            summary = workbook.active
            summary.title = "Summary"
            summary.append(["OZAK POWER - Module Test Report"])
            summary.merge_cells("A1:N1")
            summary["A1"].font = Font(bold=True, color="FFFFFF", size=14)
            summary["A1"].fill = PatternFill("solid", fgColor="9F1239")

            model = item.get("model") or {}
            candidates = item.get("model_candidates") or []
            candidate_names = ", ".join(candidate.get("model", "") for candidate in candidates)
            inference = item.get("inference") or {}
            summary_rows = [
                ["Test time", report.get("completed_at", "")],
                ["Power family selected", report.get("family", "")],
                ["Bench slot", item.get("slot")],
                ["Working status", item.get("status", "unknown")],
                ["Inference status", item.get("inference_status", "unknown")],
                ["Input range / nominal", item.get("input_range", "Undetermined")],
                ["Input inference evidence", item.get("input_range_basis", "")],
                ["Model estimate", model.get("model", "Not uniquely identified")],
                ["Candidate model(s)", candidate_names or "None"],
                ["Measured Vout at 10 V", inference.get("measured_vout_at_10v", "")],
                ["Measured Vout at 24 V", item.get("measured_output_voltage", "")],
                ["Slot calibration applied", bool(item.get("calibration_profile_applied", False))],
                ["Result message", item.get("message", "")],
                ["Detection method", "10 V / 24 V with 0.05 A probe; output family inference; performance matrix only for a unique model match"],
            ]
            for row in summary_rows:
                summary.append(row)

            summary.append([])
            summary.append(["Identification measurements"])
            summary.append(["Input step", "PSU setpoint (V)", "Measured Vin (V)", "Iin (A)",
                            "Pin (W)", "Vout (V)", "Iout (A)", "Pout (W)", "Efficiency (%)",
                            "Input verified", "Output regulated", "Probe current (A)", "Working"])
            for step, measurement in item.get("tests", {}).items():
                summary.append([step, measurement.get("input_voltage"),
                                measurement.get("measured_input_voltage"),
                                measurement.get("input_current"), measurement.get("input_power"),
                                measurement.get("output_voltage"), measurement.get("output_current"),
                                measurement.get("output_power"), measurement.get("efficiency"),
                                bool(measurement.get("input_voltage_verified")),
                                bool(measurement.get("regulated_output")),
                                measurement.get("presence_check_current"),
                                bool(measurement.get("working"))])

            summary.append([])
            summary.append(["No-load / full-load performance matrix"])
            summary.append(["Input step", "PSU setpoint (V)", "Load (%)", "Target Iout (A)",
                            "Measured Vin (V)", "Iin (A)", "Pin (W)", "Vout (V)",
                            "Iout (A)", "Pout (W)", "Efficiency (%)", "Pass", "Status", "Message"])
            for measurement in item.get("performance_tests", []):
                summary.append([measurement.get("input_range_point"), measurement.get("input_voltage"),
                                measurement.get("load_percent"), measurement.get("target_current"),
                                measurement.get("measured_input_voltage"), measurement.get("input_current"),
                                measurement.get("input_power"), measurement.get("output_voltage"),
                                measurement.get("output_current"), measurement.get("output_power"),
                                measurement.get("efficiency"), bool(measurement.get("passed")),
                                measurement.get("status", "measured"), measurement.get("message", "")])

            regulation = workbook.create_sheet("Regulation")
            regulation.append(["Load regulation and line regulation"])
            regulation.append(["Reference: catalogue nominal output voltage (V)",
                               (item.get("regulation") or {}).get("reference_output_v")])
            regulation.append(["Load regulation (%) = abs(Vout no load - Vout full load) / Vout nominal * 100"])
            regulation.append(["Line regulation (%) = (max Vout - min Vout) across min/nom/max Vin at fixed load / Vout nominal * 100"])
            regulation.append(["Unavailable results are blank, not zero. Check input/load verification and skipped full-load points."])
            regulation.append([])
            regulation.append(["Load regulation", "Vout no load (V)", "Vout full load (V)",
                               "Delta Vout (V)", "Load regulation (%)", "Valid"])
            metrics = item.get("regulation") or {}
            for metric in metrics.get("load_regulation", []):
                regulation.append([metric["input_step"], metric["no_load_v"], metric["full_load_v"],
                                   metric["delta_v"], metric["percent"], metric["valid"]])
            regulation.append([])
            regulation.append(["Line regulation", "Min Vout (V)", "Max Vout (V)",
                               "Delta Vout (V)", "Line regulation (%)", "Valid"])
            for metric in metrics.get("line_regulation", []):
                regulation.append(["Full load" if metric["load_percent"] else "No load",
                                   metric["min_output_v"], metric["max_output_v"],
                                   metric["delta_v"], metric["percent"], metric["valid"]])
            if not metrics:
                regulation.append(["Not available: no completed regulation matrix for this slot."])
            for row in regulation.iter_rows(min_row=7):
                for cell in row[1:5]:
                    if isinstance(cell.value, (int, float)):
                        cell.number_format = "0.0000"

            raw = workbook.create_sheet("Raw Samples")
            raw.append(["Stage", "Point", "Sample #", "PSU setpoint (V)", "Target Iout (A)",
                        "Vin (V)", "Iin (A)", "Pin (W)", "Vout (V)", "Iout (A)",
                        "Pout (W)", "Efficiency (%)", "Input verified", "Regulated", "Point passed"])
            for step, measurement in item.get("tests", {}).items():
                for sample_index, sample in enumerate(measurement.get("raw_samples", []), start=1):
                    raw.append(["Identification", step, sample_index, measurement.get("input_voltage"),
                                measurement.get("presence_check_current"), sample.get("v_in"),
                                sample.get("i_in"), sample.get("p_in"), sample.get("v_out"),
                                sample.get("i_out"), sample.get("p_out"), sample.get("eff"),
                                bool(measurement.get("input_voltage_verified")),
                                bool(measurement.get("regulated_output")), bool(measurement.get("working"))])
            for measurement in item.get("performance_tests", []):
                setpoint = float(measurement.get("input_voltage", 0))
                verified_limit = max(1.0, setpoint * 0.10)
                for sample_index, sample in enumerate(measurement.get("raw_samples", []), start=1):
                    input_verified = abs(float(sample.get("v_in", 0)) - setpoint) <= verified_limit
                    raw.append(["Performance", f"{measurement.get('input_range_point')} / {measurement.get('load_percent')}%",
                                sample_index, setpoint, measurement.get("target_current"),
                                sample.get("v_in"), sample.get("i_in"), sample.get("p_in"),
                                sample.get("v_out"), sample.get("i_out"), sample.get("p_out"),
                                sample.get("eff"), input_verified,
                                input_verified and float(sample.get("v_out", 0)) >= 2.5,
                                bool(measurement.get("passed"))])

            for sheet in (summary, raw, regulation):
                sheet.freeze_panes = "A2"
                for row in sheet.iter_rows():
                    for cell in row:
                        cell.alignment = Alignment(vertical="center", wrap_text=True)
                for cell in sheet[1]:
                    cell.font = Font(bold=True, color="FFFFFF")
                    cell.fill = PatternFill("solid", fgColor="1E293B")
            for row_number in range(1, summary.max_row + 1):
                if summary.cell(row_number, 1).value in ("Identification measurements", "No-load / full-load performance matrix"):
                    for cell in summary[row_number]:
                        cell.font = Font(bold=True, color="FFFFFF")
                        cell.fill = PatternFill("solid", fgColor="1E293B")
            for column, width in {"A": 30, "B": 22, "C": 16, "D": 16, "E": 16,
                                  "F": 16, "G": 16, "H": 16, "I": 16, "J": 18,
                                  "K": 18, "L": 18, "M": 18, "N": 18}.items():
                summary.column_dimensions[column].width = width
                raw.column_dimensions[column].width = width
                regulation.column_dimensions[column].width = max(width, 24)
            for row_number in (3, 4, 5):
                regulation.merge_cells(start_row=row_number, start_column=1, end_row=row_number, end_column=6)
                regulation.row_dimensions[row_number].height = 32

            output = BytesIO()
            workbook.save(output)
            model_label = model.get("model") or item.get("inference_status") or "unmatched"
            bundle.writestr(f"slot_{item.get('slot')}_{model_label}.xlsx", output.getvalue())

    archive.seek(0)
    filename = "ozak_power_module_test_results.zip"
    return Response(content=archive.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "Cache-Control": "no-cache"})

class DUTSelectRequest(BaseModel):
    model_key: str

@app.get("/api/ports")
async def get_ports():
    """Sistemdeki aktif COM portlarını döndürür."""
    relay_port = RELAY_SELECTOR.port.strip().upper()
    ports = [port for port in MANAGER.get_available_ports()
             if port["device"].strip().upper() != relay_port]
    return {"ports": ports}

@app.get("/api/status")
async def get_status():
    """Sistem genel durumu, HAL ve aktif ürün bilgileri."""
    dut = DUT_CATALOG.get(ACTIVE_DUT_KEY, DUT_CATALOG["OZP50S48SS05A"])
    return {
        "mode": MANAGER.mode,
        "company": "Ozak Power",
        "slogan": "Keep limits out!",
        "dut_key": ACTIVE_DUT_KEY,
        "dut": dut,
        "psu_type": "UNI-T UDP6731 (RS232 SCPI)",
        "psu_port": getattr(MANAGER.psu, "port", "COM5"),
        "psu_connected": MANAGER.psu.is_connected,
        "load_type": "UNI-T UTL8511 (RS232)",
        "load_port": getattr(MANAGER.load._driver, "port", CONFIG.UTL_PORT) if hasattr(MANAGER.load, "_driver") else CONFIG.UTL_PORT,
        "load_connected": MANAGER.load.is_connected,
        "load_enabled": MANAGER.sim_load_enabled if MANAGER.mode == "SIMULATION" else MANAGER.load.load_enabled,
        "active_slot": MANAGER.active_slot,
        "test_active": MANAGER.is_sweep_active,
        "psu_enabled": MANAGER.sim_psu_enabled if MANAGER.mode == "SIMULATION" else MANAGER.psu.get_output_status(),
        "tare_offset": getattr(MANAGER.load, "i_tare_offset", 0.0),
        "target_current": MANAGER.sim_current if MANAGER.mode == "SIMULATION" else MANAGER.load.target_current,
        "peak_efficiency": MANAGER.math_engine.peak_efficiency,
        "active_clients": len(MANAGER.active_websockets),
        "sweep_running": SWEEP_ENGINE.is_running
    }

@app.get("/api/dut/catalog")
async def get_dut_catalog():
    """Ozak Power DC/DC katalog listesini ve güç ailelerini döndürür."""
    return {
        "active_key": ACTIVE_DUT_KEY,
        "families": POWER_FAMILIES,
        "catalog": DUT_CATALOG
    }

@app.get("/api/calibration/slots")
async def get_slot_calibrations():
    return {"profiles": MANAGER.slot_calibrations, "active_slot": MANAGER.active_slot}

@app.post("/api/calibration/capture")
async def capture_slot_calibration_point(req: SlotCalibrationCaptureRequest):
    global SLOT_CALIBRATION_SESSION, SLOT_CALIBRATION_TIMER
    point_name = req.point.strip().upper()
    if req.slot not in range(1, 6) or point_name not in {"A", "B"}:
        return {"status": "error", "message": "Yuva 1-5 ve ölçüm noktası A veya B olmalı."}
    if req.output_current_a <= 0:
        return {"status": "error", "message": "Yük akımı sıfırdan büyük olmalı."}
    if SWEEP_ENGINE.is_running or MODULE_DETECTION_LOCK.locked():
        return {"status": "error", "message": "Başka bir test çalışırken kalibrasyon noktası alınamaz."}
    await ensure_bench_instruments()
    if MANAGER.mode != "HARDWARE" or not MANAGER.psu.is_connected or not MANAGER.load.is_connected:
        return {"status": "error", "message": "Kalibrasyon için donanım modu ve iki cihaz bağlantısı gerekli."}

    dut = DUT_CATALOG.get(ACTIVE_DUT_KEY, DUT_CATALOG["OZP20S24SS33A"])
    vin = float(dut.get("vin_nom", 0))
    vout = float(dut.get("vout_val", 0))
    rated_power = float(dut.get("power_val", 0))
    safe_current = min(float(dut.get("imax_val", 0)), rated_power / max(vout, 0.1),
                       CONFIG.LOAD_TEST_MAX_CURRENT_A)
    if (vin <= 0 or vout <= 0 or rated_power <= 0
            or req.output_current_a > safe_current * 0.75
            or req.output_current_a * vout > rated_power * 0.75):
        return {"status": "error", "message": "Bu akım seçili DUT için güvenli kalibrasyon sınırını aşıyor."}
    if relay_port_conflict(getattr(MANAGER.psu, "port", ""),
                           getattr(MANAGER.load._driver, "port", "")):
        return {"status": "error", "message": "PSU, yük ve Arduino rölesi ayrı COM portlarında olmalı."}

    async with SLOT_CALIBRATION_LOCK:
        if SLOT_CALIBRATION_SESSION and SLOT_CALIBRATION_SESSION["slot"] != req.slot:
            return {"status": "error", "message": f"Yuva {SLOT_CALIBRATION_SESSION['slot']} kalibrasyonu açık. Önce kaydedin veya iptal edin."}
        try:
            if SLOT_CALIBRATION_SESSION is None:
                MANAGER.clear_emergency_stop()
                MANAGER.is_sweep_active = True
                if not MANAGER.set_psu_state(False):
                    raise RuntimeError("Kalibrasyon öncesi PSU kapatılamadı.")
                MANAGER.set_load_current(0.0)
                if not MANAGER.set_load_state(False):
                    raise RuntimeError("Kalibrasyon öncesi elektronik yük kapatılamadı.")
                if not await asyncio.to_thread(RELAY_SELECTOR.connect):
                    raise RuntimeError("Arduino röle denetleyicisine bağlanılamadı.")
                if not await asyncio.to_thread(RELAY_SELECTOR.all_off):
                    raise RuntimeError("Arduino rölelerin kapalı olduğunu doğrulamadı.")
                if not await asyncio.to_thread(RELAY_SELECTOR.select_slot, req.slot):
                    raise RuntimeError(f"Arduino {req.slot}. yuvayı seçtiğini doğrulamadı.")
                MANAGER.set_active_slot(req.slot)
                if not MANAGER.psu.set_current_limit(test_source_current_limit(rated_power, vin)):
                    raise RuntimeError("PSU akım sınırı ayarlanamadı.")
                SLOT_CALIBRATION_SESSION = {
                    "id": uuid.uuid4().hex,
                    "slot": req.slot,
                    "dut": dut["model"],
                    "vin_setpoint_v": vin,
                    "points": {},
                }
                if not MANAGER.set_psu_voltage(vin):
                    raise RuntimeError("Calibration voltage could not be set.")
                if not MANAGER.set_psu_state(True):
                    raise RuntimeError("Calibration PSU output could not be enabled.")
            elif SLOT_CALIBRATION_SESSION["dut"] != dut["model"]:
                raise RuntimeError("Kalibrasyon sırasında DUT modeli değişmiş. Oturumu iptal edip yeniden başlayın.")

            require_test_not_stopped()
            MANAGER.set_load_state(False)
            MANAGER.set_load_current(req.output_current_a)
            if not MANAGER.set_load_state(True):
                raise RuntimeError("Kalibrasyon yükü açılamadı.")
            await guarded_test_sleep(5.0)
            sample = await MANAGER.acquire_and_broadcast(False)
            if (sample["v_in"] < vin * 0.90 or sample["v_out"] < 1.0
                    or sample["i_out"] < req.output_current_a * 0.5):
                raise RuntimeError(
                    f"Yuva {req.slot} ölçümü kararlı değil (Vin {sample['v_in']:.2f} V, "
                    f"Vout {sample['v_out']:.2f} V, Iout {sample['i_out']:.3f} A)."
                )
            raw_point = {
                "iin_a": sample["i_in"],
                "vin_source_v": sample["v_in"],
                "iout_a": sample["i_out"],
                "vout_load_v": sample["v_out"],
                "output_current_target_a": req.output_current_a,
            }
            SLOT_CALIBRATION_SESSION["points"][point_name] = raw_point
            if SLOT_CALIBRATION_TIMER is not None:
                SLOT_CALIBRATION_TIMER.cancel()
            session_id = SLOT_CALIBRATION_SESSION["id"]
            SLOT_CALIBRATION_TIMER = asyncio.create_task(expire_slot_calibration(session_id))
            return {
                "status": "ready",
                "slot": req.slot,
                "point": point_name,
                "dut": dut["model"],
                "setpoint_v": vin,
                "output_current_target_a": req.output_current_a,
                "instrument_readings": raw_point,
                "message": "Modül pinlerinde multimetre ölçümünü alın; kayıt sırasında PSU ve yük açık kalır.",
            }
        except Exception as exc:
            session_id = SLOT_CALIBRATION_SESSION.get("id") if SLOT_CALIBRATION_SESSION else None
            if session_id:
                await finish_slot_calibration(session_id)
            else:
                MANAGER.set_load_current(0.0)
                MANAGER.set_load_state(False)
                MANAGER.set_psu_state(False)
                if await asyncio.to_thread(RELAY_SELECTOR.all_off):
                    MANAGER.set_active_slot(None)
                    await asyncio.to_thread(RELAY_SELECTOR.disconnect)
                MANAGER.is_sweep_active = False
            return {"status": "error", "message": str(exc)}

@app.post("/api/calibration/slot/save")
async def save_captured_slot_calibration(req: SlotCalibrationSaveRequest):
    if req.slot not in range(1, 6):
        return {"status": "error", "message": "Yuva numarası 1 ile 5 arasında olmalı."}
    session = SLOT_CALIBRATION_SESSION
    if not session or session["slot"] != req.slot:
        return {"status": "error", "message": "Bu yuva için önce A ve B ölçüm noktalarını alın."}
    if not all(name in session["points"] for name in ("A", "B")):
        return {"status": "error", "message": "Kalibrasyon için hem A hem B ölçüm noktası gerekli."}
    try:
        points = []
        for name in ("A", "B"):
            refs = req.references.get(name, {})
            point = dict(session["points"][name])
            point["vin_dut_v"] = float(refs["vin_dut_v"])
            point["vout_dut_v"] = float(refs["vout_dut_v"])
            points.append(point)
        profile = build_profile(points)
        MANAGER.slot_calibrations[str(req.slot)] = profile
        save_profiles(MANAGER.slot_calibrations)
    except (ValueError, KeyError, TypeError) as exc:
        return {"status": "error", "message": f"Kalibrasyon kaydedilemedi: {exc}"}
    await finish_slot_calibration(session["id"])
    return {"status": "success", "slot": req.slot, "profile": profile}

@app.post("/api/calibration/cancel")
async def cancel_slot_calibration():
    session_id = SLOT_CALIBRATION_SESSION.get("id") if SLOT_CALIBRATION_SESSION else None
    if session_id:
        await finish_slot_calibration(session_id)
    return {"status": "stopped"}

@app.post("/api/calibration/slot")
async def save_slot_calibration(req: SlotCalibrationRequest):
    if req.slot not in range(1, 6):
        return {"status": "error", "message": "Yuva numarası 1 ile 5 arasında olmalı."}
    try:
        profile = build_profile([point.model_dump() for point in req.points])
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    MANAGER.slot_calibrations[str(req.slot)] = profile
    save_profiles(MANAGER.slot_calibrations)
    return {"status": "success", "slot": req.slot, "profile": profile}

@app.post("/api/dut/select")
async def select_dut(req: DUTSelectRequest):
    """Test edilen DC/DC ürün modelini seçer."""
    global ACTIVE_DUT_KEY
    if MODULE_DETECTION_LOCK.locked() or SWEEP_ENGINE.is_running:
        return {"status": "error", "message": "Test sırasında katalog modeli değiştirilemez."}
    if req.model_key in DUT_CATALOG:
        ACTIVE_DUT_KEY = req.model_key
        SWEEP_ENGINE.set_dut_model(DUT_CATALOG[ACTIVE_DUT_KEY]["model"])
        return {"status": "success", "dut": DUT_CATALOG[ACTIVE_DUT_KEY]}
    return {"status": "error", "message": "Geçersiz model anahtarı"}

@app.post("/api/sweep/start")
async def start_sweep(cfg: SweepConfig):
    global ACTIVE_DUT_KEY
    """Otomatik verimlilik taramasını başlatır."""
    if SWEEP_ENGINE.is_running:
        return {"status": "error", "message": "Verimlilik taraması zaten çalışıyor."}
    if SLOT_CALIBRATION_SESSION is not None:
        return {"status": "error", "message": "Yuva kalibrasyonu tamamlanmalı veya iptal edilmeli."}
    if MODULE_DETECTION_LOCK.locked():
        return {"status": "error", "message": "Başka bir modül testi çalışırken verimlilik taraması başlatılamaz."}
    if MANAGER.mode != "HARDWARE":
        return {"status": "error", "message": "Verimlilik taraması için donanım modu gerekli."}
    await ensure_bench_instruments()
    if not MANAGER.psu.is_connected or not MANAGER.load.is_connected:
        return {"status": "error", "message": "PSU ve elektronik yük bağlantılarını kontrol edin."}
    if cfg.slot not in range(1, 6):
        return {"status": "error", "message": "Test yuvası 1 ile 5 arasında olmalı."}
    powers = (cfg.start_power_w, cfg.end_power_w, cfg.step_power_w)
    if any(not math.isfinite(value) or value <= 0 for value in powers) or cfg.end_power_w < cfg.start_power_w:
        return {"status": "error", "message": "Invalid power range or step."}
    if (cfg.end_power_w - cfg.start_power_w) / cfg.step_power_w > 1000:
        return {"status": "error", "message": "Too many power steps."}

    if cfg.rated_power_w not in (20, 50, 100, 300):
        return {"status": "error", "message": "Modül gücü 20, 50, 100 veya 300 W olmalı."}
    detection = await run_module_detection(
        only_slot=cfg.slot, run_performance=False, power_family=f"{cfg.rated_power_w}W")
    detected = next((item for item in detection.get("results", []) if item["slot"] == cfg.slot), None)
    if detection.get("status") != "complete" or not detected or detected.get("inference_status") != "identified":
        return {"status": "error", "message": (detected or detection).get(
            "message", "Modül tek bir katalog modeliyle eşleşmedi; tarama başlatılmadı.")}
    if MANAGER.emergency_stop_latched:
        return {"status": "error", "message": "Acil stop aktif; tarama başlatılmadı."}
    dut = detected["model"]
    ACTIVE_DUT_KEY = detected["model_key"]
    vin = float(dut.get("vin_nom", 0))
    vout = catalog_output_span_v(dut)
    max_current = min(float(dut.get("imax_val", 0)),
                      float(dut.get("power_val", 0)) / max(vout, 0.1),
                      CONFIG.LOAD_TEST_MAX_CURRENT_A)
    if vin <= 0 or vout <= 0 or max_current <= 0:
        return {"status": "error", "message": "Seçili modülün güvenli test değerleri katalogda bulunamadı."}
    max_power = min(float(dut["power_val"]), round(max_current * vout, 2))
    cfg.end_power_w = min(cfg.end_power_w, max_power)
    if cfg.start_power_w > cfg.end_power_w:
        return {"status": "error", "message": "Requested power exceeds the detected module rating."}
    cfg.output_voltage_v = vout
    cfg.max_load_current_a = max_current

    psu_port = getattr(MANAGER.psu, "port", "")
    load_port = getattr(MANAGER.load._driver, "port", "")
    if relay_port_conflict(psu_port, load_port) or psu_port.strip().upper() == load_port.strip().upper():
        return {"status": "error", "message": "PSU, elektronik yük ve Arduino rölesi farklı COM portlarında olmalı."}

    await MODULE_DETECTION_LOCK.acquire()
    if SWEEP_ENGINE.is_running:
        MODULE_DETECTION_LOCK.release()
        return {"status": "error", "message": "Verimlilik taraması zaten çalışıyor."}
    SWEEP_ENGINE.set_dut_model(dut["model"])
    MANAGER.clear_emergency_stop()
    MANAGER.is_sweep_active = True
    try:
        if not MANAGER.set_psu_state(False):
            raise RuntimeError("Yuva değişiminden önce PSU kapatılamadı.")
        MANAGER.set_load_current(0.0)
        if not MANAGER.set_load_state(False):
            raise RuntimeError("Yuva değişiminden önce elektronik yük kapatılamadı.")
        if not await asyncio.to_thread(RELAY_SELECTOR.connect):
            raise RuntimeError(f"Arduino röle denetleyicisine {RELAY_SELECTOR.port} üzerinden bağlanılamadı.")
        require_test_not_stopped()
        if not await asyncio.to_thread(RELAY_SELECTOR.all_off):
            raise RuntimeError("Arduino röleleri kapalı konumda olduğunu doğrulamadı.")
        require_test_not_stopped()
        if not await asyncio.to_thread(RELAY_SELECTOR.select_slot, cfg.slot):
            raise RuntimeError(f"Arduino {cfg.slot}. yuvayı seçtiğini doğrulamadı.")
        MANAGER.set_active_slot(cfg.slot)
        require_test_not_stopped()

        if not MANAGER.psu.set_current_limit(test_source_current_limit(float(dut["power_val"]), vin)):
            raise RuntimeError("PSU giriş akım sınırı ayarlanamadı.")
        # Program voltage, then explicitly enable the selected slot's supply.
        MANAGER.set_psu_voltage(vin)
        if not MANAGER.set_psu_state(True):
            raise RuntimeError("PSU output could not be enabled for the sweep.")
        MANAGER.set_load_current(0.05)
        if not MANAGER.set_load_state(True):
            raise RuntimeError("Modül varlık kontrolü için elektronik yük açılamadı.")
        await asyncio.sleep(2.0)
        require_test_not_stopped()
        presence = await MANAGER.acquire_and_broadcast()
        require_test_not_stopped()
        if (presence["v_in"] < vin * 0.90
                or presence["v_out"] < max(1.0, vout * 0.5)
                or presence["p_out"] < 0.02):
            raise RuntimeError(
                f"Yuva {cfg.slot} modül çıkışı doğrulanamadı "
                f"(Vin {presence['v_in']:.2f} V, Vout {presence['v_out']:.2f} V, "
                f"Pout {presence['p_out']:.2f} W). Tarama başlatılmadı."
            )
        MANAGER.set_load_state(False)
        MANAGER.set_load_current(0.0)
        ok = await SWEEP_ENGINE.start(MANAGER, cfg, RELAY_SELECTOR)
        if not ok:
            raise RuntimeError("Verimlilik taraması başlatılamadı.")
        return {"status": "started", "config": cfg.model_dump(), "dut": dut["model"],
                "model_key": ACTIVE_DUT_KEY, "detected_model": dut}
    except Exception as exc:
        MANAGER.set_load_state(False)
        MANAGER.set_load_current(0.0)
        source_disabled = MANAGER.set_psu_state(False)
        if source_disabled:
            await asyncio.to_thread(RELAY_SELECTOR.all_off)
            MANAGER.set_active_slot(None)
        MANAGER.is_sweep_active = False
        return {"status": "error", "message": str(exc)}
    finally:
        if MODULE_DETECTION_LOCK.locked():
            MODULE_DETECTION_LOCK.release()

@app.post("/api/sweep/stop")
async def stop_sweep():
    """Taramayı durdurur."""
    SWEEP_ENGINE.stop(MANAGER)
    MANAGER.set_load_state(False)
    MANAGER.set_load_current(0.0)
    source_disabled = MANAGER.set_psu_state(False)
    if source_disabled:
        await asyncio.to_thread(RELAY_SELECTOR.all_off)
        MANAGER.set_active_slot(None)
    return {"status": "stopped"}

@app.get("/api/sweep/status")
async def sweep_status():
    """Tarama ilerleme durumu ve toplanan veri noktaları."""
    return SWEEP_ENGINE.get_status()

@app.get("/api/sweep/export-csv")
async def export_sweep_csv():
    """Toplanan test verilerini kurumsal Ozak Power CSV dosyası olarak indirir."""
    dut = DUT_CATALOG.get(ACTIVE_DUT_KEY, DUT_CATALOG["OZP50S48SS05A"])
    csv_text = SWEEP_ENGINE.generate_csv(dut_catalog_eff=dut["typ_eff_str"])
    filename = f"ozak_power_sweep_{dut['model']}.csv"
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache"
        }
    )

@app.post("/api/mode")
async def set_mode(req: ModeRequest):
    if SLOT_CALIBRATION_SESSION:
        return {"status": "error", "message": "Mode is locked during slot calibration."}
    """Çalışma modunu değiştirir: SIMULATION veya HARDWARE."""
    target_mode = req.mode.upper()
    if target_mode not in {"HARDWARE", "SIMULATION"}:
        return {"status": "error", "message": "Geçersiz mod."}
    if MODULE_DETECTION_LOCK.locked() or SWEEP_ENGINE.is_running:
        return {"status": "error", "message": "Test sürerken mod değiştirilemez."}
    if target_mode == MANAGER.mode:
        return {"status": "success", "mode": MANAGER.mode}
    async with MODULE_DETECTION_LOCK:
        MANAGER.is_sweep_active = True
        try:
            if MANAGER.mode == "HARDWARE":
                if MANAGER.psu.is_connected and not MANAGER.set_psu_state(False):
                    raise RuntimeError("PSU kapatılamadı; mod değiştirilmedi.")
                if MANAGER.load.is_connected and not MANAGER.set_load_state(False):
                    raise RuntimeError("Yük kapatılamadı; mod değiştirilmedi.")
                if MANAGER.active_slot is not None and not await asyncio.to_thread(RELAY_SELECTOR.all_off):
                    raise RuntimeError("Röleler kapatılamadı; mod değiştirilmedi.")
            MANAGER.set_active_slot(None)
            updated = await asyncio.to_thread(MANAGER.set_mode, target_mode)
            MANAGER.last_frame = None
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        finally:
            MANAGER.is_sweep_active = False
    return {"status": "success", "mode": updated}


async def release_idle_relays() -> bool:
    """Release the selected relay after both manual outputs have been disabled."""
    if MANAGER.psu.get_output_status() or MANAGER.load.load_enabled:
        return True
    if MANAGER.mode != "HARDWARE":
        MANAGER.set_active_slot(None)
        return True
    if MODULE_DETECTION_LOCK.locked() or SWEEP_ENGINE.is_running or SLOT_CALIBRATION_SESSION:
        return False
    async with MODULE_DETECTION_LOCK:
        if MANAGER.psu.get_output_status() or MANAGER.load.load_enabled:
            return True
        if not await asyncio.to_thread(RELAY_SELECTOR.all_off):
            return False
        MANAGER.set_active_slot(None)
        return True


@app.post("/api/load/state")
async def set_load_state(req: LoadStateRequest):
    """UTL8511 yükünü açar (LOAD ON) veya kapatır (LOAD OFF)."""
    if MANAGER.emergency_stop_latched and req.enabled:
        return {"status": "error", "message": "Acil stop kilitli; devam etmek için yeni bir test başlatın."}
    if MANAGER.mode == "HARDWARE" and not MANAGER.load.is_connected:
        return {"status": "error", "message": "Elektronik yük bağlı değil; COM bağlantısını kontrol edin."}
    res = MANAGER.set_load_state(req.enabled)
    if not res:
        return {"status": "error", "message": "Elektronik yük aç/kapat komutu gönderilemedi."}
    if not req.enabled and not await release_idle_relays():
        return {"status": "error", "message": "Yük kapandı ancak rölelerin bırakılması doğrulanamadı."}
    return {"status": "success", "load_enabled": MANAGER.sim_load_enabled if MANAGER.mode == "SIMULATION" else MANAGER.load.load_enabled,
            "active_slot": MANAGER.active_slot}

@app.post("/api/psu/state")
async def set_psu_state(req: PSUStateRequest):
    """UNI-T UDP6731 güç kaynağı çıkışını açar (OUTP ON) veya kapatır (OUTP OFF)."""
    if MANAGER.emergency_stop_latched and req.enabled:
        return {"status": "error", "message": "Acil stop kilitli; devam etmek için yeni bir test başlatın."}
    if MANAGER.mode == "HARDWARE" and not MANAGER.psu.is_connected:
        return {"status": "error", "message": "Güç kaynağı bağlı değil; COM bağlantısını kontrol edin."}
    if req.enabled and MANAGER.mode == "HARDWARE":
        if req.slot not in range(1, 6):
            return {"status": "error", "message": "Önce 1–5 arasında bir yuva seçin."}
        if SLOT_CALIBRATION_SESSION or MODULE_DETECTION_LOCK.locked() or SWEEP_ENGINE.is_running:
            return {"status": "error", "message": "Test veya kalibrasyon sırasında röle değiştirilemez."}
        if relay_port_conflict(getattr(MANAGER.psu, "port", ""),
                               getattr(MANAGER.load._driver, "port", "")):
            return {"status": "error", "message": "Arduino, PSU ve yük farklı COM portlarında olmalı."}
        async with MODULE_DETECTION_LOCK:
            try:
                if not MANAGER.set_load_state(False):
                    raise RuntimeError("Elektronik yük kapatılamadı.")
                if not MANAGER.set_psu_state(False):
                    raise RuntimeError("Röle seçimi öncesinde PSU kapatılamadı.")
                if not await asyncio.to_thread(RELAY_SELECTOR.connect):
                    raise RuntimeError("Arduino bağlantısı kurulamadı.")
                if not await asyncio.to_thread(RELAY_SELECTOR.all_off):
                    raise RuntimeError("Röleler kapatılamadı.")
                MANAGER.set_active_slot(None)
                if not await asyncio.to_thread(RELAY_SELECTOR.select_slot, req.slot):
                    raise RuntimeError("Seçilen röle Arduino tarafından doğrulanamadı.")
                MANAGER.set_active_slot(req.slot)
                require_test_not_stopped()
                voltage = 24.0
                limit = test_source_current_limit(float(DUT_CATALOG[ACTIVE_DUT_KEY]["power_val"]), voltage)
                if not MANAGER.psu.set_current_limit(limit):
                    raise RuntimeError("PSU akım sınırı ayarlanamadı.")
                MANAGER.set_psu_voltage(voltage)
                if not MANAGER.set_psu_state(True):
                    raise RuntimeError("PSU açılamadı.")
                return {"status": "success", "psu_enabled": True,
                        "active_slot": req.slot, "load_enabled": False, "hw_result": True,
                        "voltage_v": voltage, "current_limit_a": limit}
            except Exception as exc:
                if MANAGER.set_psu_state(False):
                    if await asyncio.to_thread(RELAY_SELECTOR.all_off):
                        MANAGER.set_active_slot(None)
                return {"status": "error", "message": str(exc)}
    res = MANAGER.set_psu_state(req.enabled)
    if not res:
        return {"status": "error", "message": "PSU aç/kapat komutu gönderilemedi."}
    if not req.enabled and not await release_idle_relays():
        return {"status": "error", "message": "PSU kapandı ancak rölelerin bırakılması doğrulanamadı."}
    return {
        "status": "success",
        "psu_enabled": req.enabled,
        "active_slot": MANAGER.active_slot,
        "hw_result": res
    }

@app.post("/api/bench/slot-power")
async def power_selected_slot(req: SlotPowerRequest):
    """Select one relay slot and leave the PSU at a guarded voltage until stopped."""
    if req.slot not in range(1, 6):
        return {"status": "error", "message": "Yuva numarası 1 ile 5 arasında olmalı."}
    if req.voltage not in (10.0, 24.0):
        return {"status": "error", "message": "Bu işlem yalnızca 10 V veya 24 V için etkin."}
    if MANAGER.mode != "HARDWARE" or not await ensure_bench_instruments():
        return {"status": "error", "message": "PSU ve elektronik yük bağlantısı doğrulanamadı."}
    if SLOT_CALIBRATION_SESSION or MODULE_DETECTION_LOCK.locked() or SWEEP_ENGINE.is_running:
        return {"status": "error", "message": "Başka bir test/kalibrasyon çalışırken yuva enerjilenemez."}
    if relay_port_conflict(getattr(MANAGER.psu, "port", ""),
                           getattr(MANAGER.load._driver, "port", "")):
        return {"status": "error", "message": "PSU, yük ve Arduino farklı COM portlarında olmalı."}

    async with MODULE_DETECTION_LOCK:
        try:
            if not MANAGER.set_load_state(False):
                raise RuntimeError("Elektronik yük kapatılamadı.")
            MANAGER.set_load_current(0.0)
            if not MANAGER.set_psu_state(False):
                raise RuntimeError("Yuva değiştirmeden önce PSU kapatılamadı.")
            if not await asyncio.to_thread(RELAY_SELECTOR.connect):
                raise RuntimeError(f"Arduino {RELAY_SELECTOR.port} portunda bulunamadı.")
            if not await asyncio.to_thread(RELAY_SELECTOR.all_off):
                raise RuntimeError("Arduino rölelerin kapalı olduğunu onaylamadı.")
            if not await asyncio.to_thread(RELAY_SELECTOR.select_slot, req.slot):
                raise RuntimeError(f"Arduino {req.slot}. yuvayı seçtiğini onaylamadı.")
            MANAGER.set_active_slot(req.slot)
            dut = DUT_CATALOG[ACTIVE_DUT_KEY]
            source_limit = test_source_current_limit(float(dut["power_val"]), req.voltage)
            if not MANAGER.psu.set_current_limit(source_limit):
                raise RuntimeError("PSU input current limit could not be set.")
            MANAGER.set_psu_voltage(req.voltage)
            if not MANAGER.set_psu_state(True):
                raise RuntimeError("PSU output could not be enabled.")
            if not MANAGER.psu.get_output_status():
                raise RuntimeError("PSU output could not be enabled.")
            MANAGER.clear_emergency_stop()
            return {"status": "powered", "slot": req.slot, "voltage_v": req.voltage,
                    "current_limit_a": source_limit,
                    "input_power_limit_w": float(dut["power_val"]) * 1.5, "load_enabled": False,
                    "message": "Yuva enerjili kalacak; kapatmak için ACİL STOP kullanın."}
        except Exception as exc:
            MANAGER.set_load_current(0.0)
            MANAGER.set_load_state(False)
            MANAGER.set_psu_state(False)
            if await asyncio.to_thread(RELAY_SELECTOR.all_off):
                MANAGER.set_active_slot(None)
            return {"status": "error", "message": str(exc)}

@app.post("/api/emergency-stop")
async def emergency_stop():
    """
    Akıllı Acil Stop: Hem Güç Kaynağını (PSU) hem de Elektronik Yükü (Load)
    derhal kapatır, akımı sıfırlar.
    """
    global SLOT_CALIBRATION_SESSION, SLOT_CALIBRATION_TIMER
    timer = SLOT_CALIBRATION_TIMER
    SLOT_CALIBRATION_TIMER = None
    SLOT_CALIBRATION_SESSION = None
    if timer is not None:
        timer.cancel()
    MANAGER.is_sweep_active = False
    res = MANAGER.emergency_stop()
    relay_disabled = (True if MANAGER.mode == "SIMULATION"
                      else await asyncio.to_thread(RELAY_SELECTOR.all_off))
    MANAGER.set_active_slot(None)
    SWEEP_ENGINE.stop(MANAGER)
    res["relays_disabled"] = relay_disabled
    return {"status": "success", "result": res}

@app.post("/api/load/current")
async def set_load_current(req: LoadCurrentRequest):
    """Hedef test akımını ayarlar."""
    if MANAGER.emergency_stop_latched and req.current > 0:
        return {"status": "error", "message": "Acil stop kilitli; devam etmek için yeni bir test başlatın."}
    if SLOT_CALIBRATION_SESSION:
        return {"status": "error", "message": "Load current is locked during slot calibration."}
    res = MANAGER.set_load_current(req.current)
    return {"status": "success", "target_current": MANAGER.load.target_current}

@app.post("/api/load/tare")
async def tare_load():
    """UTL8511 yükündeki artık akımı sıfırlar (Tare / Zero Offset)."""
    offset = MANAGER.tare_load()
    return {"status": "success", "tare_offset": offset}

@app.post("/api/load/tare/reset")
async def reset_tare():
    """Tare ofsetini sıfırlar."""
    MANAGER.reset_tare()
    return {"status": "success"}


class PSUCalibrateRequest(BaseModel):
    psu_setpoint_v: float = 48.0
    measured_vin: float = 47.90
    measured_iin: float = 0.449
    manual_fixed: bool = False

@app.get("/api/telemetry/latest")
async def get_latest_telemetry():
    """Son telemetri karesini döndürür."""
    if MANAGER.last_frame:
        return MANAGER.last_frame.model_dump()
    return {}

@app.get("/api/psu/calibrate")
async def get_psu_calibration():
    """Mevcut güç kaynağı ve telemetri parametrelerini döndürür."""
    psu = MANAGER.psu
    return {
        "nominal_vin": getattr(psu, "nominal_vin", 48.0),
        "cable_resistance": 0.0,
        "manual_fixed": getattr(psu, "manual_fixed", False),
        "manual_vin": getattr(psu, "manual_vin", 48.00),
        "manual_iin": getattr(psu, "manual_iin", 0.449),
        "description": "UNI-T UDP6731 4-Wire Sense & SCPI Doğrudan Okuma (0.00V Düşüm)"
    }

@app.post("/api/psu/calibrate")
async def calibrate_psu(req: PSUCalibrateRequest):
    if MANAGER.emergency_stop_latched:
        return {"status": "error", "message": "Acil stop kilitli; devam etmek için yeni bir test başlatın."}
    """Güç kaynağı gerilimini ayarlar."""
    MANAGER.calibrate_psu(
        psu_setpoint_v=req.psu_setpoint_v,
        measured_vin=req.measured_vin,
        measured_iin=req.measured_iin,
        manual_fixed=req.manual_fixed
    )
class PSUVoltageRequest(BaseModel):
    voltage: float = 48.0

@app.post("/api/psu/voltage")
async def set_psu_voltage(req: PSUVoltageRequest):
    if MANAGER.emergency_stop_latched:
        return {"status": "error", "message": "Acil stop kilitli; devam etmek için yeni bir test başlatın."}
    """Test gerilim noktasını (18V, 48V, 72V vb.) seçer ve donanıma SCPI gönderir."""
    if SLOT_CALIBRATION_SESSION:
        return {"status": "error", "message": "PSU voltage is locked during slot calibration."}
    v_dut, drop = MANAGER.set_psu_voltage(req.voltage)
    return {
        "status": "success",
        "setpoint_v": req.voltage,
        "calibrated_vin": round(v_dut, 2),
        "cable_drop": 0.0
    }

@app.post("/api/ports/configure")
async def configure_ports(req: PortConfigRequest):
    if SLOT_CALIBRATION_SESSION:
        return {"status": "error", "message": "Ports are locked during slot calibration."}
    """Cihaz seri portlarını ayarlar."""
    psu_target = req.psu_port or req.hmp_port
    effective_psu = psu_target or getattr(MANAGER.psu, "port", "")
    effective_load = req.utl_port or getattr(MANAGER.load._driver, "port", "")
    if req.utl_port and req.utl_port.strip().upper() == RELAY_SELECTOR.port.strip().upper():
        return {"status": "error", "message": f"{RELAY_SELECTOR.port} Arduino röle denetleyicisi için ayrılmıştır; yük portu olamaz."}
    if relay_port_conflict(effective_psu, effective_load):
        return {"status": "error", "message": f"Port {RELAY_SELECTOR.port} Arduino röle denetleyicisine ayrılmıştır."}
    if effective_psu and effective_load and effective_psu.strip().upper() == effective_load.strip().upper():
        return {"status": "error", "message": "PSU ve elektronik yük ayrı COM portlarında olmalıdır."}
    MANAGER.configure_ports(psu_target, req.utl_port)
    return {
        "status": "success",
        "psu_port": getattr(MANAGER.psu, "port", "COM5"),
        "utl_port": req.utl_port
    }

@app.post("/api/ports/ensure")
async def ensure_default_ports():
    """Verify configured devices, then rediscover them by SCPI identity if COM numbers moved."""
    if MANAGER.mode == "SIMULATION":
        return {"status": "success", "mode": "SIMULATION", "message": "Simülasyonda donanım portları açılmaz."}
    relay_port = RELAY_SELECTOR.port.strip().upper()
    psu_port = getattr(MANAGER.psu, "port", CONFIG.PSU_PORT)
    load_port = getattr(MANAGER.load._driver, "port", CONFIG.UTL_PORT)

    try:
        psu_id = (MANAGER.psu._query("*IDN?") or "").upper()
    except Exception:
        psu_id = ""
    try:
        load_id = (MANAGER.load._driver.query("*IDN?") or "").upper()
        load_input = (MANAGER.load._driver.query(":INP?") or "").strip().upper()
    except Exception:
        load_id, load_input = "", ""

    psu_valid = "UDP6731" in psu_id or ("UNI-T" in psu_id and "UTL8511" not in psu_id)
    # Match the UTL8511 driver's own identity contract; some firmware does
    # not implement *IDN? or SYST:REM? but reliably answers :INP?.
    load_valid = "UTL8511" in load_id or load_input in {"0", "1", "ON", "OFF"}
    if not psu_valid:
        MANAGER.psu.disconnect()
    if not load_valid or load_port.strip().upper() == relay_port:
        MANAGER.load.disconnect()

    # Keep already verified, open instrument ports out of the scan. Probe the
    # remaining ports by identity so changed Windows COM assignments are found.
    excluded = {relay_port}
    if psu_valid:
        excluded.add(psu_port.strip().upper())
    if load_valid:
        excluded.add(load_port.strip().upper())
    discovered = await asyncio.to_thread(MANAGER.discover_instrument_ports, excluded)

    if not psu_valid:
        psu_port = discovered.get("psu") or psu_port or CONFIG.PSU_PORT
    if not load_valid or load_port.strip().upper() == relay_port:
        load_port = discovered.get("load") or load_port or CONFIG.UTL_PORT
    if psu_port.strip().upper() == relay_port or psu_port.strip().upper() == load_port.strip().upper():
        psu_port = CONFIG.PSU_PORT
    if load_port.strip().upper() in {relay_port, psu_port.strip().upper()}:
        load_port = CONFIG.UTL_PORT

    MANAGER.configure_ports(psu_port, load_port)
    psu_connected = MANAGER.psu.is_connected
    load_connected = MANAGER.load.is_connected
    return {
        "status": "success" if psu_connected and load_connected else "error",
        "psu_port": getattr(MANAGER.psu, "port", CONFIG.PSU_PORT),
        "psu_connected": psu_connected,
        "psu_id": psu_id or None,
        "load_port": getattr(MANAGER.load._driver, "port", CONFIG.UTL_PORT),
        "load_connected": load_connected,
        "load_id": load_id or None,
        "discovered": discovered,
        "message": None if psu_connected and load_connected else "Cihazlardan biri bulunamad?. USB/RS232 ba?lant?s?n? ve cihaz?n a??k oldu?unu kontrol edin."
    }

@app.post("/api/debug/scpi")
async def debug_scpi(req: dict):
    cmd = req.get("cmd", "*IDN?")
    is_query = "?" in cmd
    if is_query:
        res = MANAGER.load._driver.query(cmd)
    else:
        res = MANAGER.load._driver.write(cmd)
    return {"cmd": cmd, "response": res, "connected": MANAGER.load.is_connected}

@app.post("/api/debug/psu-scpi")
async def debug_psu_scpi(req: dict):
    cmd = req.get("cmd", "*IDN?")
    is_query = "?" in cmd
    if is_query:
        res = MANAGER.psu._query(cmd)
    else:
        res = MANAGER.psu._write(cmd)
    return {"cmd": cmd, "response": res, "connected": MANAGER.psu.is_connected}

@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    """Tarayıcılar için 250ms canlı telemetri veri akışı."""
    await MANAGER.register_client(websocket)
    try:
        while True:
            # İstemciden gelebilecek komutları dinle
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        MANAGER.unregister_client(websocket)
    except Exception:
        MANAGER.unregister_client(websocket)

# Frontend Statik Dosyalarını Sunma
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
