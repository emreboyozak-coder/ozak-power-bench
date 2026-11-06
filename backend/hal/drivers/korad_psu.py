"""
Korad KA3005P / Tenma / Velleman Programlanabilir Güç Kaynağı Sürücüsü
Laboratuvarlarda en yaygın kullanılan bütçe dostu RS232/USB DC güç kaynağı protokolü.
"""
import logging
from typing import List, Tuple, Optional
from ..base_psu import BasePowerSupply, ChannelReading
from ...drivers.base_driver import BaseSerialDriver, parse_float

logger = logging.getLogger("KoradPowerSupply")

class KoradPowerSupply(BasePowerSupply):
    def __init__(self, port: str = "COM1", baudrate: int = 9600, channel: int = 1):
        self._driver = BaseSerialDriver(port=port, baudrate=baudrate, timeout=0.5)
        self.channel = channel
        self._output_enabled: bool = False
        self._last_v: float = 0.0
        self._last_i: float = 0.0
        self.device_id: str = "Korad KA3005P"

    def connect(self) -> bool:
        ok = self._driver.connect()
        if ok:
            idn = self._driver.query("*IDN?")
            if idn:
                self.device_id = idn
                logger.info(f"[Korad PSU] Bağlandı: {self.device_id}")
        return ok

    def disconnect(self) -> None:
        self._driver.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._driver.is_connected

    def set_voltage(self, volts: float) -> bool:
        """Gerilimi ayarlar (VSET<ch>:<val>)."""
        if not self._driver.is_connected:
            return False
        return self._driver.write(f"VSET{self.channel}:{volts:.2f}")

    def set_current_limit(self, amps: float) -> bool:
        """Akımı ayarlar (ISET<ch>:<val>)."""
        if not self._driver.is_connected:
            return False
        return self._driver.write(f"ISET{self.channel}:{amps:.3f}")

    def set_output(self, enabled: bool) -> bool:
        """Çıkışı açar/kapatır (OUT1 / OUT0)."""
        self._output_enabled = enabled
        if not self._driver.is_connected:
            return True
        cmd = f"OUT{1 if enabled else 0}"
        return self._driver.write(cmd)

    def read_telemetry(self, simulated_load_power: float = 0.0) -> Tuple[List[ChannelReading], float, float, float]:
        """Gerilim ve akımı sorgular (VOUT<ch>?, IOUT<ch>?)."""
        if not self._driver.is_connected:
            self._driver.connect()

        if self._driver.is_connected:
            v_str = self._driver.query(f"VOUT{self.channel}?")
            i_str = self._driver.query(f"IOUT{self.channel}?")

            v_val = parse_float(v_str)
            i_val = parse_float(i_str)

            if v_val is not None and i_val is not None:
                p_val = v_val * i_val
                self._last_v = v_val
                self._last_i = i_val
                ch = ChannelReading(
                    channel_id=self.channel,
                    voltage=round(v_val, 4),
                    current=round(i_val, 4),
                    power=round(p_val, 4),
                    sense_ok=True
                )
                return [ch], round(v_val, 3), round(i_val, 3), round(p_val, 3)

        return [ChannelReading(channel_id=self.channel, voltage=0.0, current=0.0, power=0.0, sense_ok=False)], 0.0, 0.0, 0.0
