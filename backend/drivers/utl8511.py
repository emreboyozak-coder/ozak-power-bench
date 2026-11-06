"""
UNI-T UTL8511 DC Elektronik Yük Sürücüsü (SCPI)
Arka panel RS-232 portu üzerinden 4-Wire Remote Sense gerilim ve akım ölçümlerini okur.
"""
from typing import Optional, Tuple
import logging
from .base_driver import BaseSerialDriver, parse_float

logger = logging.getLogger("UTL8511Driver")

class UTL8511Driver(BaseSerialDriver):
    def __init__(self, port: str = "COM4", baudrate: int = 9600):
        super().__init__(port=port, baudrate=baudrate, timeout=0.3)
        self.last_voltage: float = 5.0
        self.last_current: float = 0.0

    def identify(self) -> Optional[str]:
        """Cihaz kimliğini doğrular (*IDN?)."""
        return self.query("*IDN?")

    def read_telemetry(self) -> Optional[Tuple[float, float, float]]:
        """
        Elektronik yükün anlık gerilim, akım ve güç değerlerini sorgular.
        Dönüş: (v_out, i_out, p_out)
        """
        if not self.is_connected:
            self.connect()

        if not self.is_connected:
            return None

        # 1. Gerilim Sorgusu: MEAS:VOLT?
        v_str = self.query("MEAS:VOLT?")
        v_out = parse_float(v_str)
        if v_out is None:
            # Yedek SCPI komut denemesi: VOLT?
            v_str = self.query("VOLT?")
            v_out = parse_float(v_str)

        # 2. Akım Sorgusu: MEAS:CURR?
        i_str = self.query("MEAS:CURR?")
        i_out = parse_float(i_str)
        if i_out is None:
            # Yedek SCPI komut denemesi: CURR?
            i_str = self.query("CURR?")
            i_out = parse_float(i_str)

        if v_out is None or i_out is None:
            return None

        p_out = v_out * i_out
        self.last_voltage = v_out
        self.last_current = i_out
        return (v_out, i_out, p_out)
