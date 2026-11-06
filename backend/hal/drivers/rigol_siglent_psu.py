"""
Rigol DP800 / Siglent SPD Serisi Programlanabilir Güç Kaynağı Sürücüsü
Yüksek hassasiyetli çok kanallı ve tek kanallı endüstriyel laboratuvar güç kaynakları.
"""
import logging
from typing import List, Tuple, Optional
from ..base_psu import BasePowerSupply, ChannelReading
from ...drivers.base_driver import BaseSerialDriver, parse_float

logger = logging.getLogger("RigolSiglentPSU")

class RigolSiglentPowerSupply(BasePowerSupply):
    def __init__(self, port: str = "COM1", baudrate: int = 9600, channel: int = 1):
        self._driver = BaseSerialDriver(port=port, baudrate=baudrate, timeout=0.5)
        self.channel = channel
        self._output_enabled: bool = True
        self._last_v: float = 0.0
        self._last_i: float = 0.0
        self._last_p: float = 0.0
        self.device_id: str = "Rigol/Siglent PSU"

    def connect(self) -> bool:
        ok = self._driver.connect()
        if ok:
            idn = self._driver.query("*IDN?")
            if idn:
                self.device_id = idn
                logger.info(f"[Rigol/Siglent PSU] Bağlandı: {self.device_id}")
        return ok

    def disconnect(self) -> None:
        self._driver.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._driver.is_connected

    def set_voltage(self, volts: float) -> bool:
        """Kanal gerilimini ayarlar (:VOLT <v> veya :APPL CHx,<v>,<i>)."""
        if not self._driver.is_connected:
            return False
        return self._driver.write(f":SOUR{self.channel}:VOLT {volts:.3f}")

    def set_current_limit(self, amps: float) -> bool:
        """Kanal akım sınırını ayarlar (:CURR <i>)."""
        if not self._driver.is_connected:
            return False
        return self._driver.write(f":SOUR{self.channel}:CURR {amps:.3f}")

    def set_output(self, enabled: bool) -> bool:
        """Kanal çıkışını açar veya kapatır (:OUTP CHx,ON/OFF)."""
        self._output_enabled = enabled
        if not self._driver.is_connected:
            return True
        cmd = f":OUTP CH{self.channel},{'ON' if enabled else 'OFF'}"
        res = self._driver.write(cmd)
        if not res:
            # Alternatif SCPI sözdizimi
            res = self._driver.write(f":OUTP:STAT {'ON' if enabled else 'OFF'}")
        return res

    def read_telemetry(self, simulated_load_power: float = 0.0) -> Tuple[List[ChannelReading], float, float, float]:
        """Kanal gerilim, akım ve gücünü okur."""
        if not self._driver.is_connected:
            self._driver.connect()

        if self._driver.is_connected:
            # Rigol DP800 :MEAS:ALL? CH1 -> "voltage,current,power"
            all_str = self._driver.query(f":MEAS:ALL? CH{self.channel}")
            if all_str and "," in all_str:
                parts = all_str.split(",")
                v_val = parse_float(parts[0]) if len(parts) > 0 else None
                i_val = parse_float(parts[1]) if len(parts) > 1 else None
                p_val = parse_float(parts[2]) if len(parts) > 2 else None
            else:
                v_str = self._driver.query(f":MEAS:VOLT? CH{self.channel}") or self._driver.query("MEAS:VOLT?")
                i_str = self._driver.query(f":MEAS:CURR? CH{self.channel}") or self._driver.query("MEAS:CURR?")
                p_str = self._driver.query(f":MEAS:POW? CH{self.channel}") or self._driver.query("MEAS:POW?")
                v_val = parse_float(v_str)
                i_val = parse_float(i_str)
                p_val = parse_float(p_str)

            if v_val is not None and i_val is not None:
                p_calc = p_val if p_val is not None else (v_val * i_val)
                self._last_v = v_val
                self._last_i = i_val
                self._last_p = p_calc
                ch = ChannelReading(
                    channel_id=self.channel,
                    voltage=round(v_val, 4),
                    current=round(i_val, 4),
                    power=round(p_calc, 4),
                    sense_ok=True
                )
                return [ch], round(v_val, 3), round(i_val, 3), round(p_calc, 3)

        return [ChannelReading(channel_id=self.channel, voltage=0.0, current=0.0, power=0.0, sense_ok=False)], 0.0, 0.0, 0.0
