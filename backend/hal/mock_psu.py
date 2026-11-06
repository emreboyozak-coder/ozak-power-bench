"""
Gerçekçi Mock Güç Kaynağı Simülatörü (48V Nominal)
Yeni RS232 güç kaynağı kargodayken 3x16V seri veya tek 48V giriş davranışını simüle eder.
"""
import random
from typing import List, Tuple
from .base_psu import BasePowerSupply, ChannelReading

class MockPowerSupply(BasePowerSupply):
    def __init__(self, nominal_vin: float = 48.0, num_series_channels: int = 3):
        self.nominal_vin: float = nominal_vin
        self.num_channels: int = num_series_channels
        self._connected: bool = True
        self._output_enabled: bool = True
        
        # UNI-T UDP6731 4-Wire Sense & SCPI doğrudan okuma modeli (0.00V düşüm)
        self.cal_matrix = {
            18.0: {"v_meas": 18.00, "drop": 0.00},
            48.0: {"v_meas": 48.00, "drop": 0.00},
            72.0: {"v_meas": 72.00, "drop": 0.00}
        }
        self.manual_fixed: bool = False
        self.manual_vin: float = 48.00
        self.manual_iin: float = 0.460

    def get_calibrated_vin(self, v_setpoint: float) -> Tuple[float, float]:
        """Birebir kaynak gerilimi (Düşüm = 0.0V)."""
        return round(float(v_setpoint), 3), 0.0

    def calibrate(self, psu_setpoint_v: float = 48.0, measured_vin: float = 47.90, measured_iin: float = 0.460, manual_fixed: bool = False):
        """Kullanıcının özel gerilim kalibrasyonunu günceller."""
        self.nominal_vin = psu_setpoint_v
        self.manual_fixed = manual_fixed
        self.manual_vin = measured_vin
        self.manual_iin = measured_iin
        drop = max(0.0, psu_setpoint_v - measured_vin)
        self.cal_matrix[psu_setpoint_v] = {"v_meas": measured_vin, "drop": drop}

    def set_nominal_voltage(self, voltage: float) -> Tuple[float, float]:
        """Test gerilim noktasını (18V, 48V, 72V veya özel) ayarlar."""
        self.nominal_vin = max(12.0, min(80.0, float(voltage)))
        self.manual_fixed = False
        return self.get_calibrated_vin(self.nominal_vin)

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def set_output(self, enabled: bool) -> bool:
        self._output_enabled = enabled
        return True

    def read_telemetry(self, simulated_load_power: float = 0.0) -> Tuple[List[ChannelReading], float, float, float]:
        """
        Kalibre edilmiş 3 noktalı laboratuvar matrisine göre giriş telemetrisini döndürür.
        """
        if not self._output_enabled:
            channels = [
                ChannelReading(channel_id=i, voltage=0.0, current=0.0, power=0.0, sense_ok=True)
                for i in range(1, self.num_channels + 1)
            ]
            return channels, 0.0, 0.0, 0.0

        if self.manual_fixed:
            total_v_in = self.manual_vin + ((random.random() - 0.5) * 0.01)
            i_in_series = self.manual_iin + ((random.random() - 0.5) * 0.002)
            total_p_in = total_v_in * i_in_series
        else:
            # 3 Noktalı kalibre edilmiş kart giriş gerilimi
            v_dut_base, v_drop = self.get_calibrated_vin(self.nominal_vin)

            # Dinamik Kayıp Hesabı (Dönüştürücü Gücü)
            if simulated_load_power > 0.05:
                i_load = simulated_load_power / 5.0
                # Giriş gerilimine göre verimlilik karakteristiği
                p_fixed = 0.85
                p_switching = (0.13 + (self.nominal_vin / 72.0) * 0.05) * i_load
                p_conduction = 0.067 * (i_load ** 2)
                p_loss = p_fixed + p_switching + p_conduction + ((random.random() - 0.5) * 0.02)
                total_p_in = max(0.85, simulated_load_power + p_loss)
            else:
                total_p_in = 0.55 + ((random.random() - 0.5) * 0.01)

            total_v_in = v_dut_base + ((random.random() - 0.5) * 0.004)
            i_in_series = total_p_in / total_v_in if total_v_in > 0 else 0.0

        channels: List[ChannelReading] = []
        for ch_id in range(1, self.num_channels + 1):
            ch_v = (total_v_in / self.num_channels) + ((random.random() - 0.5) * 0.003)
            ch_i = max(0.0, i_in_series + ((random.random() - 0.5) * 0.001))
            ch_p = ch_v * ch_i
            channels.append(
                ChannelReading(
                    channel_id=ch_id,
                    voltage=round(ch_v, 4),
                    current=round(ch_i, 4),
                    power=round(ch_p, 4),
                    sense_ok=True
                )
            )

        return channels, round(total_v_in, 3), round(i_in_series, 3), round(total_p_in, 3)