"""Serial control for the Arduino Uno five-slot module relay selector."""
import logging
import threading
import time

import serial

logger = logging.getLogger("RelaySelector")


class ArduinoRelaySelector:
    """Protocol: one five-bit mask for pins 2..6, acknowledged by the Uno."""

    def __init__(self, port: str = "COM6", baudrate: int = 9600):
        self.port = port
        self.baudrate = baudrate
        self._serial = None
        self._lock = threading.RLock()

    @property
    def is_connected(self) -> bool:
        return bool(self._serial and self._serial.is_open)

    def connect(self) -> bool:
        with self._lock:
            if self.is_connected:
                return True
            try:
                self._serial = serial.Serial(self.port, self.baudrate, timeout=2.0, write_timeout=2.0)
                # Uno resets when the USB serial port opens.
                time.sleep(2.0)
                self._serial.reset_input_buffer()
                return True
            except (serial.SerialException, OSError) as exc:
                logger.error("Arduino relay connection failed on %s: %s", self.port, exc)
                self._serial = None
                return False

    def disconnect(self) -> None:
        with self._lock:
            if self._serial:
                try:
                    self._serial.close()
                finally:
                    self._serial = None

    def command(self, command: str) -> bool:
        if len(command) != 5 or any(bit not in "01" for bit in command):
            raise ValueError("Unsupported relay command")
        with self._lock:
            expected = f"OK {command}"
            for attempt in range(2):
                if not self.is_connected and not self.connect():
                    return False
                try:
                    self._serial.reset_input_buffer()
                    self._serial.write((command + "\n").encode("ascii"))
                    self._serial.flush()
                    response = self._serial.readline().decode("ascii", errors="ignore").strip()
                    if response == expected:
                        return True
                    logger.error("Unexpected relay response: %r (expected %r)", response, expected)
                except (serial.SerialException, OSError) as exc:
                    logger.error("Arduino relay command failed: %s", exc)
                # Reopening the Uno resets its firmware, clears stale serial data,
                # and leaves all relay outputs off before one retry.
                self.disconnect()
                if attempt == 0:
                    time.sleep(0.1)
            return False

    def select_slot(self, slot: int) -> bool:
        if slot not in range(1, 6):
            raise ValueError("Slot must be between 1 and 5")
        mask = ["0"] * 5
        mask[slot - 1] = "1"
        return self.command("".join(mask))

    def all_off(self) -> bool:
        return self.command("00000")
