"""
Telemetri Yöneticisi ve WebSocket Yayın Motoru (HAL Destekli)
Mock Power Supply ve UTL8511 Elektronik Yükü koordine eder, 250ms periyotla telemetri yayınlar.
"""
import asyncio
import json
import logging
from typing import Set, List, Dict, Any, Optional, Tuple
import serial.tools.list_ports
import serial
from fastapi import WebSocket

from .config import CONFIG
from .math_engine import MathEngine, TelemetryFrame, ChannelTelemetry
from .hal import MockPowerSupply, UTL8511Load, UnitUDP6731PowerSupply
from .slot_calibration import load_profiles
from .simulator import ConverterSimulator

logger = logging.getLogger("TelemetryManager")

class TelemetryManager:
    def __init__(self):
        self.mode: str = getattr(CONFIG, "INITIAL_MODE", "HARDWARE")
        self.math_engine = MathEngine()

        # HAL Donanım Nesneleri (UNI-T UDP6731 Güç Kaynağı & UNI-T UTL8511 Elektronik Yük)
        psu_port = getattr(CONFIG, "PSU_PORT", "COM5")
        psu_baud = getattr(CONFIG, "PSU_BAUDRATE", 9600)
        load_port = getattr(CONFIG, "UTL_PORT", "COM4")
        load_baud = getattr(CONFIG, "UTL_BAUDRATE", 9600)

        self.psu = UnitUDP6731PowerSupply(port=psu_port, baudrate=psu_baud, nominal_vin=48.0)
        self.load = UTL8511Load(port=load_port, baudrate=load_baud)

        # Aktif WebSocket Bağlantıları
        self.active_websockets: Set[WebSocket] = set()

        # Son üretilen çerçeve
        self.last_frame: Optional[TelemetryFrame] = None
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self.is_sweep_active: bool = False
        self.emergency_stop_latched: bool = False
        self.active_slot: Optional[int] = None
        self.simulator = ConverterSimulator()
        self.sim_psu_enabled = True
        self.sim_load_enabled = True
        self.sim_voltage = 24.0
        self.sim_current = 2.0
        self.slot_calibrations = load_profiles()

    def set_active_slot(self, slot: Optional[int]) -> None:
        self.active_slot = slot if slot in range(1, 6) else None

    def apply_slot_calibration(self, channels, total_vin: float, i_in: float,
                               v_out: float, i_out: float):
        """Correct PSU/load terminal readings to DUT-pin readings for the active slot."""
        if self.mode != "HARDWARE" or self.active_slot is None:
            p_in = total_vin * i_in
            p_out = v_out * i_out
            return channels, total_vin, p_in, v_out, p_out

        profile = self.slot_calibrations.get(str(self.active_slot), {})
        vin_drop = (float(profile.get("input_drop_offset_v", 0.0))
                    + float(profile.get("input_resistance_ohm", 0.0)) * i_in)
        vout_gain = (float(profile.get("output_gain_offset_v", 0.0))
                     + float(profile.get("output_resistance_ohm", 0.0)) * i_out)
        corrected_vin = max(0.0, total_vin - vin_drop)
        corrected_vout = max(0.0, v_out + vout_gain)

        if total_vin > 0 and channels:
            voltage_scale = corrected_vin / total_vin
            corrected_channels = [
                ch.__class__(channel_id=ch.channel_id,
                             voltage=max(0.0, ch.voltage * voltage_scale),
                             current=ch.current,
                             power=max(0.0, ch.voltage * voltage_scale) * ch.current,
                             sense_ok=ch.sense_ok)
                for ch in channels
            ]
        else:
            corrected_channels = channels
        return (corrected_channels, corrected_vin, corrected_vin * i_in,
                corrected_vout, corrected_vout * i_out)

    @staticmethod
    def get_available_ports() -> List[Dict[str, str]]:
        """Windows sistemindeki tüm seri COM portlarını listeler."""
        ports = serial.tools.list_ports.comports()
        return [
            {
                "device": p.device,
                "description": p.description or "Seri Port",
                "hwid": p.hwid or ""
            }
            for p in ports
        ]

    def discover_instrument_ports(self, excluded_ports: Optional[Set[str]] = None) -> Dict[str, Optional[str]]:
        """Find PSU and load by their SCPI identity response, without changing outputs."""
        excluded = {str(p).strip().upper() for p in (excluded_ports or set()) if p}
        found: Dict[str, Optional[str]] = {"psu": None, "load": None}
        for item in serial.tools.list_ports.comports():
            port = item.device
            if port.strip().upper() in excluded:
                continue
            try:
                with serial.Serial(port, 9600, timeout=0.35, write_timeout=0.35) as probe:
                    def query(command: bytes) -> str:
                        probe.reset_input_buffer()
                        probe.write(command + b"\n")
                        probe.flush()
                        return probe.readline().decode("ascii", errors="ignore").strip().upper()

                    identity = query(b"*IDN?")
                    if "UDP6731" in identity or ("UNI-T" in identity and "UTL8511" not in identity):
                        found["psu"] = port
                        continue
                    if "UTL8511" in identity:
                        found["load"] = port
                        continue

                    # Some UTL8511 firmware returns ERR for *IDN? but supports
                    # these read-only status queries. Require both responses so
                    # a generic USB-serial device or the relay Arduino cannot match.
                    input_status = query(b":INP?")
                    remote_status = query(b"SYST:REM?")
                    if input_status in {"0", "1", "ON", "OFF"} and remote_status in {"0", "1", "ON", "OFF"}:
                        found["load"] = port
            except (serial.SerialException, OSError) as exc:
                logger.debug("Port kimlik sorgusu başarısız (%s): %s", port, exc)
        return found

    def set_mode(self, new_mode: str) -> str:
        """Çalışma modunu değiştirir: 'SIMULATION' veya 'HARDWARE'."""
        mode_upper = new_mode.upper()
        if mode_upper in ["SIMULATION", "HARDWARE"]:
            self.mode = mode_upper
            logger.info(f"Çalışma modu değiştirildi: {self.mode}")
            if self.mode == "HARDWARE":
                self.load.connect()
                self.psu.connect()
                self.load.set_load_state(False)
            else:
                self.load.disconnect()
                self.psu.disconnect()
        return self.mode

    def set_load_state(self, enabled: bool) -> bool:
        """Yük girişini açar (LOAD ON) veya kapatır (LOAD OFF)."""
        if self.mode == "SIMULATION":
            self.sim_load_enabled = enabled
            return True
        res = self.load.set_load_state(enabled)
        logger.info(f"Yük durumu güncellendi: {enabled} (Sonuç: {res})")
        return res

    def set_load_current(self, current: float) -> bool:
        """Hedef yük akımını ayarlar."""
        if self.mode == "SIMULATION":
            self.sim_current = max(0.0, min(30.0, float(current)))
            return True
        res = self.load.set_constant_current(current)
        logger.info(f"Hedef akım güncellendi: {current} A")
        return res

    def tare_load(self) -> float:
        """UTL8511 yükündeki artık akımı sıfırlar (Tare offset)."""
        offset = self.load.tare_offset()
        logger.info(f"Yük akımı sıfırlandı (Tare): ofset = {offset:.4f} A")
        return offset

    def reset_tare(self):
        """Tare ofsetini temizler."""
        self.load.reset_tare()
        logger.info("Yük tare ofseti sıfırlandı.")


    def calibrate_psu(self, psu_setpoint_v: float = 48.0, measured_vin: float = 47.90, measured_iin: float = 0.449, manual_fixed: bool = False):
        """Güç kaynağı gerilimini ve kablo kaybını kalibre eder."""
        if hasattr(self.psu, "calibrate"):
            self.psu.calibrate(psu_setpoint_v, measured_vin, measured_iin, manual_fixed)

    def set_psu_voltage(self, voltage: float) -> Tuple[float, float]:
        """Güç kaynağı gerilimini seçer (örn: 3V, 9V, 18V, 24V, 48V, 72V) ve kalibre değeri döndürür."""
        if self.mode == "SIMULATION":
            self.sim_voltage = float(voltage)
            return self.sim_voltage, 0.0
        if hasattr(self.psu, "set_nominal_voltage"):
            return self.psu.set_nominal_voltage(voltage)
        return voltage, 0.0

    def set_psu_state(self, enabled: bool) -> bool:
        """Güç kaynağı çıkışını açar (OUTP ON) veya kapatır (OUTP OFF)."""
        if self.mode == "SIMULATION":
            self.sim_psu_enabled = enabled
            return True
        res = False
        if hasattr(self.psu, "set_output"):
            res = self.psu.set_output(enabled)
        logger.info(f"[ENGINE] PSU çıkış durumu güncellendi: {enabled} (Sonuç: {res})")
        return res

    def emergency_stop(self) -> dict:
        """
        Akıllı Acil Stop: Hem Güç Kaynağını (PSU) hem de Elektronik Yükü (Load)
        derhal kapatır, akımı 0.0A yapar.
        """
        logger.warning("[ACİL STOP] Sistem tetiklendi! PSU ve Yük kapatılıyor...")
        self.emergency_stop_latched = True
        if self.mode == "SIMULATION":
            self.sim_psu_enabled = False
            self.sim_load_enabled = False
            self.sim_current = 0.0
            return {"emergency_stop": True, "psu_disabled": True,
                    "load_disabled": True, "current_zeroed": True}
        load_res = False
        curr_res = False
        psu_res = False
        try:
            curr_res = self.load.set_constant_current(0.0)
            load_res = self.load.set_load_state(False)
        except Exception as e:
            logger.error(f"[ACİL STOP] Yük kapatma hatası: {e}")

        try:
            if hasattr(self.psu, "set_output"):
                psu_res = self.psu.set_output(False)
        except Exception as e:
            logger.error(f"[ACİL STOP] PSU kapatma hatası: {e}")

        return {
            "emergency_stop": True,
            "psu_disabled": psu_res,
            "load_disabled": load_res,
            "current_zeroed": curr_res
        }

    def clear_emergency_stop(self) -> None:
        """Release the safety latch only when a new test is explicitly started."""
        self.emergency_stop_latched = False

    def configure_ports(self, psu_port: str, utl_port: str):
        """Kullanıcının arayüzden seçtiği COM portlarını günceller."""
        if psu_port and hasattr(self.psu, "port") and psu_port != self.psu.port:
            self.psu.disconnect()
            self.psu.port = psu_port
        if utl_port and hasattr(self.load, "_driver") and utl_port != self.load._driver.port:
            self.load.disconnect()
            self.load._driver.port = utl_port
        if self.mode == "HARDWARE":
            if not self.psu.is_connected:
                self.psu.connect()
            if not self.load.is_connected:
                self.load.connect()

    async def register_client(self, websocket: WebSocket):
        """Yeni bir istemciyi kaydeder ve varsa son veriyi anında iletir."""
        await websocket.accept()
        self.active_websockets.add(websocket)
        if self.last_frame:
            await websocket.send_text(self.last_frame.model_dump_json())

    def unregister_client(self, websocket: WebSocket):
        """Ayrılan istemciyi listeden çıkarır."""
        self.active_websockets.discard(websocket)

    async def broadcast(self, frame: TelemetryFrame):
        """Veri karesini tüm bağlı tarayıcılara JSON formatında gönderir."""
        if not self.active_websockets:
            return

        payload = frame.model_dump()
        payload["active_slot"] = self.active_slot
        payload["test_active"] = self.is_sweep_active
        json_data = json.dumps(payload)
        stale_clients = []
        for ws in self.active_websockets:
            try:
                await ws.send_text(json_data)
            except Exception:
                stale_clients.append(ws)

        for ws in stale_clients:
            self.unregister_client(ws)

    async def start(self):
        """Telemetri arka plan döngüsünü başlatır."""
        self._running = True
        # Serial reconnects happen in the telemetry worker, not during ASGI startup.
        self._task = asyncio.create_task(self._telemetry_loop())

    async def stop(self):
        """Telemetri döngüsünü ve donanım bağlantılarını durdurur."""
        self._running = False
        if self._task:
            self._task.cancel()
        self.load.disconnect()
        self.psu.disconnect()

    def read_simulation(self):
        self.simulator.nominal_vin_per_channel = self.sim_voltage / 3.0
        self.simulator.target_iout = self.sim_current if self.sim_load_enabled and self.sim_psu_enabled else 0.0
        if not self.sim_load_enabled or not self.sim_psu_enabled:
            self.simulator.current_iout = 0.0
        channels, v_out, i_out = self.simulator.step()
        if not self.sim_psu_enabled:
            for channel in channels:
                channel.voltage = channel.current = channel.power = 0.0
            v_out = i_out = 0.0
        elif not self.sim_load_enabled:
            i_out = 0.0
        return channels, sum(c.voltage for c in channels), channels[0].current, sum(c.power for c in channels), v_out, i_out, v_out * i_out

    def acquire_sync_sample(self, apply_calibration: bool = True) -> dict:
        """Sweep sırasında donanımları senkronize ve doğrudan sorgular."""
        is_hw = (self.mode == "HARDWARE")
        current_vin = getattr(self.psu, "nominal_vin", 48.0)
        if is_hw:
            v_out, i_out, p_out = self.load.read_telemetry(True, current_vin)
            channels, total_vin, i_in_series, total_pin = self.psu.read_telemetry(p_out)
        else:
            channels, total_vin, i_in_series, total_pin, v_out, i_out, p_out = self.read_simulation()

        if apply_calibration:
            channels, total_vin, total_pin, v_out, p_out = self.apply_slot_calibration(
                channels, total_vin, i_in_series, v_out, i_out)

        adapted_channels = [
            ChannelTelemetry(
                channel_id=ch.channel_id,
                voltage=ch.voltage,
                current=ch.current,
                power=ch.power,
                sense_ok=ch.sense_ok
            )
            for ch in channels
        ]

        frame = self.math_engine.compute(
            channels=adapted_channels,
            v_out=v_out,
            i_out=i_out,
            mode=self.mode,
            hmp_connected=self.psu.is_connected,
            utl_connected=self.load.is_connected
        )
        self.last_frame = frame
        return {
            "v_in": total_vin,
            "i_in": i_in_series,
            "p_in": total_pin,
            "v_out": v_out,
            "i_out": i_out,
            "p_out": p_out,
            "eff": frame.efficiency,
            "p_loss": frame.p_loss,
            "frame": frame
        }

    async def acquire_and_broadcast(self, apply_calibration: bool = True) -> dict:
        """Publish a test-owned sample while the background reader is paused."""
        sample = await asyncio.to_thread(self.acquire_sync_sample, apply_calibration)
        await self.broadcast(sample["frame"])
        return sample

    async def _telemetry_loop(self):
        """250ms periyotla sürekli veri toplayıp yayınlayan ana asenkron döngü."""
        while self._running:
            if self.is_sweep_active:
                await asyncio.sleep(0.1)
                continue

            try:
                # 1. Çıkış Yükünü Oku (UTL8511 veya Simülasyon)
                is_hw = (self.mode == "HARDWARE")
                current_vin = getattr(self.psu, "nominal_vin", 48.0)
                if is_hw:
                    v_out, i_out, p_out = await asyncio.to_thread(self.load.read_telemetry, True, current_vin)
                    channels, total_vin, i_in_series, total_pin = await asyncio.to_thread(self.psu.read_telemetry, p_out)
                else:
                    channels, total_vin, i_in_series, total_pin, v_out, i_out, p_out = self.read_simulation()

                channels, total_vin, total_pin, v_out, p_out = self.apply_slot_calibration(
                    channels, total_vin, i_in_series, v_out, i_out)

                # ChannelReading -> ChannelTelemetry adaptasyonu
                adapted_channels = [
                    ChannelTelemetry(
                        channel_id=ch.channel_id,
                        voltage=ch.voltage,
                        current=ch.current,
                        power=ch.power,
                        sense_ok=ch.sense_ok
                    )
                    for ch in channels
                ]

                # 3. Güç ve Verimlilik Matematiğini Hesapla
                frame = self.math_engine.compute(
                    channels=adapted_channels,
                    v_out=v_out,
                    i_out=i_out,
                    mode=self.mode,
                    hmp_connected=self.psu.is_connected,
                    utl_connected=self.load.is_connected
                )

                self.last_frame = frame
                await self.broadcast(frame)

            except Exception as e:
                logger.error(f"Telemetri döngü hatası: {e}", exc_info=True)

            await asyncio.sleep(getattr(CONFIG, "SAMPLE_INTERVAL_SEC", 0.25))

MANAGER = TelemetryManager()
