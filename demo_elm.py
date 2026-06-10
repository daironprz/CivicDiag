"""
Simulated ELM327 + 1999 Civic for demo mode — lets the whole app run
with no adapter or car attached. Mirrors the public interface of
elm327.ELM327.

The simulated car: warm-up in progress, MIL on with a stored P1456
(EVAP, tank side) and a pending P0133 (lazy primary O2), EVAP and EGR
monitors not yet ready.
"""

import math
import random
import threading
import time

from elm327 import NoDataError

DEMO_PORT = "DEMO"

# Mode-01 PIDs the simulated ECU supports (typical '99 Civic EX set)
_SUPPORTED = {0x01, 0x03, 0x04, 0x05, 0x06, 0x07, 0x0B, 0x0C, 0x0D, 0x0E,
              0x0F, 0x11, 0x13, 0x14, 0x15, 0x1C, 0x1F, 0x20, 0x21}

_FREEZE = {  # raw data bytes at the moment "P1456 was set" (45 mph cruise)
    0x03: [0x02, 0x00], 0x04: [0x59], 0x05: [0x82], 0x06: [0x84],
    0x07: [0x87], 0x0B: [0x23], 0x0C: [0x23, 0x00], 0x0D: [0x48],
    0x0E: [0xC6], 0x0F: [0x46], 0x11: [0x26], 0x14: [0x5A, 0x80],
    0x15: [0x7C, 0xFF],
}


