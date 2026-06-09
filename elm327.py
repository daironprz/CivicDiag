"""
ELM327 USB adapter driver.

Talks raw AT / OBD-II hex commands over a serial (COM) port to an
ELM327-compatible adapter. Tuned for ISO 9141-2, the protocol used by
the 1999 Honda Civic, but works with any protocol the adapter supports.
"""

import time
import threading

import serial
from serial.tools import list_ports


class ELM327Error(Exception):
    """Raised for adapter / bus level failures."""


class NoDataError(ELM327Error):
    """ECU gave no response for this request (often: PID not supported)."""


# Baud rates ELM327 clones commonly ship with, in order of likelihood.
BAUD_RATES = (38400, 115200, 9600, 57600, 230400)

PROTOCOL_NAMES = {
    "1": "SAE J1850 PWM",
    "2": "SAE J1850 VPW",
    "3": "ISO 9141-2",
    "4": "ISO 14230-4 KWP (5-baud init)",
    "5": "ISO 14230-4 KWP (fast init)",
    "6": "ISO 15765-4 CAN (11/500)",
    "7": "ISO 15765-4 CAN (29/500)",
    "8": "ISO 15765-4 CAN (11/250)",
    "9": "ISO 15765-4 CAN (29/250)",
    "A": "SAE J1939 CAN",
}


def find_ports():
    """Return [(device, description), ...] for plausible serial ports."""
    ports = []
    for p in list_ports.comports():
        ports.append((p.device, p.description or "Serial port"))
    return ports


class ELM327:
    def __init__(self, log_fn=None):
        self.ser = None
        self.port = None
        self.elm_version = ""
        self.protocol = ""
        self.protocol_name = ""
        self.lock = threading.RLock()
        self._log = log_fn or (lambda s: None)

    # ---------------- low level ----------------

    def _write(self, cmd):
        self.ser.reset_input_buffer()
        self.ser.write((cmd + "\r").encode("ascii", "ignore"))
        self._log(f">> {cmd}")

    def _read_until_prompt(self, timeout):
        """Read until the ELM '>' prompt appears or timeout (seconds)."""
        buf = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            chunk = self.ser.read(self.ser.in_waiting or 1)
            if chunk:
                buf += chunk
                if b">" in buf:
                    break
            else:
                time.sleep(0.01)
        text = buf.decode("ascii", "ignore").replace("\x00", "")
        self._log(f"<< {text.strip()}")
        return text

    def command(self, cmd, timeout=6.0):
        """Send a command, return list of non-empty response lines."""
        with self.lock:
            if not self.ser or not self.ser.is_open:
                raise ELM327Error("Not connected")
            self._write(cmd)
            text = self._read_until_prompt(timeout)
        lines = []
        for raw in text.replace(">", "").split("\r"):
            line = raw.strip()
            # echo may still be on during init; drop echoed command
            if not line or line.upper() == cmd.upper():
                continue
            lines.append(line)
        return lines

    # ---------------- connection ----------------

    def connect(self, port, baud=None):
        """Open the port and initialize the adapter + vehicle bus."""
        last_err = None
        rates = (baud,) if baud else BAUD_RATES
        for rate in rates:
            try:
                self.ser = serial.Serial(port, rate, timeout=0.1,
                                         write_timeout=2)
                time.sleep(0.3)
                # ATZ resets the chip; expect "ELM327 vX.X" in the banner
                lines = self.command("ATZ", timeout=3.0)
                banner = " ".join(lines)
                if "ELM327" in banner.upper() or "OBD" in banner.upper():
                    self.port = port
                    self.elm_version = banner.strip()
                    return self._initialize()
                self.ser.close()
            except (serial.SerialException, OSError) as e:
                last_err = e
                if self.ser:
                    try:
                        self.ser.close()
                    except OSError:
                        pass
        raise ELM327Error(
            f"No ELM327 adapter found on {port}."
            + (f" Last error: {last_err}" if last_err else "")
        )

    def _initialize(self):
        """Configure the adapter, then wake the vehicle bus."""
        for cmd in ("ATE0",   # echo off
                    "ATL0",   # linefeeds off
                    "ATS0",   # spaces off (we parse hex pairs)
                    "ATH0",   # headers off
                    "ATST96", # response timeout ~600ms (ISO 9141 is slow)
                    "ATAT1",  # adaptive timing
                    "ATSP0"): # auto protocol detect
            self.command(cmd, timeout=2.0)

        # First real request triggers the slow 5-baud ISO 9141 init.
        # Give it generous time and a couple of retries.
        ok = False
        for attempt in range(3):
            lines = self.command("0100", timeout=12.0)
            joined = " ".join(lines).upper()
            if "UNABLE" in joined or "ERROR" in joined:
                time.sleep(1.0)
                continue
            if any(l.replace(" ", "").startswith("41") for l in lines):
                ok = True
                break
        if not ok:
            raise ELM327Error(
                "Adapter found, but the car did not respond.\n"
                "Check: ignition ON (engine can be off), adapter firmly "
                "seated in the OBD port, and try again."
            )

        # Ask which protocol auto-detect settled on, e.g. "A3" = auto ISO9141
        lines = self.command("ATDPN", timeout=2.0)
        num = lines[0].strip().lstrip("A") if lines else ""
        self.protocol = num
        self.protocol_name = PROTOCOL_NAMES.get(num, f"Protocol {num}")
        return True

    def close(self):
        with self.lock:
            if self.ser:
                try:
                    self.command("ATPC", timeout=1.0)  # protocol close
                except ELM327Error:
                    pass
                try:
                    self.ser.close()
                except OSError:
                    pass
            self.ser = None
            self.port = None

    @property
    def connected(self):
        return self.ser is not None and self.ser.is_open

    # ---------------- OBD requests ----------------

    def query(self, request, timeout=6.0):
        """
        Send an OBD request like '010C' and return a list of data-byte
        lists, one per response line (multiple ECUs / multi-line answers
        each yield one entry). Bytes include the mode-echo byte
        (e.g. 0x41) and PID echo.
        """
        req = request.replace(" ", "").upper()
        expect = f"{int(req[0:2], 16) + 0x40:02X}"
        lines = self.command(req, timeout=timeout)

        joined = " ".join(lines).upper()
        if "NO DATA" in joined:
            raise NoDataError(f"NO DATA for {req}")
        for bad in ("UNABLE TO CONNECT", "BUS ERROR", "BUS BUSY",
                    "CAN ERROR", "DATA ERROR", "STOPPED", "FB ERROR"):
            if bad in joined:
                raise ELM327Error(f"{bad} during {req}")

        frames = []
        for line in lines:
            hexstr = line.replace(" ", "").upper()
            if "SEARCHING" in line.upper():
                continue
            if not hexstr.startswith(expect):
                continue
            if len(hexstr) % 2:
                hexstr = hexstr[:-1]  # drop stray nibble from line noise
            try:
                frames.append([int(hexstr[i:i + 2], 16)
                               for i in range(0, len(hexstr), 2)])
            except ValueError:
                continue
        if not frames:
            raise NoDataError(f"No valid response for {req}")
        return frames

    def query_pid(self, mode, pid, timeout=6.0):
        """Query one mode-01-style PID, return data bytes after the
        mode/PID echo from the first responding ECU."""
        frames = self.query(f"{mode:02X}{pid:02X}", timeout=timeout)
        return frames[0][2:]
