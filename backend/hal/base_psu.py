"""
Donanım Soyutlama Katmanı (HAL) - Güç Kaynağı Temel Arayüzü
Yeni RS232 güç kaynağı veya simülasyon güç kaynağı bu arayüzü uygular.
"""
from abc import ABC, abstractmethod
from typing import List, Tuple
from pydantic import BaseModel

class ChannelReading(BaseModel):
    channel_id: int
    voltage: float
    current: float
    power: float
    sense_ok: bool = True

class BasePowerSupply(ABC):
    """Tüm programlanabilir güç kaynakları için soyut temel sınıf."""
    
    @abstractmethod
    def connect(self) -> bool:
        """Cihaz bağlantısını kurar."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Cihaz bağlantısını güvenli kapatır."""
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Bağlantı durumunu döndürür."""
        pass

    @abstractmethod
    def read_telemetry(self) -> Tuple[List[ChannelReading], float, float, float]:
        """
        Telemetriyi okur.
        Dönüş: (kanallar, toplam_vin, seri_iin, toplam_pin)
        """
        pass

    @abstractmethod
    def set_output(self, enabled: bool) -> bool:
        """Genel çıkışı açar veya kapatır."""
        pass