"""
Standart SCPI Programlanabilir Güç Kaynağı Sürücüsü
Keysight, GW Instek, EA Elektro-Automatik, BK Precision ve standart SCPI komut setine sahip tüm RS232/USB kaynakları destekler.
"""
import logging
from typing import List, Tuple, Optional
from ..base_psu import BasePowerSupply, ChannelReading
from ...drivers.base_driver import BaseSerialDriver, parse_float

logger = logging.getLogger("SCPIPowerSupply")

class SCPIPowerSupply(BasePowerSupply):
    def __init__(self, port: str = "COM1", baudrate: int = 9600, nominal_vin: float = 48.0):
        self._driver = BaseSerialDriver(port=port, baudrate=baudrate, timeout=0.5)
        self.nominal_vin = nominal_vin
        self._output_enabled: bool = True
        self._last_v: float = 0.0
        self._last_i: float = 0.0
        self._last_p: float = 0.0
        self.device_id: str = "Generic SCPI PSU"

    def connect(self) -> bool:
        ok = self._driver.connect()
        if ok:
            idn = self._driver.query("*IDN?")
            if idn:
                self.device_id = idn
                logger.info(f"[SCPI PSU] Bağlandı: {self.device_id}")
        return ok

    def disconnect(self) -> None:
        self._driver.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._driver.is_connected

    def set_voltage(self, volts: float, channel: Optional[int] = None) -> bool:
        """Gerilim ayarlar (:VOLT <v> veya :SOUR:VOLT <v>)."""
        if not self._driver.is_connected:
            return False
        if channel:
            return self._driver.write(f":INST:NSEL {channel}; :VOLT {volts:.3f}")
        return self._driver.write(f":VOLT {volts:.3f}")

    def set_current_limit(self, amps: float, channel: Optional[int] = None) -> bool:
        """Akım sınırını ayarlar (:CURR <i>)."""
        if not self._driver.is_connected:
            return False
        if channel:
            return self._driver.write(f":INST:NSEL {channel}; :CURR {amps:.3f}")
        return self._driver.write(f":CURR {amps:.3f}")

    def set_output(self, enabled: bool) -> bool:
        """Çıkışı açar veya kapatır (:OUTP ON/OFF)."""
        self._output_enabled = enabled
        if not self._driver.is_connected:
            return True
        cmd = ":OUTP ON" if enabled else ":OUTP OFF"
        return self._driver.write(cmd)

    def read_telemetry(self, simulated_load_power: float = 0.0) -> Tuple[List[ChannelReading], float, float, float]:
        """
        Giriş gerilimi ve akımını donanımdan okur.
        Dönüş: (kanallar, toplam_vin, seri_iin, toplam_pin)
        """
        if not self._driver.is_connected:
            self._driver.connect()

        if self._driver.is_connected:
            v_str = self._driver.query("MEAS:VOLT?") or self._driver.query(":VOLT?")
            i_str = self._driver.query("MEAS:CURR?") or self._driver.query(":CURR?")
            p_str = self._driver.query("MEAS:POW?")

            v_val = parse_float(v_str)
            i_val = parse_float(i_str)
            p_val = parse_float(p_str)

            if v_val is not None and i_val is not None:
                p_calc = p_val if p_val is not None else (v_val * i_val)
                self._last_v = v_val
                self._last_i = i_val
                self._last_p = p_calc
                
                ch = ChannelReading(
                    channel_id=1,
                    voltage=round(v_val, 4),
                    current=round(i_val, 4),
                    power=round(p_calc, 4),
                    sense_ok=True
                )
                return [ch], round(v_val, 3), round(i_val, 3), round(p_calc, 3)

        # Cihaz bağlı değilse güvenli 0.0
        return [ChannelReading(channel_id=1, voltage=0.0, current=0.0, power=0.0, sense_ok=False)], 0.0, 0.0, 0.0
