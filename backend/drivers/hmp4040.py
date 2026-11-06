"""
Rohde & Schwarz HMP4040 Programlanabilir Güç Kaynağı Sürücüsü (SCPI)
USB Virtual COM port üzerinden Ch1, Ch2, Ch3 seri gerilim ve akım ölçümlerini okur.
"""
from typing import List, Optional
import logging
from .base_driver import BaseSerialDriver, parse_float
from ..math_engine import ChannelTelemetry

logger = logging.getLogger("HMP4040Driver")

class HMP4040Driver(BaseSerialDriver):
    def __init__(self, port: str = "COM3", baudrate: int = 9600, series_channels: List[int] = [1, 2, 3]):
        super().__init__(port=port, baudrate=baudrate, timeout=0.3)
        self.series_channels = series_channels
        self.last_measurements = {ch: (16.0, 0.0) for ch in self.series_channels}

    def identify(self) -> Optional[str]:
        """Cihaz kimliğini doğrular (*IDN?)."""
        return self.query("*IDN?")

    def read_channel(self, channel_id: int) -> Optional[tuple[float, float]]:
        """
        Belirtilen kanalın anlık gerilim ve akımını okur.
        Dönüş: (voltage, current)
        """
        # Kanalı seç: INST:NSEL <channel_id>
        if not self.write(f"INST:NSEL {channel_id}"):
            return None
        
        # Gerilim ölçümü
        volt_str = self.query("MEAS:VOLT?")
        v = parse_float(volt_str)
        if v is None:
            return None
        
        # Akım ölçümü
        curr_str = self.query("MEAS:CURR?")
        i = parse_float(curr_str)
        if i is None:
            return None

        self.last_measurements[channel_id] = (v, i)
        return (v, i)

    def read_all_series_channels(self) -> List[ChannelTelemetry]:
        """
        Seri bağlı Ch1, Ch2, Ch3 kanallarını sırayla okur.
        """
        results = []
        if not self.is_connected:
            self.connect()

        for ch in self.series_channels:
            reading = self.read_channel(ch) if self.is_connected else None
            if reading:
                v, i = reading
                results.append(
                    ChannelTelemetry(
                        channel_id=ch,
                        voltage=v,
                        current=i,
                        power=v * i,
                        sense_ok=True
                    )
                )
            else:
                last_v, last_i = self.last_measurements.get(ch, (0.0, 0.0))
                results.append(
                    ChannelTelemetry(
                        channel_id=ch,
                        voltage=last_v,
                        current=last_i,
                        power=last_v * last_i,
                        sense_ok=False
                    )
                )

        return results
