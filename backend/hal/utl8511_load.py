"""
UNI-T UTL8511 DC Elektronik Yük HAL Sürücüsü
RS-232 portu üzerinden SCPI komutlarıyla çift yönlü yük kontrolü ve 4-wire sense okuması yapar.
"""
import logging
import math
import random
import time
from typing import Tuple
from .base_load import BaseLoad
from ..drivers.base_driver import BaseSerialDriver, parse_float

logger = logging.getLogger("UTL8511HAL")

class UTL8511Load(BaseLoad):
    def __init__(self, port: str = "COM3", baudrate: int = 9600):
        self._driver = BaseSerialDriver(port=port, baudrate=baudrate, timeout=0.4)
        self._load_enabled: bool = False
        self._target_current: float = 2.0
        self._last_v: float = 5.002
        self._last_i: float = 2.0
        self._last_p: float = 10.0
        self._raw_v: float = 0.0
        self._raw_i: float = 0.0
        self.i_tare_offset: float = 0.0

    def connect(self) -> bool:
        ok = self._driver.connect()
        if ok:
            self._driver.write(":SYST:REM")
            self._driver.write("SYST:REM")
            self._driver.write(":FUNC CURR")
            self._driver.write(":MODE CC")
            self.set_remote_sense(False)
            input_status = self._driver.query(":INP?")
            normalized_status = input_status.strip().upper() if input_status else ""
            if normalized_status not in {"0", "1", "ON", "OFF"}:
                logger.warning("Port %s did not identify as a UTL8511 electronic load.", self._driver.port)
                self._driver.disconnect()
                self._load_enabled = False
                return False
            self._load_enabled = normalized_status in {"1", "ON"}
        return ok

    def set_remote_sense(self, enabled: bool) -> bool:
        """Select local front-terminal sensing or rear-terminal remote compensation."""
        if not self._driver.is_connected:
            return False
        state = "ON" if enabled else "OFF"
        if not self._driver.write(f":SYST:SENS {state}"):
            return False
        time.sleep(0.05)
        response = self._driver.query(":SYST:SENS?")
        expected = {"1", "ON"} if enabled else {"0", "OFF"}
        ok = response is not None and response.strip().upper() in expected
        logger.info("[UTL8511] Remote sense %s (readback=%s)", "enabled" if enabled else "disabled", response)
        return ok

    def enable_remote_sense(self) -> bool:
        """UTL8511 4-Wire Remote Sense modunu garanti altına alır."""
        if not self._driver.is_connected:
            return False
        self._driver.write(":SYST:REM")
        self._driver.write(":SYST:SENS ON")
        self._driver.write(":SENS ON")
        self._driver.write("SYST:SENS 1")
        logger.info("[UTL8511] 4-Wire Remote Sense (:SYST:SENS ON) komutu iletildi.")
        return True

    def tare_offset(self) -> float:
        """Boşta kalan artık akımı (mA) sıfırlar (Maksimum 60mA artık ile sınırlı)."""
        if self._driver.is_connected:
            i_str = self._driver.query(":MEAS:CURR?") or self._driver.query("MEAS:CURR?")
            val = parse_float(i_str)
            if val is not None:
                self._raw_i = val
        if 0.0 < self._raw_i <= 0.060:
            self.i_tare_offset = self._raw_i
        else:
            self.i_tare_offset = 0.0
        logger.info(f"[UTL8511] Akım sıfırlandı (Tare). Ofset: {self.i_tare_offset:.4f} A")
        return self.i_tare_offset

    def reset_tare(self):
        self.i_tare_offset = 0.0

    def disconnect(self) -> None:
        self._driver.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._driver.is_connected

    def set_load_state(self, enabled: bool) -> bool:
        self._load_enabled = enabled
        if self._driver.is_connected:
            cmd = ":INP 1" if enabled else ":INP 0"
            success = self._driver.write(cmd)
            logger.info(f"[UTL8511] Yük durumu gönderildi: {cmd}")
            return success
        return True

    @property
    def load_enabled(self) -> bool:
        return self._load_enabled

    def set_constant_current(self, amps: float) -> bool:
        clamped = max(0.0, min(30.0, float(amps)))
        self._target_current = clamped
        if self._driver.is_connected:
            success = self._driver.write(f":CURR {clamped:.3f}")
            return success
        return True

    @property
    def target_current(self) -> float:
        return self._target_current

    def verify_settings(self, amps: float, enabled: bool) -> dict:
        """Verify device setpoints, independently of measured output current."""
        if not self._driver.is_connected:
            raise RuntimeError("Electronic load disconnected before settings verification.")
        current = parse_float(self._driver.query(":CURR?"))
        state_response = self._driver.query(":INP?")
        state = state_response.strip().upper() if state_response else ""
        # Compare at the precision used by :CURR writes (three decimals).
        if current is None or not math.isfinite(current) or abs(current - amps) > 0.0005:
            raise RuntimeError(
                f"Electronic load current setting not confirmed: expected {amps:.3f} A, read {current!r}.")
        expected_states = {"1", "ON"} if enabled else {"0", "OFF"}
        if state not in expected_states:
            raise RuntimeError(
                f"Electronic load input state not confirmed: expected {'ON' if enabled else 'OFF'}, read {state_response!r}.")
        return {"verified": True, "current_setting_a": current, "input_enabled": enabled}

    def read_telemetry(self, is_hardware_mode: bool = False, vin: float = 48.0) -> Tuple[float, float, float]:
        """
        Cihaz bağlıysa RS-232 SCPI ile okur.
        SCPI bağlantısı kesilirse veya dönüştürücü aktifken (Vin >= 12V) fiziksel regülasyon modelini çalıştırır.
        Vin < 12V ise dönüştürücü kapalıdır (0.0V döner).
        """
        if not self._driver.is_connected:
            self._driver.connect()

        if self._driver.is_connected:
            v_str = self._driver.query(":MEAS:VOLT?") or self._driver.query("MEAS:VOLT?")
            i_str = self._driver.query(":MEAS:CURR?") or self._driver.query("MEAS:CURR?")
            p_str = self._driver.query(":MEAS:POW?") or self._driver.query("MEAS:POW?")

            v_val = parse_float(v_str)
            i_val = parse_float(i_str)
            p_val = parse_float(p_str)

            if v_val is not None and i_val is not None:
                self._raw_v = v_val
                self._raw_i = i_val
                # Tare / Zero ofsetini uygula (Sadece minör mA ofsetleri için)
                if self.i_tare_offset > 0.060:
                    self.i_tare_offset = 0.0
                clean_i = max(0.0, i_val - self.i_tare_offset)
                p_calc = (v_val * clean_i) if p_val is None else p_val
                self._last_v = v_val
                self._last_i = clean_i
                self._last_p = p_calc
                return round(v_val, 3), round(clean_i, 3), round(p_calc, 3)

        if is_hardware_mode:
            logger.error("UTL8511 measurement failed on %s; refusing to substitute simulated readings.", self._driver.port)
            self._last_v = self._last_i = self._last_p = 0.0
            raise RuntimeError(f"UTL8511 measurement unavailable on {self._driver.port}; no simulated values used.")

        # Giriş gerilimi kontrolü: Eğer güç kaynağı kapalıysa veya Vin < 12V ise dönüştürücü çalışmaz
        if vin < 12.0:
            self._last_v = 0.0
            self._last_i = 0.0
            self._last_p = 0.0
            return 0.0, 0.0, 0.0

        # Güç kaynağı aktif (Vin >= 12V: 18V, 48V, 72V): Ozak Power OZP50S48SS05A regüle 5VDC üretir
        if not self._load_enabled or self._target_current <= 0.05:
            # Boşta (No Load) çıkış: 5.015V - 5.025V arası kararlı regülasyon
            jitter = (random.random() - 0.5) * 0.003
            v_out = 5.020 + jitter
            i_out = 0.000
            p_out = 0.000
        else:
            # Yük altında (On Load): Hedef akım çekilir, Kelvin uçlarında minör hat empedansı düşümü
            jitter_i = (random.random() - 0.5) * 0.006
            i_out = max(0.0, self._target_current + jitter_i)
            jitter_v = (random.random() - 0.5) * 0.002
            v_out = max(0.0, 5.012 - (i_out * 0.0035) + jitter_v)
            p_out = v_out * i_out

        self._last_v = v_out
        self._last_i = i_out
        self._last_p = p_out
        return round(v_out, 3), round(i_out, 3), round(p_out, 3)
