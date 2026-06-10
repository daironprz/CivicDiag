"""Offline sanity tests — decoders, DTC knowledge base, demo car,
report builders. No real car or GUI needed."""
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

# ---- DTC knowledge base integrity ----
for code, info in od.DTC_INFO.items():
    assert set(info) == {"sev", "drive", "causes", "check", "pids"}, code
    assert info["sev"] in od.SEVERITY_NAMES, code
    assert code in od.DTC_DESCRIPTIONS, f"{code} missing plain description"
    for pid in info["pids"]:
        assert od.pid_def(pid), f"{code} references unknown PID {pid:#x}"
for alias, target in od._DTC_ALIASES.items():
    assert target in od.DTC_INFO, f"alias {alias} -> missing {target}"
info = od.dtc_info("P1456")
assert info["severity_name"] == "Low" and info["causes"]
info = od.dtc_info("P0302")                          # via alias to P0300
assert info["severity"] == 3 and "plug" in " ".join(info["causes"]).lower()
info = od.dtc_info("P9999")                          # unknown: safe defaults
assert info["severity_name"] == "Moderate" and info["check"]

# ---- guided presets reference valid PIDs ----
from diagnostics import PRESETS
for name, p in PRESETS.items():
    assert p["blurb"] and p["look_for"], name
    for pid in p["pids"]:
        assert od.pid_def(pid), f"{name}: unknown PID {pid:#x}"
    for pid in p["alerts"]:
        assert pid in p["pids"], f"{name}: alert for unwatched PID"

# ---- demo car end-to-end (no GUI) ----
from demo_elm import DemoELM327
from elm327 import NoDataError

car = DemoELM327()
car.connect("DEMO")
assert car.connected
sup = od.decode_supported_pids(0x00, car.query_pid(0x01, 0x00))
assert 0x0C in sup and 0x05 in sup
rpm = od.PIDS[0x0C][3](car.query_pid(0x01, 0x0C))
assert 400 < rpm < 1400, rpm
stored = od.decode_dtc_frames(car.query("03"))
assert stored == ["P1456"], stored
pending = od.decode_dtc_frames(car.query("07"))
assert pending == ["P0133"], pending
stat = od.decode_monitor_status(car.query_pid(0x01, 0x01))
assert stat["mil"] and stat["dtc_count"] == 1
ff = car.query("020200")
assert od.decode_dtc_bytes(ff[0][3], ff[0][4]) == "P1456"
assert "V" in car.command("ATRV")[0]
car.query("04")                                      # clear codes
try:
    car.query("03")
    raise AssertionError("expected NoDataError after clear")
except NoDataError:
    pass
assert not od.decode_monitor_status(car.query_pid(0x01, 0x01))["mil"]

# ---- report builders ----
import reports

s = reports.empty_session()
s["vehicle"] = {"Adapter": "ELM327 v1.5", "Protocol": "ISO 9141-2"}
c = od.dtc_info("P1456")
c["kind"] = "STORED"
s["codes"] = [c]
s["readiness"] = [("Misfire", True, True), ("EVAP system", True, False),
                  ("EGR system", True, False)]
s["snapshot"] = [("Engine RPM", "780", "rpm", "750", "1100", "812")]
s["events"] = [("2026-06-09T10:00:00", "Felt stumble")]
s["notes"] = "test note"
txt = reports.session_to_txt(s)
assert "P1456" in txt and "Felt stumble" in txt
html = reports.build_html(s, "check")
assert "P1456" in html and "window.print" in html
html = reports.build_html(s, "presmog")
assert "NOT READY" in html or "LIKELY FAIL" in html  # 2 incomplete monitors
s2 = reports.empty_session()
s2["readiness"] = [("Misfire", True, True), ("EVAP system", True, False)]
cls, verdict = reports._smog_verdict(s2)
assert cls == "pass" and "one incomplete" in verdict.lower()
base = reports.empty_session()
base["codes"] = [dict(od.dtc_info("P1456"), kind="STORED")]
html = reports.build_html(reports.empty_session(), "beforeafter", base)
assert "Codes fixed" in html and "P1456" in html
name = reports.auto_name(s, "csv")
assert name.startswith("CivicDiag_") and name.endswith("_P1456.csv"), name
assert "P1456" in reports.codes_to_csv(s)
assert "P1456" in reports.codes_to_clipboard_text(s)

print("all tests passed")
