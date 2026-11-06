"""
DC-DC Buck/Boost Telemetri Sistemi Yapılandırması
"""
from pydantic import BaseModel

class SystemConfig(BaseModel):
    # Ağ ve Sunucu Ayarları
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # Telemetri Örnekleme Aralığı (Saniyede 3-4 kez: 250ms - 300ms)
    SAMPLE_INTERVAL_SEC: float = 0.250

    # UNI-T UDP6731 DC Güç Kaynağı Ayarları (RS-232 / USB Virtual COM)
    PSU_PORT: str = "COM16"
    PSU_BAUDRATE: int = 9600
    PSU_TIMEOUT_SEC: float = 0.4
    PSU_MODEL: str = "UNI-T UDP6731"

    # UNI-T UTL8511 Elektronik Yük Ayarları (Arka Panel RS-232 / USB)
    UTL_PORT: str = "COM11"
    UTL_BAUDRATE: int = 9600
    UTL_TIMEOUT_SEC: float = 0.5

    # Arduino Uno USB-serial port for the five-slot relay selector
    RELAY_PORT: str = "COM14"
    RELAY_BAUDRATE: int = 9600

    # Conservative limits used to size the loaded module test matrix
    PSU_TEST_CURRENT_LIMIT_A: float = 12.0
    LOAD_TEST_MAX_CURRENT_A: float = 30.0

    # Başlangıç Çalışma Modu: 'SIMULATION' veya 'HARDWARE'
    INITIAL_MODE: str = "HARDWARE"

    # Simülasyon Varsayılanları (Fuar Demo Koşulları)
    SIM_DEFAULT_IOUT: float = 17.40  # Amper
    SIM_NOMINAL_VOUT: float = 5.000  # Volt
    SIM_NOMINAL_VIN_PER_CH: float = 16.000 # Volt (16V x 3 = 48V)

CONFIG = SystemConfig()
