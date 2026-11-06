"""Persistent per-slot voltage-drop calibration profiles."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

PROFILE_PATH = Path(__file__).with_name("slot_calibrations.json")


def _empty_profile() -> Dict[str, Any]:
    return {
        "input_drop_offset_v": 0.0,
        "input_resistance_ohm": 0.0,
        "output_gain_offset_v": 0.0,
        "output_resistance_ohm": 0.0,
        "calibrated_at": None,
        "points": [],
    }


def load_profiles() -> Dict[str, Dict[str, Any]]:
    profiles = {str(slot): _empty_profile() for slot in range(1, 6)}
    try:
        saved = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        for slot in profiles:
            if isinstance(saved.get(slot), dict):
                profiles[slot].update(saved[slot])
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return profiles


def save_profiles(profiles: Dict[str, Dict[str, Any]]) -> None:
    temporary_path = PROFILE_PATH.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(profiles, indent=2), encoding="utf-8")
    temporary_path.replace(PROFILE_PATH)


def _fit_drop(points: List[Dict[str, float]], current_key: str, delta_key: str) -> tuple[float, float]:
    first, second = points
    current_delta = second[current_key] - first[current_key]
    if abs(current_delta) < 0.01:
        raise ValueError(f"İki kalibrasyon noktasının {current_key} değerleri en az 0.01 A farklı olmalı.")
    resistance = (second[delta_key] - first[delta_key]) / current_delta
    offset = first[delta_key] - resistance * first[current_key]
    if resistance < -0.02 or resistance > 1.0:
        raise ValueError("Hesaplanan kablo/PCB direnci geçersiz. Akım ve multimetre ölçümlerini kontrol edin.")
    if abs(offset) > 2.0:
        raise ValueError("Hesaplanan gerilim ofseti 2 V sınırını aşıyor; ölçümleri kontrol edin.")
    return max(0.0, resistance), offset


def build_profile(points: List[Dict[str, float]]) -> Dict[str, Any]:
    if len(points) != 2:
        raise ValueError("Her yuva için iki farklı yük noktasında ölçüm gerekli.")
    normalized = []
    for point in points:
        clean = {key: float(value) for key, value in point.items()}
        if min(clean.values()) < 0:
            raise ValueError("Ölçüm değerleri negatif olamaz.")
        normalized.append(clean)

    for point in normalized:
        if point["vin_source_v"] <= 0 or point["vin_dut_v"] <= 0:
            raise ValueError("Giriş gerilimi ölçümleri sıfırdan büyük olmalı.")
        if point["vout_load_v"] <= 0 or point["vout_dut_v"] <= 0:
            raise ValueError("Çıkış gerilimi ölçümleri sıfırdan büyük olmalı.")
        if point["iin_a"] <= 0 or point["iout_a"] <= 0:
            raise ValueError("Kalibrasyon sırasında giriş ve çıkış akımı ölçülmeli.")

    # PSU terminal voltage is above DUT input; load-terminal voltage is below DUT output.
    for point in normalized:
        point["vin_drop_v"] = point["vin_source_v"] - point["vin_dut_v"]
        point["vout_gain_v"] = point["vout_dut_v"] - point["vout_load_v"]

    vin_resistance, vin_offset = _fit_drop(normalized, "iin_a", "vin_drop_v")
    vout_resistance, vout_offset = _fit_drop(normalized, "iout_a", "vout_gain_v")
    return {
        "input_drop_offset_v": round(vin_offset, 6),
        "input_resistance_ohm": round(vin_resistance, 6),
        "output_gain_offset_v": round(vout_offset, 6),
        "output_resistance_ohm": round(vout_resistance, 6),
        "calibrated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "points": normalized,
    }
