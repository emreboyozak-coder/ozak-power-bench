"""
Gerçekçi DC-DC 48V -> 5V Buck/Boost Simülatörü
Fuar standında cihazlar bağlı değilken veya kapalıyken gerçeğe birebir uygun telemetri üretir.
"""
import random
import math
from typing import List, Tuple
from .math_engine import ChannelTelemetry

class ConverterSimulator:
    def __init__(self):
        # Hedeflenen Çıkış Akımı (A)
        self.target_iout: float = 17.40
        self.current_iout: float = 17.40
        
        # Nominal Gerilimler
        self.nominal_vout: float = 5.002
        self.nominal_vin_per_channel: float = 16.000 # 3 kanal x 16V = 48V

        # Fiziksel Kayıp Parametreleri (Gerçekçi Buck Modeli)
        self.r_conduction: float = 0.0112   # 11.2 mOhm eşdeğer MOSFET + İndüktör DCR direnci
        self.p_fixed_losses: float = 0.82   # Kontrolcü, Gate-Drive ve Çekirdek Kaybı (W)

        # Simülasyon Dalgalanma Durumu
        self.tick: int = 0
        self.oscillation_enabled: bool = True

    def set_load_current(self, target_amps: float):
        """Kullanıcının arayüzden yük akımını değiştirmesini sağlar (1A - 30A)."""
        self.target_iout = max(0.1, min(30.0, float(target_amps)))

    def step(self) -> Tuple[List[ChannelTelemetry], float, float]:
        """
        Tek bir telemetri adımı üretir (250ms periyot için optimize).
        Dönüş: (kanallar_listesi, v_out, i_out)
        """
        self.tick += 1

        # 1. Yük Akımının Dinamik Takibi & Gerçekçi Jitter/Gürültü
        if self.oscillation_enabled:
            # Akımın hedefe doğru yumuşak yaklaşımı + doğal analog gürültü
            alpha = 0.20
            jitter = (random.random() - 0.5) * 0.08
            self.current_iout += (self.target_iout - self.current_iout) * alpha + jitter * 0.02
        else:
            self.current_iout = self.target_iout

        # Çıkış akımını pozitif tut
        i_out = max(0.0, self.current_iout)

        # 2. Çıkış Gerilimi (4-Wire Remote Sense regülasyonu)
        # Yük arttıkça PCB hat empedansından dolayı mikro mV düşüşü modellemesi
        v_drop_sim = (i_out * 0.0003) # Çok düşük hat direnci
        v_noise = (random.random() - 0.5) * 0.003
        v_out = max(0.0, self.nominal_vout - v_drop_sim + v_noise)

        # 3. Çıkış Gücü
        p_out = v_out * i_out

        # 4. Gerçekçi 48V -> 5V Buck Kayıp Modeli (Laboratuvar Standartları):
        # - Sabit kontrolcü/gate-drive kaybı: 0.85W
        # - Tepe verim: ~%87.5 (2.5A - 4.0A aralığında)
        # - Ağır yük kaybı (I^2 * R): 8A - 10A'de %84 - %85 bandı
        if i_out > 0.05:
            p_fixed = 0.85
            p_switching = 0.18 * i_out
            p_conduction = 0.075 * (i_out ** 2)
            p_thermal_loss = p_fixed + p_switching + p_conduction + ((random.random() - 0.5) * 0.03)
        else:
            p_thermal_loss = 0.85 + ((random.random() - 0.5) * 0.02)
        p_thermal_loss = max(0.1, p_thermal_loss)

        # 5. Giriş Gücü ve Giriş Akımı
        p_in = p_out + p_thermal_loss

        # 6. R&S HMP4040 3 Seri Kanal Dağılımı (16V + 16V + 16V = ~48V)
        # Her kanala 1/3 güç ve seri koldan geçen akım
        channels = []
        total_v_in = 0.0
        channel_voltages = []

        for ch_idx in [1, 2, 3]:
            # Kanallar arası hafif kalibrasyon farkı ve ADC gürültüsü (+- 10mV)
            ch_noise = (random.random() - 0.5) * 0.015
            v_ch = self.nominal_vin_per_channel + ch_noise
            channel_voltages.append(v_ch)
            total_v_in += v_ch

        # Seri koldan geçen giriş akımı: I_in = P_in / V_in_toplam
        i_in_series = p_in / total_v_in if total_v_in > 0 else 0.0

        for ch_idx, v_ch in enumerate(channel_voltages, start=1):
            # Seri kanalların akım okumalarında mikro ADC gürültüsü (+- 2mA)
            ch_curr_noise = (random.random() - 0.5) * 0.004
            i_ch = max(0.0, i_in_series + ch_curr_noise)
            channels.append(
                ChannelTelemetry(
                    channel_id=ch_idx,
                    voltage=v_ch,
                    current=i_ch,
                    power=v_ch * i_ch,
                    sense_ok=True
                )
            )

        return channels, v_out, i_out
