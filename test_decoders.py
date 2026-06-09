"""Offline sanity tests for the decoding logic (no car needed)."""
import obd_data as od

# DTC byte-pair decoding
assert od.decode_dtc_bytes(0x01, 0x33) == "P0133"
assert od.decode_dtc_bytes(0x14, 0x56) == "P1456"
assert od.decode_dtc_bytes(0x03, 0x00) == "P0300"
assert od.decode_dtc_bytes(0x00, 0x00) is None

# Mode 03 frame: 43 01 33 14 56 00 00
codes = od.decode_dtc_frames([[0x43, 0x01, 0x33, 0x14, 0x56, 0x00, 0x00]])
assert codes == ["P0133", "P1456"], codes
assert "EVAP" in od.describe_dtc("P1456")

# PID decoders
assert od.PIDS[0x0C][3]([0x1A, 0xF8]) == 1726        # RPM
assert od.PIDS[0x05][3]([0x7B]) == 83                # coolant degC
assert od.PIDS[0x06][3]([0x80]) == 0.0               # STFT 0%
assert od.PIDS[0x0E][3]([0x90]) == 8.0               # timing advance
assert od.PIDS[0x14][3]([0x8C, 0xFF]) == "0.700 V"   # O2 no-trim case

# Monitor status: MIL on, 2 stored codes
st = od.decode_monitor_status([0x82, 0x07, 0x65, 0x04])
assert st["mil"] and st["dtc_count"] == 2
mon = {n: (s, c) for n, s, c in st["monitors"]}
assert mon["Misfire"] == (True, True)
assert mon["EVAP system"] == (True, False)           # supported, not ready

# Supported-PID bitmask 0xBE1FA813
sup = od.decode_supported_pids(0, [0xBE, 0x1F, 0xA8, 0x13])
assert sup == {0x01, 0x03, 0x04, 0x05, 0x06, 0x07, 0x0C, 0x0D, 0x0E,
               0x0F, 0x10, 0x11, 0x13, 0x15, 0x1C, 0x1F, 0x20}, \
    sorted(hex(p) for p in sup)
assert 0x20 in sup  # continuation bit

print("all decoder tests passed")
