"""
Donanım Soyutlama Katmanı (HAL) - Elektronik Yük Temel Arayüzü
UNI-T UTL8511 veya simüle yük bu arayüzü uygular.
"""
from abc import ABC, abstractmethod
from typing import Optional, Tuple

class BaseLoad(ABC):
    """Tüm programlanabilir elektronik yükler için soyut temel sınıf."""

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
    def set_load_state(self, enabled: bool) -> bool:
        """Yük girişini açar (LOAD ON) veya kapatır (LOAD OFF)."""
        pass

    @property
    @abstractmethod
    def load_enabled(self) -> bool:
        """Yükün aktif olup olmadığını döndürür."""
        pass

    @abstractmethod
    def set_constant_current(self, amps: float) -> bool:
        """Sabit akım (CC) değerini ayarlar."""
        pass

    @property
    @abstractmethod
    def target_current(self) -> float:
        """Ayarlanan hedef akımı döndürür."""
        pass

    @abstractmethod
    def read_telemetry(self) -> Tuple[float, float, float]:
        """
        Anlık gerilim, akım ve gücü okur.
        Dönüş: (v_out, i_out, p_out)
        """
        pass