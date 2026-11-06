"""
Seri Port Tabanlı Cihaz Sürücüsü Temel Sınıfı
SCPI komutları, hata toleransı ve otomatik yeniden bağlanma desteği.
"""
import time
import threading
import logging
import re
from typing import Optional
import serial

logger = logging.getLogger("InstrumentDriver")

def parse_float(val_str: Optional[str]) -> Optional[float]:
    """SCPI yanitlarindan sayisal degeri birimlerden (V, A, W vb.) temizleyerek ceker."""
    if not val_str:
        return None
    m = re.search(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", val_str)
    if m:
        try:
            return float(m.group(0))
        except (ValueError, TypeError):
            return None
    return None

class BaseSerialDriver:
    def __init__(self, port: str, baudrate: int = 9600, timeout: float = 0.5):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_conn: Optional[serial.Serial] = None
        self.lock = threading.RLock()
        self.is_connected: bool = False
        self.last_reconnect_attempt: float = 0.0
        self.reconnect_interval_sec: float = 1.0
        self._consecutive_errors: int = 0
        self._max_consecutive_errors: int = 4

    def connect(self) -> bool:
        """Seri portu açmaya çalışır."""
        with self.lock:
            if self.serial_conn and self.serial_conn.is_open:
                self.is_connected = True
                return True

            now = time.time()
            if now - self.last_reconnect_attempt < self.reconnect_interval_sec:
                return False
            self.last_reconnect_attempt = now

            try:
                self.serial_conn = serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=self.timeout,
                    write_timeout=self.timeout
                )
                time.sleep(0.05)
                self.serial_conn.reset_input_buffer()
                self.serial_conn.reset_output_buffer()
                self.is_connected = True
                self._consecutive_errors = 0
                logger.info(f"[{self.__class__.__name__}] {self.port} portuna başarıyla bağlandı.")
                return True
            except Exception as e:
                self.is_connected = False
                logger.warning(f"[{self.__class__.__name__}] {self.port} bağlantı hatası: {e}")
                return False

    def disconnect(self):
        """Portu güvenli şekilde kapatır."""
        with self.lock:
            if self.serial_conn:
                try:
                    self.serial_conn.close()
                except Exception:
                    pass
                self.serial_conn = None
            self.is_connected = False

    def query(self, command: str) -> Optional[str]:
        """SCPI sorgusu gönderir ve yanıt satırını okur."""
        with self.lock:
            if not self.serial_conn or not self.serial_conn.is_open:
                return None
            try:
                cmd_bytes = (command.strip() + "\n").encode('ascii')
                self.serial_conn.reset_input_buffer()
                self.serial_conn.write(cmd_bytes)
                
                raw_response = self.serial_conn.readline()
                if not raw_response:
                    return None
                
                response = raw_response.decode('ascii', errors='ignore').strip()
                self._consecutive_errors = 0
                return response
            except Exception as e:
                self._consecutive_errors += 1
                logger.warning(f"[{self.__class__.__name__}] SCPI sorgu uyarısı ({command}) [{self._consecutive_errors}/{self._max_consecutive_errors}]: {e}")
                if self._consecutive_errors >= self._max_consecutive_errors:
                    logger.error(f"[{self.__class__.__name__}] Çok sayıda ardışık hata, port kapatılıyor.")
                    self.disconnect()
                return None

    def write(self, command: str) -> bool:
        """Yanıt beklemeyen SCPI komutu gönderir."""
        with self.lock:
            if not self.serial_conn or not self.serial_conn.is_open:
                return False
            try:
                cmd_bytes = (command.strip() + "\n").encode('ascii')
                self.serial_conn.write(cmd_bytes)
                self._consecutive_errors = 0
                return True
            except Exception as e:
                self._consecutive_errors += 1
                logger.warning(f"[{self.__class__.__name__}] SCPI yazma uyarısı ({command}) [{self._consecutive_errors}/{self._max_consecutive_errors}]: {e}")
                if self._consecutive_errors >= self._max_consecutive_errors:
                    logger.error(f"[{self.__class__.__name__}] Çok sayıda ardışık hata, port kapatılıyor.")
                    self.disconnect()
                return False