def _mask(base):
    """Build a supported-PID bitmask reply for 01<base>."""
    out = [0, 0, 0, 0]
    for pid in _SUPPORTED:
        if base < pid <= base + 0x20:
            idx = pid - base - 1
            out[idx // 8] |= 0x80 >> (idx % 8)
    return out


class DemoELM327:
    """Duck-type stand-in for elm327.ELM327."""

    def __init__(self, log_fn=None):
        self._log = log_fn or (lambda s: None)
        self._connected = False
        self.port = DEMO_PORT
        self.elm_version = "ELM327 v1.5 (simulated)"
        self.protocol = "3"
        self.protocol_name = "ISO 9141-2 (simulated)"
        self.lock = threading.RLock()
        self.t0 = time.monotonic()
        self.stored = ["P1456"]
        self.pending = ["P0133"]
        self.mil = True

    # ---------------- connection ----------------

    def connect(self, port, baud=None):
        time.sleep(1.2)  # pretend to do the ISO init
        self._connected = True
        self.t0 = time.monotonic()
        self._log("<< [demo] simulated 1999 Civic connected")
        return True

    def close(self):
        self._connected = False

    @property
    def connected(self):
        return self._connected

    # ---------------- simulated engine state ----------------

    def _elapsed(self):
        return time.monotonic() - self.t0

    def _coolant_c(self):
        return min(90.0, 22.0 + self._elapsed() * 1.1)

    def _rpm(self):
        t = self._elapsed()
        warm_drop = 350 * math.exp(-t / 90)          # fast idle when cold
        wobble = 25 * math.sin(t * 1.7) + random.uniform(-15, 15)
        return 760 + warm_drop + wobble

    def _pid_bytes(self, pid):
        t = self._elapsed()
        if pid == 0x01:
            a = (0x80 if self.mil else 0) | len(self.stored)
            d = 0x84 if (self.stored or self.pending) else 0x00
            return [a, 0x07, 0xE5, d]               # EVAP+EGR not ready
        if pid in (0x00, 0x20, 0x40):
            if pid == 0x40:
                raise NoDataError("demo")
            return _mask(pid)
        if pid == 0x03:
            warm = self._coolant_c() > 45
            return [0x02 if warm else 0x01, 0x00]
        if pid == 0x04:
            return [int((22 + 4 * math.sin(t)) * 255 / 100)]
        if pid == 0x05:
            return [int(self._coolant_c()) + 40]
        if pid == 0x06:
            return [128 + int(5 * math.sin(t / 3) + random.uniform(-2, 2))]
        if pid == 0x07:
            return [128 + 4]                         # LTFT +3.1% (small leak)
        if pid == 0x0B:
            return [33 + random.randint(-2, 2)]
        if pid == 0x0C:
            v = int(self._rpm() * 4)
            return [v >> 8, v & 0xFF]
        if pid == 0x0D:
            return [0]
        if pid == 0x0E:
            return [int((16 + 3 * math.sin(t / 2) + 64) * 2)]
        if pid == 0x0F:
            return [28 + 40]
        if pid == 0x11:
            return [int(1.5 * 255 / 100)]
        if pid == 0x13:
            return [0x03]
        if pid == 0x14:                              # primary O2 oscillating
            warm = self._coolant_c() > 60
            v = 0.45 + (0.38 * math.sin(t * 5.5) if warm else 0.02)
            return [int(v / 0.005), 128]
        if pid == 0x15:                              # secondary, steady
            warm = self._coolant_c() > 60
            v = (0.62 + 0.04 * math.sin(t / 4)) if warm else 0.1
            return [int(v / 0.005), 0xFF]
        if pid == 0x1C:
            return [0x01]
        if pid == 0x1F:
            e = int(t)
            return [e >> 8, e & 0xFF]
        if pid == 0x21:
            return [0x00, 0x0C] if self.mil else [0, 0]
        raise NoDataError("demo")

    # ---------------- ELM327-compatible API ----------------

    def command(self, cmd, timeout=6.0):
        cmd = cmd.strip().upper()
        self._log(f">> {cmd}")
        if cmd == "ATRV":
            out = [f"{14.1 + random.uniform(-0.15, 0.15):.1f}V"]
        elif cmd.startswith("AT"):
            out = ["OK"]
        else:
            try:
                out = [" ".join(f"{b:02X}" for b in f)
                       for f in self.query(cmd)]
            except NoDataError:
                out = ["NO DATA"]
        self._log("<< " + " | ".join(out))
        time.sleep(0.06)
        return out

    def query(self, request, timeout=6.0):
        req = request.replace(" ", "").upper()
        mode = int(req[0:2], 16)
        time.sleep(0.09)  # ISO 9141-ish pacing
        if mode == 0x01:
            pid = int(req[2:4], 16)
            return [[0x41, pid] + self._pid_bytes(pid)]
        if mode == 0x02:
            pid = int(req[2:4], 16)
            if pid == 0x02:
                if not self.stored:
                    raise NoDataError("demo")
                return [[0x42, 0x02, 0x00, 0x14, 0x56]]
            if pid in _FREEZE and self.stored:
                return [[0x42, pid, 0x00] + _FREEZE[pid]]
            raise NoDataError("demo")
        if mode == 0x03:
            if not self.stored:
                raise NoDataError("demo")
            return [[0x43, 0x14, 0x56, 0x00, 0x00, 0x00, 0x00]]
        if mode == 0x07:
            if not self.pending:
                raise NoDataError("demo")
            return [[0x47, 0x01, 0x33, 0x00, 0x00, 0x00, 0x00]]
        if mode == 0x04:
            self.stored, self.pending, self.mil = [], [], False
            return [[0x44]]
        if mode == 0x05:
            tid, sensor = int(req[2:4], 16), int(req[4:6] or "0", 16)
            table = {(0x01, 1): 0x2D, (0x02, 1): 0x46, (0x07, 1): 0x0A,
                     (0x08, 1): 0xB4, (0x07, 2): 0x6E, (0x08, 2): 0x8C}
            if (tid, sensor) in table:
                return [[0x45, tid, sensor, table[(tid, sensor)]]]
            raise NoDataError("demo")
        raise NoDataError("demo")  # mode 09 etc: like a real '99

    def query_pid(self, mode, pid, timeout=6.0):
        return self.query(f"{mode:02X}{pid:02X}")[0][2:]
