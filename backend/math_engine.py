"""
DC-DC Buck/Boost Güç & Verimlilik Matematik Motoru
"""
from typing import List, Optional
from pydantic import BaseModel, Field
import time

class ChannelTelemetry(BaseModel):
    channel_id: int
    voltage: float = 0.0   # Volt
    current: float = 0.0   # Amper
    power: float = 0.0     # Watt
    sense_ok: bool = True

class InputTelemetry(BaseModel):
    v_total: float = 0.0        # Toplam Giriş Gerilimi (V_ch1 + V_ch2 + V_ch3)
    i_series: float = 0.0       # Seri Hat Akımı (A)
    p_total: float = 0.0        # Toplam Giriş Gücü (W)
    channels: List[ChannelTelemetry] = []

class OutputTelemetry(BaseModel):
    v_out: float = 0.0          # Çıkış Gerilimi (4-Wire Remote Sense) (V)
    i_out: float = 0.0          # Çıkış Akımı (A)
    p_out: float = 0.0          # Çıkış Gücü (W)
    mode: str = "CC"            # Sabit Akım Modu
    remote_sense: bool = True

class TelemetryFrame(BaseModel):
    timestamp: float = Field(default_factory=time.time)
    mode: str = "SIMULATION"    # "SIMULATION" veya "HARDWARE"
    
    # Donanım Bağlantı Durumları
    hmp_connected: bool = False
    utl_connected: bool = False

    # Güç Verileri
    input: InputTelemetry = Field(default_factory=InputTelemetry)
    output: OutputTelemetry = Field(default_factory=OutputTelemetry)
    
    # Hesaplanan Matematiksel Değerler
    efficiency: float = 0.0      # η (%) = (P_out / P_in) * 100
    peak_efficiency: float = 0.0 # Maksimum ulaşılan verimlilik
    p_loss: float = 0.0          # P_loss (W) = P_in - P_out (Termal Kayıp)
    thermal_status: str = "SAFE" # "SAFE", "WARM", "HIGH"

class MathEngine:
    def __init__(self):
        self.peak_efficiency: float = 0.0

    def reset_peak(self):
        self.peak_efficiency = 0.0

    def compute(
        self,
        channels: List[ChannelTelemetry],
        v_out: float,
        i_out: float,
        mode: str = "SIMULATION",
        hmp_connected: bool = False,
        utl_connected: bool = False
    ) -> TelemetryFrame:
        """
        Giriş kanalları ve çıkış yükü ölçümlerinden telemetri karesini ve güç matematiğini hesaplar.
        """
        # 1. Giriş Kanal Hesaplamaları (Seri Bağlantı)
        v_total = 0.0
        p_total = 0.0
        currents = []

        processed_channels: List[ChannelTelemetry] = []
        for ch in channels:
            ch_power = ch.voltage * ch.current
            processed_channels.append(
                ChannelTelemetry(
                    channel_id=ch.channel_id,
                    voltage=round(ch.voltage, 4),
                    current=round(ch.current, 4),
                    power=round(ch_power, 4),
                    sense_ok=ch.sense_ok
                )
            )
            v_total += ch.voltage
            p_total += ch_power
            currents.append(ch.current)

        # Seri bağlı kollarda akım: Ortalama akım veya güç/gerilim
        if currents:
            i_series = sum(currents) / len(currents)
        else:
            i_series = (p_total / v_total) if v_total > 0.1 else 0.0

        # 2. Çıkış Yükü Hesaplamaları
        v_out_clean = max(0.0, v_out)
        i_out_clean = max(0.0, i_out)
        p_out = v_out_clean * i_out_clean

        # 3. Temel Matematik Motoru
        # P_loss = P_in - P_out
        p_loss_raw = p_total - p_out
        p_loss = max(0.0, p_loss_raw)

        # Verimlilik η (%) = (P_out / P_in) * 100
        # Güvenlik korumaları: P_in çok düşükse veya çıkış akımı yoksa 0% göster
        if p_total > 0.5 and i_out_clean > 0.05:
            eff_raw = (p_out / p_total) * 100.0
            # Fiziksel sınır: Süperiletken değilse %100'ü geçemez (ani geçici durum filtrelemesi)
            efficiency = min(100.0, max(0.0, eff_raw))
        else:
            efficiency = 0.0

        # Pik Verimlilik Takibi
        if efficiency > self.peak_efficiency and efficiency < 99.9:
            self.peak_efficiency = efficiency

        # Termal Durum Sınıflandırması
        if p_loss < 6.0:
            thermal_status = "SAFE"       # Düşük kayıp (<6W)
        elif p_loss < 12.0:
            thermal_status = "WARM"       # Orta seviye ısınma (6W - 12W)
        else:
            thermal_status = "HIGH"       # Yüksek ısı yayılımı (>12W)

        return TelemetryFrame(
            mode=mode,
            hmp_connected=hmp_connected,
            utl_connected=utl_connected,
            input=InputTelemetry(
                v_total=round(v_total, 3),
                i_series=round(i_series, 3),
                p_total=round(p_total, 3),
                channels=processed_channels
            ),
            output=OutputTelemetry(
                v_out=round(v_out_clean, 4),
                i_out=round(i_out_clean, 3),
                p_out=round(p_out, 3),
                mode="CC",
                remote_sense=True
            ),
            efficiency=round(efficiency, 2),
            peak_efficiency=round(self.peak_efficiency, 2),
            p_loss=round(p_loss, 3),
            thermal_status=thermal_status
        )
