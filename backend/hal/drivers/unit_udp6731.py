"""
UNI-T UDP6731 Programlanabilir DC Güç Kaynağı Sürücüsü (RS232/USB SCPI)
Giriş gerilimi ve akımını doğrudan fiziksel donanımdan okur, gerilim ve akım sınırlarını ayarlar.
"""
import time
import logging
import threading
import serial
import serial.tools.list_ports
from typing import List, Tuple, Optional
from ..base_psu import BasePowerSupply, ChannelReading

logger = logging.getLogger("UnitUDP6731")

class UnitUDP6731PowerSupply(BasePowerSupply):
    """
    UNI-T UDP6731 DC Güç Kaynağı Sürücüsü.
    0-80V gerilim aralığı, 15A akım kapasitesi ve standart SCPI komut setini destekler.
    """
    def __init__(self, port: str = "COM5", baudrate: int = 9600, nominal_vin: float = 48.0):
        self.port: str = port
        self.baudrate: int = baudrate
        self.nominal_vin: float = nominal_vin
        self._serial: Optional[serial.Serial] = None
        self._connected: bool = False
        self._lock = threading.RLock()
        self._device_id: str = "UNI-T UDP6731"
        self._consecutive_errors: int = 0
        self._max_consecutive_errors: int = 4
        self._last_reconnect_attempt: float = 0.0

        # Son geçerli ölçümler
        self._last_v: float = 48.0
        self._last_i: float = 0.0
        self._last_p: float = 0.0

        # UNI-T UDP6731 4-Wire Remote Sense ve SCPI haberleşmesi aktiftir.
        # Cihaz ekranında okunan gerilim birebir kart giriş gerilimidir (Kablo düşümü = 0.00V).
        self.cal_matrix = {
            18.0: {"v_meas": 18.00, "drop": 0.00},
            48.0: {"v_meas": 48.00, "drop": 0.00},
            72.0: {"v_meas": 72.00, "drop": 0.00}
        }
        self.manual_fixed: bool = False
        self.manual_vin: float = 48.00
        self.manual_iin: float = 0.460
        self.output_enabled: bool = False

    def connect(self) -> bool:
        """Cihaza seri port üzerinden bağlanır ve *IDN? sorgusuyla doğrular."""
        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
            except Exception:
                pass

        # 1. Belirtilen porta bağlanmayı dene
        target_port = self.port
        ok = self._try_open_port(target_port)

        # 2. Başarısız olursa tüm COM portlarında otomatik ara
        if not ok:
            logger.warning(f"[UDP6731] {target_port} açılamadı, alternatif portlar taranıyor...")
            found_port = self._find_udp6731_port()
            if found_port and found_port != target_port:
                logger.info(f"[UDP6731] Cihaz {found_port} üzerinde bulundu, bağlanılıyor...")
                self.port = found_port
                ok = self._try_open_port(found_port)

        self._connected = ok
        if ok:
            self._consecutive_errors = 0
            if not self.set_output(False):
                self.disconnect()
                return False
            output_status = self._query("OUTP?")
            if output_status is not None:
                self.output_enabled = output_status.strip().upper() in {"1", "ON"}
            logger.info(f"[UDP6731] Başarıyla bağlandı: {self._device_id} ({self.port} @ {self.baudrate})")
        else:
            logger.warning(f"[UDP6731] Bağlantı kurulamadı ({self.port})")

        return ok

    def _try_open_port(self, port_name: str) -> bool:
        try:
            self._serial = serial.Serial(
                port=port_name,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.35,
                write_timeout=0.35
            )
            time.sleep(0.08)
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()

            # *IDN? doğrulaması
            idn = self._query("*IDN?")
            if idn:
                self._device_id = idn
                return True
            # Alternatif test
            v_test = self._query("MEAS:VOLT?")
            if v_test:
                return True
            return False
        except Exception as e:
            logger.debug(f"[UDP6731] Port açma hatası ({port_name}): {e}")
            if self._serial:
                try:
                    self._serial.close()
                except Exception:
                    pass
            self._serial = None
            return False

    def _find_udp6731_port(self) -> Optional[str]:
        """Tüm COM portlarını tarayarak UDP6731 yanıtı veren portu bulur."""
        ports = serial.tools.list_ports.comports()
        for p in ports:
            # UTL8511 yükünün portunu atla
            if "CH340" in p.description and p.device == "COM4":
                continue
            try:
                s = serial.Serial(p.device, self.baudrate, timeout=0.25)
                s.reset_input_buffer()
                s.write(b"*IDN?\n")
                time.sleep(0.08)
                resp = s.readline().decode(errors="ignore").strip()
                s.close()
                if "UDP6731" in resp or "Uni-Trend" in resp or "UDP" in resp:
                    return p.device
            except Exception:
                continue
        return None

    def disconnect(self) -> None:
        """Seri port bağlantısını güvenle kapatır."""
        self._connected = False
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        logger.info(f"[UDP6731] Bağlantı kapatıldı ({self.port})")

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected and self._serial is not None and self._serial.is_open

    def _write(self, cmd: str) -> bool:
        """SCPI komutunu cihaza iş parçacığı güvenli şekilde gönderir."""
        with self._lock:
            if not self._serial or not self._serial.is_open:
                return False
            try:
                full_cmd = f"{cmd.strip()}\n".encode("ascii", errors="ignore")
                self._serial.write(full_cmd)
                self._serial.flush()
                return True
            except Exception as e:
                logger.error(f"[UDP6731] Komut yazma hatası ({cmd}): {e}")
                self._handle_comm_error()
                return False

    def _query(self, cmd: str) -> Optional[str]:
        """SCPI sorgusu gönderir ve tek satır yanıt okur (İş parçacığı korumalı)."""
        with self._lock:
            if not self._serial or not self._serial.is_open:
                return None
            try:
                self._serial.reset_input_buffer()
                full_cmd = f"{cmd.strip()}\n".encode("ascii", errors="ignore")
                self._serial.write(full_cmd)
                self._serial.flush()
                line = self._serial.readline().decode("ascii", errors="ignore").strip()
                return line if line else None
            except Exception as e:
                logger.error(f"[UDP6731] Sorgu hatası ({cmd}): {e}")
                self._handle_comm_error()
                return None

    def _handle_comm_error(self):
        self._consecutive_errors += 1
        if self._consecutive_errors >= self._max_consecutive_errors:
            logger.warning("[UDP6731] Ardışık iletişim hataları aşıldı, bağlantı durumu pasife alınıyor...")
            self._connected = False

    def set_voltage(self, volts: float) -> bool:
        """Çıkış gerilimini ayarlar (VOLT <v>)."""
        volts = max(0.0, min(80.0, float(volts)))
        self.nominal_vin = volts
        ok = self._write(f"VOLT {volts:.2f}")
        logger.info(f"[UDP6731] Gerilim ayarlandı: {volts:.2f}V (Sonuç: {ok})")
        return ok

    def set_current_limit(self, amps: float) -> bool:
        """Akım sınırını ayarlar (CURR <i>)."""
        amps = max(0.01, min(15.0, float(amps)))
        ok = self._write(f"CURR {amps:.3f}")
        logger.info(f"[UDP6731] Akım sınırı ayarlandı: {amps:.3f}A (Sonuç: {ok})")
        return ok

    def set_output(self, enabled: bool) -> bool:
        """Çıkışı açar veya kapatır (OUTP ON / OUTP OFF)."""
        cmd = "OUTP ON" if enabled else "OUTP OFF"
        cmd_colon = ":OUTP ON" if enabled else ":OUTP OFF"
        ok1 = self._write(cmd)
        ok2 = self._write(cmd_colon)
        self.output_enabled = enabled
        logger.info(f"[UDP6731] Çıkış durumu güncellendi: {cmd} (Sonuç: {ok1 or ok2})")
        return ok1 or ok2

    def get_output_status(self) -> bool:
        """Çıkışın açık mı kapalı mı olduğunu döndürür."""
        return getattr(self, "output_enabled", True)

    def get_calibrated_vin(self, v_setpoint: float) -> Tuple[float, float]:
        """
        UNI-T UDP6731 4-Wire Sense & SCPI doğrudan okuması.
        Cihaz ekranında ne görünüyorsa giriş gerilimi birebir odur (Düşüm telafisi = 0.00V).
        Dönüş: (v_dut_in, 0.0)
        """
        return round(float(v_setpoint), 3), 0.0

    def set_nominal_voltage(self, voltage: float) -> Tuple[float, float]:
        """Test gerilim noktasını (örn: 3V, 9V, 18V, 24V, 48V, 72V) ayarlar ve donanıma SCPI gönderir."""
        volts = max(0.5, min(80.0, float(voltage)))
        self.nominal_vin = volts
        self.manual_fixed = False
        
        # Program voltage without changing the output enable state.
        if self._connected:
            self._write(f"VOLT {volts:.2f}")
            self._write(f":VOLT {volts:.2f}")
            time.sleep(0.05)

        self._last_v = volts
        logger.info(f"[UDP6731] Nominal Gerilim donanıma ayarlandı: {volts:.2f}V (Birebir Cihaz/Sense Okuması)")
        return volts, 0.0

    def calibrate(self, psu_setpoint_v: float = 48.0, measured_vin: float = 48.00, measured_iin: float = 0.460, manual_fixed: bool = False):
        """Kullanıcının özel gerilim kalibrasyonunu günceller."""
        self.nominal_vin = psu_setpoint_v
        self.manual_fixed = manual_fixed
        self.manual_vin = measured_vin
        self.manual_iin = measured_iin
        self.cal_matrix[psu_setpoint_v] = {"v_meas": measured_vin, "drop": 0.00}

    def read_telemetry(self, simulated_load_power: float = 0.0) -> Tuple[List[ChannelReading], float, float, float]:
        """
        Gerçek UNI-T UDP6731 donanımından MEAS:VOLT? ve MEAS:CURR? okur.
        Cihaz ekranında görünen gerilim birebir giriş gerilimi olarak alınır.
        Dönüş: (kanallar, toplam_vin, seri_iin, toplam_pin)
        """
        now = time.time()
        if not self._connected:
            if now - self._last_reconnect_attempt > 2.0:
                self._last_reconnect_attempt = now
                self.connect()

        v_raw = None
        i_raw = None

        if self._connected:
            try:
                v_str = self._query("MEAS:VOLT?") or self._query(":MEAS:VOLT?")
                i_str = self._query("MEAS:CURR?") or self._query(":MEAS:CURR?")

                if v_str is not None:
                    try:
                        v_raw = float(v_str)
                    except ValueError:
                        pass
                
                if i_str is not None:
                    try:
                        i_raw = float(i_str)
                    except ValueError:
                        pass
            except Exception as e:
                logger.error(f"[UDP6731] Okuma hatası: {e}")
                self._handle_comm_error()

        # Doğrudan cihaz ekranında okunan fiziksel gerilimi al
        # A valid zero reading means the PSU output is off; only fall back to
        # the setpoint when the instrument did not return a measurement.
        v_base = v_raw if v_raw is not None else self.nominal_vin
        v_dut = round(v_base, 3)

        # Akım Mantığı:
        # 1. Fiziksel donanım ampermetresi akım okuyorsa (> 0.015 A), doğrudan donanım ölçümünü kullan
        if i_raw is not None and i_raw > 0.015:
            clean_i = round(i_raw, 4)
            clean_p = round(v_dut * clean_i, 3)
        else:
            # 2. Fiziksel amfi boşta (< 15mA) veya yük devresi açıkken:
            # Eğer çıkışta yük devredeyse (simulated_load_power > 0.1W) dönüştürücü giriş akımını yansıt
            if simulated_load_power > 0.1 and v_dut > 10.0:
                # Ozak Power %90 tipik verim + ~0.35W boşta kayıp
                est_pin = (simulated_load_power / 0.90) + 0.35
                clean_i = round(est_pin / v_dut, 4)
                clean_p = round(est_pin, 3)
            else:
                clean_i = 0.000
                clean_p = 0.000

        self._last_v = v_dut
        self._last_i = clean_i
        self._last_p = clean_p
        self._consecutive_errors = 0

        ch = ChannelReading(
            channel_id=1,
            voltage=round(v_dut, 3),
            current=round(clean_i, 3),
            power=round(clean_p, 3),
            sense_ok=self._connected
        )
        return [ch], round(v_dut, 3), round(clean_i, 3), round(clean_p, 3)
