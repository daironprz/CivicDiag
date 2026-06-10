"""
OBD-II data definitions: Mode 01 PID decoders, readiness monitors,
and trouble-code descriptions (generic SAE + Honda-specific P1 codes
for 1996-2000 models).
"""

# ---------------------------------------------------------------------
# Mode 01 PID decoders
# Each entry: pid -> (name, unit, num_data_bytes, decode_fn)
# decode_fn receives the raw data bytes (list of ints) and returns a value.
# ---------------------------------------------------------------------

FUEL_SYSTEM_STATUS = {
    0x00: "Not present",
    0x01: "Open loop (cold)",
    0x02: "Closed loop (normal)",
    0x04: "Open loop (load/decel)",
    0x08: "Open loop (system fault)",
    0x10: "Closed loop w/ fault",
}

SECONDARY_AIR = {
    0x01: "Upstream",
    0x02: "Downstream of cat",
    0x04: "Outside atmosphere / off",
}

OBD_STANDARDS = {
    1: "OBD-II (CARB)", 2: "OBD (EPA)", 3: "OBD and OBD-II",
    4: "OBD-I", 5: "Not OBD compliant", 6: "EOBD",
}


def _fuel_status(d):
    s1 = FUEL_SYSTEM_STATUS.get(d[0], f"0x{d[0]:02X}")
    if len(d) > 1 and d[1]:
        return f"B1: {s1} | B2: {FUEL_SYSTEM_STATUS.get(d[1], hex(d[1]))}"
    return s1


def _o2_volt_trim(d):
    volts = d[0] * 0.005
    if d[1] == 0xFF:
        return f"{volts:.3f} V"
    trim = (d[1] - 128) * 100.0 / 128
    return f"{volts:.3f} V / {trim:+.1f}%"


PIDS = {
    0x03: ("Fuel system status", "", 2, _fuel_status),
    0x04: ("Calculated engine load", "%", 1, lambda d: round(d[0] * 100 / 255, 1)),
    0x05: ("Coolant temperature", "°C", 1, lambda d: d[0] - 40),
    0x06: ("Short term fuel trim B1", "%", 1, lambda d: round((d[0] - 128) * 100 / 128, 1)),
    0x07: ("Long term fuel trim B1", "%", 1, lambda d: round((d[0] - 128) * 100 / 128, 1)),
    0x08: ("Short term fuel trim B2", "%", 1, lambda d: round((d[0] - 128) * 100 / 128, 1)),
    0x09: ("Long term fuel trim B2", "%", 1, lambda d: round((d[0] - 128) * 100 / 128, 1)),
    0x0A: ("Fuel pressure (gauge)", "kPa", 1, lambda d: d[0] * 3),
    0x0B: ("Intake manifold pressure (MAP)", "kPa", 1, lambda d: d[0]),
    0x0C: ("Engine RPM", "rpm", 2, lambda d: round((d[0] * 256 + d[1]) / 4)),
    0x0D: ("Vehicle speed", "km/h", 1, lambda d: d[0]),
    0x0E: ("Ignition timing advance", "° BTDC", 1, lambda d: round(d[0] / 2 - 64, 1)),
    0x0F: ("Intake air temperature", "°C", 1, lambda d: d[0] - 40),
    0x10: ("MAF air flow rate", "g/s", 2, lambda d: round((d[0] * 256 + d[1]) / 100, 2)),
    0x11: ("Throttle position", "%", 1, lambda d: round(d[0] * 100 / 255, 1)),
    0x12: ("Secondary air status", "", 1, lambda d: SECONDARY_AIR.get(d[0], hex(d[0]))),
    0x14: ("O2 sensor B1S1", "", 2, _o2_volt_trim),
    0x15: ("O2 sensor B1S2", "", 2, _o2_volt_trim),
    0x16: ("O2 sensor B1S3", "", 2, _o2_volt_trim),
    0x17: ("O2 sensor B1S4", "", 2, _o2_volt_trim),
    0x18: ("O2 sensor B2S1", "", 2, _o2_volt_trim),
    0x19: ("O2 sensor B2S2", "", 2, _o2_volt_trim),
    0x1A: ("O2 sensor B2S3", "", 2, _o2_volt_trim),
    0x1B: ("O2 sensor B2S4", "", 2, _o2_volt_trim),
    0x1C: ("OBD standard", "", 1, lambda d: OBD_STANDARDS.get(d[0], f"Code {d[0]}")),
    0x1F: ("Run time since engine start", "s", 2, lambda d: d[0] * 256 + d[1]),
    0x21: ("Distance with MIL on", "km", 2, lambda d: d[0] * 256 + d[1]),
    0x2E: ("Commanded EVAP purge", "%", 1, lambda d: round(d[0] * 100 / 255, 1)),
    0x2F: ("Fuel level", "%", 1, lambda d: round(d[0] * 100 / 255, 1)),
    0x30: ("Warm-ups since codes cleared", "", 1, lambda d: d[0]),
    0x31: ("Distance since codes cleared", "km", 2, lambda d: d[0] * 256 + d[1]),
    0x33: ("Barometric pressure", "kPa", 1, lambda d: d[0]),
    0x42: ("Control module voltage", "V", 2, lambda d: round((d[0] * 256 + d[1]) / 1000, 2)),
    0x43: ("Absolute load", "%", 2, lambda d: round((d[0] * 256 + d[1]) * 100 / 255, 1)),
    0x45: ("Relative throttle position", "%", 1, lambda d: round(d[0] * 100 / 255, 1)),
    0x46: ("Ambient air temperature", "°C", 1, lambda d: d[0] - 40),
}

# PIDs worth watching by default on a D16Y8 Civic
DEFAULT_LIVE_PIDS = [0x0C, 0x0D, 0x05, 0x0B, 0x0E, 0x11, 0x06, 0x07, 0x14, 0x15]


def decode_supported_pids(base, data):
    """Decode a 0100/0120/0140 bitmask reply into a set of PID numbers."""
    supported = set()
    for i, byte in enumerate(data[:4]):
        for bit in range(8):
            if byte & (0x80 >> bit):
                supported.add(base + i * 8 + bit + 1)
    return supported


# ---------------------------------------------------------------------
# Monitor status (Mode 01 PID 01)
# ---------------------------------------------------------------------

CONTINUOUS_MONITORS = [
    ("Misfire", 0x01),
    ("Fuel system", 0x02),
    ("Comprehensive component", 0x04),
]

# Non-continuous monitors, spark-ignition layout
NONCONT_MONITORS = [
    ("Catalyst", 0x01),
    ("Heated catalyst", 0x02),
    ("EVAP system", 0x04),
    ("Secondary air system", 0x08),
    ("A/C refrigerant", 0x10),
    ("O2 sensor", 0x20),
    ("O2 sensor heater", 0x40),
    ("EGR system", 0x80),
]


def decode_monitor_status(data):
    """
    Decode PID 01 (4 bytes): MIL state, stored-DTC count, and per-monitor
    supported / ready flags.
    Returns dict with keys: mil(bool), dtc_count(int),
    monitors -> list of (name, supported, complete).
    """
    a, b, c, d = data[0], data[1], data[2], data[3]
    out = {
        "mil": bool(a & 0x80),
        "dtc_count": a & 0x7F,
        "monitors": [],
    }
    for name, bit in CONTINUOUS_MONITORS:
        supported = bool(b & bit)
        complete = not bool(b & (bit << 4))
        out["monitors"].append((name, supported, complete))
    for name, bit in NONCONT_MONITORS:
        supported = bool(c & bit)
        complete = not bool(d & bit)
        out["monitors"].append((name, supported, complete))
    return out


# ---------------------------------------------------------------------
# DTC decoding
# ---------------------------------------------------------------------

_DTC_LETTER = ["P", "C", "B", "U"]


def decode_dtc_bytes(b1, b2):
    """Two raw bytes -> 'P0301' style code, or None for empty slot."""
    if b1 == 0 and b2 == 0:
        return None
    letter = _DTC_LETTER[(b1 >> 6) & 0x03]
    return f"{letter}{(b1 >> 4) & 0x03}{b1 & 0x0F:X}{(b2 >> 4) & 0x0F:X}{b2 & 0x0F:X}"


def decode_dtc_frames(frames):
    """Mode 03/07 response frames -> ordered list of DTC strings."""
    codes = []
    for frame in frames:
        data = frame[1:]  # drop mode echo byte (0x43 / 0x47)
        for i in range(0, len(data) - 1, 2):
            code = decode_dtc_bytes(data[i], data[i + 1])
            if code and code not in codes:
                codes.append(code)
    return codes


def describe_dtc(code):
    desc = DTC_DESCRIPTIONS.get(code)
    if desc:
        return desc
    if code.startswith("P1"):
        return "Manufacturer-specific code (see Honda service manual)"
    return "No description available (see service manual)"


# Generic SAE codes most relevant to a late-90s Honda, plus the full
# Honda-specific P1xxx set for 1996-2000 Civic/Accord-era ECUs.
DTC_DESCRIPTIONS = {
    # --- Air / fuel metering ---
    "P0101": "MAF sensor circuit range/performance",
    "P0102": "MAF sensor circuit low input",
    "P0103": "MAF sensor circuit high input",
    "P0105": "MAP sensor circuit malfunction",
    "P0106": "MAP sensor range/performance (mechanical fault, vacuum leak)",
    "P0107": "MAP sensor circuit low input",
    "P0108": "MAP sensor circuit high input",
    "P0110": "Intake air temperature (IAT) circuit malfunction",
    "P0111": "IAT sensor range/performance",
    "P0112": "IAT sensor circuit low input",
    "P0113": "IAT sensor circuit high input",
    "P0115": "Engine coolant temperature (ECT) circuit malfunction",
    "P0116": "ECT sensor range/performance",
    "P0117": "ECT sensor circuit low input",
    "P0118": "ECT sensor circuit high input",
    "P0120": "Throttle position sensor (TPS) circuit malfunction",
    "P0121": "TPS range/performance",
    "P0122": "TPS circuit low input",
    "P0123": "TPS circuit high input",
    "P0125": "Insufficient coolant temp for closed-loop (stuck-open thermostat)",
    "P0128": "Coolant temp below thermostat regulating temperature",
    "P0130": "O2 sensor circuit malfunction (B1S1, primary)",
    "P0131": "O2 sensor low voltage (B1S1)",
    "P0132": "O2 sensor high voltage (B1S1)",
    "P0133": "O2 sensor slow response (B1S1)",
    "P0134": "O2 sensor no activity (B1S1)",
    "P0135": "O2 sensor heater circuit (B1S1, primary)",
    "P0136": "O2 sensor circuit malfunction (B1S2, secondary)",
    "P0137": "O2 sensor low voltage (B1S2)",
    "P0138": "O2 sensor high voltage (B1S2)",
    "P0139": "O2 sensor slow response (B1S2)",
    "P0140": "O2 sensor no activity (B1S2)",
    "P0141": "O2 sensor heater circuit (B1S2, secondary)",
    "P0170": "Fuel trim malfunction (Bank 1)",
    "P0171": "System too lean (Bank 1) — vacuum leak, weak fuel pump, dirty injectors",
    "P0172": "System too rich (Bank 1) — leaking injector, FPR, bad O2",
    # --- Injectors / misfire ---
    "P0201": "Injector circuit — cylinder 1",
    "P0202": "Injector circuit — cylinder 2",
    "P0203": "Injector circuit — cylinder 3",
    "P0204": "Injector circuit — cylinder 4",
    "P0300": "Random/multiple cylinder misfire detected",
    "P0301": "Cylinder 1 misfire detected",
    "P0302": "Cylinder 2 misfire detected",
    "P0303": "Cylinder 3 misfire detected",
    "P0304": "Cylinder 4 misfire detected",
    "P0325": "Knock sensor circuit malfunction",
    "P0335": "Crankshaft position (CKP) sensor circuit",
    "P0336": "CKP sensor range/performance",
    "P0340": "Camshaft position (CMP/CYP) sensor circuit",
    "P0341": "CMP sensor range/performance",
    # --- EGR / EVAP / emissions ---
    "P0401": "EGR insufficient flow — clogged EGR ports (very common on Honda)",
    "P0403": "EGR circuit malfunction",
    "P0404": "EGR circuit range/performance",
    "P0420": "Catalyst efficiency below threshold (cat or secondary O2)",
    "P0441": "EVAP incorrect purge flow",
    "P0442": "EVAP small leak detected",
    "P0443": "EVAP purge control valve circuit",
    "P0446": "EVAP vent control circuit",
    "P0451": "EVAP pressure sensor range/performance",
    "P0452": "EVAP pressure sensor low input",
    "P0453": "EVAP pressure sensor high input",
    "P0455": "EVAP large leak detected (check gas cap first)",
    "P0456": "EVAP very small leak detected",
    "P0457": "EVAP leak detected (loose/missing fuel cap)",
    # --- Speed / idle / electrical ---
    "P0500": "Vehicle speed sensor (VSS) malfunction",
    "P0501": "VSS range/performance",
    "P0505": "Idle air control (IAC) system malfunction",
    "P0506": "Idle control — RPM lower than expected",
    "P0507": "Idle control — RPM higher than expected",
    "P0560": "System voltage malfunction",
    "P0562": "System voltage low (charging system)",
    "P0563": "System voltage high",
    "P0601": "ECM/PCM internal memory checksum error",
    "P0603": "ECM keep-alive memory (KAM) error",
    "P0605": "ECM ROM error",
    # --- Transmission (automatic) ---
    "P0700": "Transmission control system malfunction (TCM has codes)",
    "P0705": "Transmission range sensor circuit",
    "P0715": "Mainshaft speed sensor circuit",
    "P0720": "Countershaft speed sensor circuit",
    "P0725": "Engine speed input circuit",
    "P0730": "Incorrect gear ratio",
    "P0740": "Torque converter clutch circuit",
    "P0753": "Shift solenoid A electrical",
    "P0758": "Shift solenoid B electrical",
    "P0780": "Shift malfunction",
    # --- Honda-specific P1xxx (1996-2000 Civic et al.) ---
    "P1106": "BARO sensor circuit range/performance",
    "P1107": "BARO sensor circuit low input",
    "P1108": "BARO sensor circuit high input",
    "P1121": "Throttle position lower than expected",
    "P1122": "Throttle position higher than expected",
    "P1128": "MAP lower than expected",
    "P1129": "MAP higher than expected",
    "P1149": "Primary HO2S (S1) circuit range/performance",
    "P1162": "Primary HO2S (S1) circuit malfunction",
    "P1163": "Primary HO2S (S1) slow response",
    "P1164": "Primary HO2S (S1) range/performance",
    "P1165": "Primary HO2S (S1) circuit range/performance",
    "P1166": "Primary HO2S (S1) heater system electrical",
    "P1167": "Primary HO2S (S1) heater system",
    "P1168": "Primary HO2S (S1) label low input",
    "P1169": "Primary HO2S (S1) label high input",
    "P1259": "VTEC system malfunction (pressure switch / solenoid — B/D series)",
    "P1297": "Electrical load detector (ELD) circuit low input",
    "P1298": "Electrical load detector (ELD) circuit high input",
    "P1300": "Random/multiple cylinder misfire detected",
    "P1336": "Crankshaft speed fluctuation (CKF) sensor intermittent",
    "P1337": "Crankshaft speed fluctuation (CKF) sensor no signal",
    "P1359": "CKP/TDC/CYP sensor connector disconnected",
    "P1361": "TDC sensor intermittent interruption",
    "P1362": "TDC sensor no signal",
    "P1366": "TDC sensor 2 intermittent interruption",
    "P1367": "TDC sensor 2 no signal",
    "P1381": "Cylinder position (CYP) sensor intermittent interruption",
    "P1382": "Cylinder position (CYP) sensor no signal",
    "P1456": "EVAP leak detected — fuel tank system (gas cap, tank-side)",
    "P1457": "EVAP leak detected — control canister system (canister-side)",
    "P1459": "EVAP purge flow switch malfunction",
    "P1486": "Thermostat range/performance",
    "P1491": "EGR valve lift insufficient (clogged EGR passages)",
    "P1498": "EGR valve lift sensor high voltage",
    "P1508": "IAC valve circuit failure",
    "P1509": "IAC valve circuit failure",
    "P1519": "Idle air control valve circuit failure",
    "P1607": "ECM/PCM internal circuit failure A",
    "P1655": "SEAF/SEFA/TMA/TMB signal line failure",
    "P1660": "A/T FI signal A circuit failure",
    "P1676": "FPTDR signal line failure",
    "P1681": "A/T FI signal A low input",
    "P1682": "A/T FI signal A high input",
    "P1686": "A/T FI signal B low input",
    "P1687": "A/T FI signal B high input",
    "P1705": "A/T gear position signal — short or open",
    "P1706": "A/T gear position signal — multiple signals",
    "P1738": "A/T clutch pressure control solenoid B",
    "P1739": "A/T clutch pressure control solenoid C",
    "P1753": "A/T lock-up control solenoid A",
    "P1758": "A/T lock-up control solenoid B",
    "P1768": "A/T clutch pressure control solenoid A",
    "P1786": "A/T cold engine start signal",
    "P1790": "A/T throttle position signal failure",
    "P1791": "A/T vehicle speed signal failure",
    "P1792": "A/T engine coolant temp signal failure",
    "P1794": "A/T barometric pressure signal failure",
}

# ---------------------------------------------------------------------
# Virtual PIDs (not real OBD PIDs — sourced from the adapter itself)
# ---------------------------------------------------------------------

PID_BATT = 0x1000  # adapter-measured battery voltage via ATRV

VIRTUAL_PIDS = {
    PID_BATT: ("Battery voltage (adapter)", "V", 0, None),
}


def pid_def(pid):
    """Return (name, unit, nbytes, decode) for a real or virtual PID."""
    return PIDS.get(pid) or VIRTUAL_PIDS.get(pid)


# ---------------------------------------------------------------------
# Rich DTC knowledge base — severity, drivability, common causes on a
# 1996-2000 Civic, what to check first, and related live-data PIDs.
# Severity: 1 = Low, 2 = Moderate, 3 = High, 4 = Severe.
# ---------------------------------------------------------------------

SEVERITY_NAMES = {1: "Low", 2: "Moderate", 3: "High", 4: "Severe"}

_TRIM_PIDS = [0x06, 0x07, 0x0B, 0x0C, 0x14, 0x15]
_MISFIRE_PIDS = [0x0C, 0x04, 0x06, 0x07, 0x0E, 0x05, 0x14]
_O2_PIDS = [0x14, 0x15, 0x06, 0x07, 0x0C]
_TEMP_PIDS = [0x05, 0x0C, 0x0F]

DTC_INFO = {
    # ---- MAP / intake ----
    "P0106": dict(sev=2, drive="OK to drive short-term; expect poor mileage "
                  "and hesitation.",
                  causes=["Cracked or loose vacuum hose to the MAP sensor",
                          "Intake manifold vacuum leak",
                          "Failing MAP sensor"],
                  check=["Inspect the small vacuum hose from the throttle "
                         "body to the MAP sensor for cracks",
                         "With ignition ON engine off, MAP should read close "
                         "to barometric (~101 kPa); at idle ~30-40 kPa"],
                  pids=[0x0B, 0x0C, 0x06, 0x07, 0x11]),
    "P0107": dict(sev=2, drive="Driveable but the ECU falls back to a fixed "
                  "map — sluggish and rich.",
                  causes=["MAP sensor unplugged or wiring open",
                          "Failed MAP sensor"],
                  check=["Re-seat the MAP sensor connector on the throttle "
                         "body", "Check for 5V reference at the connector"],
                  pids=[0x0B, 0x0C]),
    "P0108": dict(sev=2, drive="Driveable with reduced performance.",
                  causes=["Shorted MAP sensor signal", "Failed sensor"],
                  check=["Re-seat the MAP connector; inspect wiring chafe "
                         "near the throttle body"],
                  pids=[0x0B, 0x0C]),
    # ---- IAT / ECT ----
    "P0111": dict(sev=1, drive="Safe to drive.",
                  causes=["IAT sensor drifting out of spec",
                          "Poor connector contact"],
                  check=["IAT should read close to ambient when cold — "
                         "compare with coolant temp after sitting overnight"],
                  pids=[0x0F, 0x05]),
    "P0112": dict(sev=1, drive="Safe to drive; may run slightly rich.",
                  causes=["IAT shorted", "Wrong/failed sensor"],
                  check=["Unplug the IAT (in the intake tube) and see if the "
                         "reading changes to -40"], pids=[0x0F]),
    "P0113": dict(sev=1, drive="Safe to drive; may run slightly lean.",
                  causes=["IAT unplugged or open circuit"],
                  check=["Re-seat the IAT connector on the intake tube"],
                  pids=[0x0F]),
    "P0116": dict(sev=2, drive="Watch the temp gauge; OK for short trips.",
                  causes=["Stuck-open thermostat (very common)",
                          "Failing ECT sensor", "Low coolant"],
                  check=["Watch coolant temp in Live Data — it should climb "
                         "steadily to ~85-95°C and hold",
                         "Check coolant level when cold"],
                  pids=_TEMP_PIDS),
    "P0117": dict(sev=2, drive="Driveable; cold-start enrichment will be "
                  "wrong (hard starts, rich running).",
                  causes=["ECT sensor shorted", "Wiring pinched"],
                  check=["Re-seat the ECT connector (back of the head, near "
                         "the distributor)"], pids=[0x05]),
    "P0118": dict(sev=2, drive="Driveable; may idle poorly when cold and "
                  "the fans may run constantly.",
                  causes=["ECT unplugged/open", "Corroded connector"],
                  check=["Re-seat the ECT connector; look for green "
                         "corrosion in the plug"], pids=[0x05]),
    "P0125": dict(sev=2, drive="Safe to drive; mileage suffers and the cat "
                  "may not reach temp.",
                  causes=["Stuck-open thermostat (classic '90s Honda "
                          "failure)", "Low coolant", "Lazy ECT sensor"],
                  check=["Live Data: does coolant temp plateau below ~80°C "
                         "on the highway? Replace the thermostat"],
                  pids=_TEMP_PIDS),
    "P0128": dict(sev=2, drive="Safe to drive.",
                  causes=["Stuck-open thermostat", "Low coolant"],
                  check=["Replace the thermostat (cheap, easy on a D16)"],
                  pids=_TEMP_PIDS),
    # ---- TPS ----
    "P0121": dict(sev=2, drive="Driveable; possible hesitation and odd "
                  "shifting on automatics.",
                  causes=["Worn TPS track", "Loose TPS"],
                  check=["Live Data: throttle % should sweep smoothly 0→100 "
                         "with no jumps as you slowly press the pedal"],
                  pids=[0x11, 0x0C]),
    "P0122": dict(sev=2, drive="Driveable with poor throttle response.",
                  causes=["TPS signal shorted low", "Unplugged TPS"],
                  check=["Re-seat the TPS connector on the throttle body"],
                  pids=[0x11]),
    "P0123": dict(sev=2, drive="Driveable; may hold high idle.",
                  causes=["TPS signal shorted high"],
                  check=["Re-seat the TPS connector; inspect wiring"],
                  pids=[0x11]),
    # ---- O2 sensors ----
    "P0131": dict(sev=2, drive="Safe to drive; runs rich, wastes fuel, can "
                  "eventually damage the cat.",
                  causes=["Aged primary O2 sensor", "Exhaust leak before "
                          "the sensor", "Wiring chafe"],
                  check=["Live Data: B1S1 should swing 0.1-0.9V at warm "
                         "idle. Stuck low = lean or dead sensor"],
                  pids=_O2_PIDS),
    "P0133": dict(sev=2, drive="Safe to drive short-term.",
                  causes=["Lazy/aged primary O2 sensor (most common)",
                          "Exhaust leak", "Contaminated sensor"],
                  check=["Watch B1S1 voltage: it should cross 0.45V several "
                         "times per second at 2000 rpm. Slow swings = "
                         "replace the sensor"],
                  pids=_O2_PIDS),
    "P0134": dict(sev=2, drive="Safe to drive; closed-loop fueling is lost.",
                  causes=["Unplugged O2 sensor", "Blown O2 heater fuse",
                          "Dead sensor"],
                  check=["Re-seat the O2 connector; check fuse #15 (ECU)"],
                  pids=_O2_PIDS),
    "P0135": dict(sev=2, drive="Safe to drive; slow to enter closed loop.",
                  causes=["O2 heater element burned out", "Wiring/fuse"],
                  check=["Sensor heater should draw ~1-2A cold; check the "
                         "heater fuse"], pids=_O2_PIDS),
    "P0136": dict(sev=1, drive="Safe to drive.",
                  causes=["Aged secondary O2", "Exhaust leak at the cat"],
                  check=["B1S2 should be relatively steady (~0.6V) once "
                         "warm; constant fast switching = weak cat too"],
                  pids=[0x15, 0x14]),
    "P0141": dict(sev=1, drive="Safe to drive.",
                  causes=["Secondary O2 heater burned out", "Fuse/wiring"],
                  check=["Check heater fuse; re-seat the connector near the "
                         "cat"], pids=[0x15]),
    # ---- Fuel trim ----
    "P0171": dict(sev=2, drive="Driveable, but prolonged lean running can "
                  "cause hesitation and overheated exhaust.",
                  causes=["Vacuum leak (intake gasket, brake booster hose, "
                          "PCV)", "Weak fuel pump / clogged filter",
                          "Dirty injectors", "Exhaust leak fooling the O2"],
                  check=["Live Data: LTFT above +10% at idle that drops at "
                         "2500 rpm = vacuum leak",
                         "Listen for hissing around the intake manifold",
                         "Check fuel pressure if trims are high at all RPM"],
                  pids=_TRIM_PIDS),
    "P0172": dict(sev=2, drive="Driveable; expect poor mileage, fouled "
                  "plugs, possible cat damage long-term.",
                  causes=["Leaking injector", "High fuel pressure (bad "
                          "regulator)", "Stuck-open purge valve",
                          "Dead primary O2"],
                  check=["Pull a spark plug — black sooty plugs confirm "
                         "rich", "Smell fuel in the vacuum line to the "
                         "pressure regulator (= leaking diaphragm)"],
                  pids=_TRIM_PIDS),
    # ---- Misfires ----
    "P0300": dict(sev=3, drive="Drive gently and fix soon — raw fuel from "
                  "misfires destroys the catalytic converter.",
                  causes=["Worn plugs/wires/cap/rotor (check first on this "
                          "engine)", "Vacuum leak", "Low fuel pressure",
                          "Low compression"],
                  check=["Tune-up parts first: plugs, wires, cap, rotor",
                         "Watch fuel trims — big positive = lean misfire"],
                  pids=_MISFIRE_PIDS),
    "P0325": dict(sev=2, drive="Driveable; the ECU retards timing as a "
                  "precaution, so power and mileage drop.",
                  causes=["Knock sensor failed (common with age)",
                          "Wiring open under the intake manifold"],
                  check=["Check the single-wire connector under the intake "
                         "manifold"], pids=[0x0E, 0x0C, 0x05]),
    "P0335": dict(sev=3, drive="Car may stall or not restart — address "
                  "promptly.",
                  causes=["CKP sensor (inside distributor on this engine)",
                          "Distributor wiring"],
                  check=["On a '99 Civic the CKP/TDC/CYP sensors live in "
                         "the distributor — inspect its connectors; "
                         "distributor replacement often fixes all three "
                         "sensor codes"],
                  pids=[0x0C]),
    "P0340": dict(sev=3, drive="May stall / crank-no-start. Fix promptly.",
                  causes=["CMP sensor in the distributor", "Wiring"],
                  check=["Same distributor diagnosis as P0335"],
                  pids=[0x0C]),
    # ---- EGR / cat / EVAP ----
    "P0401": dict(sev=1, drive="Safe to drive; it's an emissions fault.",
                  causes=["Clogged EGR passages in the intake manifold "
                          "(THE classic D16 failure)", "Lazy EGR valve"],
                  check=["Clean the EGR ports in the intake manifold — "
                         "there's a well-known Honda service procedure",
                         "Check the EGR valve moves freely with vacuum"],
                  pids=[0x0B, 0x0C, 0x0E]),
    "P0420": dict(sev=1, drive="Safe to drive; will fail smog.",
                  causes=["Worn catalytic converter", "Lazy secondary O2 "
                          "reading like a bad cat", "Exhaust leak"],
                  check=["Compare O2 sensors in Live Data: if B1S2 mirrors "
                         "B1S1's fast switching when warm, the cat is weak",
                         "Rule out exhaust leaks and O2 sensor age first — "
                         "cheaper than a cat"],
                  pids=[0x14, 0x15, 0x05]),
    "P0441": dict(sev=1, drive="Safe to drive.",
                  causes=["Purge valve stuck/blocked", "Cracked purge lines"],
                  check=["Follow the purge line from the canister (by the "
                         "fuel tank) to the throttle body"],
                  pids=[0x06, 0x07]),
    "P0443": dict(sev=1, drive="Safe to drive.",
                  causes=["Purge solenoid unplugged or failed"],
                  check=["Re-seat the purge solenoid connector"],
                  pids=[]),
    "P0455": dict(sev=1, drive="Safe to drive.",
                  causes=["Loose or bad gas cap (check first!)",
                          "Cracked EVAP hose", "Canister vent valve"],
                  check=["Tighten the gas cap until it clicks, clear the "
                         "code, drive a few days — if it stays gone, done"],
                  pids=[]),
    "P0457": dict(sev=1, drive="Safe to drive.",
                  causes=["Gas cap left loose after refueling"],
                  check=["Tighten the cap; inspect its rubber seal"],
                  pids=[]),
    # ---- Idle / speed / electrical ----
    "P0500": dict(sev=2, drive="Driveable; speedometer and cruise may not "
                  "work, automatics shift poorly.",
                  causes=["VSS on the transmission failed", "Cluster wiring"],
                  check=["Does the speedometer work? If dead too, suspect "
                         "the VSS on top of the transaxle"],
                  pids=[0x0D, 0x0C]),
    "P0505": dict(sev=2, drive="Driveable; idle may surge, hunt or stall.",
                  causes=["Dirty IAC/EACV valve (very common)",
                          "Vacuum leak", "Low coolant (air pocket through "
                          "the IAC coolant passage)"],
                  check=["Remove and clean the IAC valve with throttle-body "
                         "cleaner", "Burp the cooling system"],
                  pids=[0x0C, 0x0B, 0x11, 0x05]),
    "P0506": dict(sev=1, drive="Driveable.",
                  causes=["Dirty IAC", "Carbon-clogged throttle body"],
                  check=["Clean the throttle body and IAC"],
                  pids=[0x0C, 0x0B, 0x11]),
    "P0507": dict(sev=1, drive="Driveable.",
                  causes=["Vacuum leak", "IAC stuck open",
                          "Throttle cable/stop misadjusted"],
                  check=["Listen for hissing; check the brake booster hose"],
                  pids=[0x0C, 0x0B, 0x11]),
    "P0562": dict(sev=3, drive="Risk of stalling/no-restart — test the "
                  "charging system now.",
                  causes=["Failing alternator", "Worn battery",
                          "Corroded battery terminals/grounds"],
                  check=["Use the Charging/Battery preset in Guided "
                         "Diagnostics: ~12.6V engine off, 13.5-14.7V "
                         "running"],
                  pids=[PID_BATT]),
    "P0563": dict(sev=3, drive="Stop soon — overvoltage cooks the battery "
                  "and electronics.",
                  causes=["Failed voltage regulator (in the alternator)"],
                  check=["Battery voltage above ~15.1V running confirms it"],
                  pids=[PID_BATT]),
    "P0601": dict(sev=3, drive="If it runs, drive minimally; behaviour can "
                  "be unpredictable.",
                  causes=["ECM internal fault", "Failing main relay solder "
                          "joints mimicking ECU faults"],
                  check=["Check battery/ground connections, then suspect "
                         "the ECM (used D16 ECUs are cheap)"],
                  pids=[]),
    "P0700": dict(sev=2, drive="Driveable but diagnose soon; the "
                  "transmission computer set a code.",
                  causes=["See the specific P17xx code accompanying this"],
                  check=["Read codes again — the paired P17xx code is the "
                         "real story"],
                  pids=[0x0D, 0x0C]),
    "P0740": dict(sev=2, drive="Driveable; lock-up clutch issues hurt "
                  "highway mileage and may shudder.",
                  causes=["Lock-up solenoid", "Dirty ATF"],
                  check=["Change the ATF with genuine Honda fluid first — "
                         "fixes many '90s Honda A/T complaints"],
                  pids=[0x0D, 0x0C]),
    # ---- Honda-specific ----
    "P1106": dict(sev=1, drive="Safe to drive.",
                  causes=["BARO sensor (inside the ECM) drift"],
                  check=["Often accompanies other MAP faults — check those "
                         "first"], pids=[0x0B]),
    "P1121": dict(sev=2, drive="Driveable.",
                  causes=["TPS misadjusted or worn"],
                  check=["Sweep the throttle in Live Data, watch for "
                         "dropouts"], pids=[0x11]),
    "P1122": dict(sev=2, drive="Driveable.",
                  causes=["TPS misadjusted or worn"],
                  check=["Sweep the throttle in Live Data, watch for "
                         "dropouts"], pids=[0x11]),
    "P1128": dict(sev=2, drive="Driveable.",
                  causes=["MAP reading low vs throttle — vacuum hose or "
                          "sensor"],
                  check=["Inspect the MAP vacuum hose"], pids=[0x0B, 0x11]),
    "P1129": dict(sev=2, drive="Driveable.",
                  causes=["MAP reading high vs throttle"],
                  check=["Inspect the MAP hose and sensor"],
                  pids=[0x0B, 0x11]),
    "P1149": dict(sev=2, drive="Safe to drive short-term.",
                  causes=["Primary O2 sensor aging"],
                  check=["Watch B1S1 switching speed in Live Data"],
                  pids=_O2_PIDS),
    "P1162": dict(sev=2, drive="Safe to drive short-term.",
                  causes=["Primary O2 sensor circuit"],
                  check=["Re-seat the connector; check heater fuse"],
                  pids=_O2_PIDS),
    "P1163": dict(sev=2, drive="Safe to drive short-term.",
                  causes=["Primary O2 sensor slow response (aged sensor)"],
                  check=["Replace the primary O2 if original/old"],
                  pids=_O2_PIDS),
    "P1164": dict(sev=2, drive="Safe to drive short-term.",
                  causes=["Primary O2 range/performance"],
                  check=["Replace the primary O2 if original/old"],
                  pids=_O2_PIDS),
    "P1166": dict(sev=2, drive="Safe to drive.",
                  causes=["Primary O2 heater circuit"],
                  check=["Check the O2 heater fuse and connector"],
                  pids=_O2_PIDS),
    "P1167": dict(sev=2, drive="Safe to drive.",
                  causes=["Primary O2 heater system"],
                  check=["Check the O2 heater fuse and connector"],
                  pids=_O2_PIDS),
    "P1259": dict(sev=2, drive="Driveable — VTEC just won't engage (down "
                  "on top-end power).",
                  causes=["Low oil level/pressure (check FIRST)",
                          "Clogged VTEC solenoid screen",
                          "VTEC pressure switch", "Solenoid wiring"],
                  check=["Check the oil level NOW — low oil is the #1 cause",
                         "Remove the VTEC solenoid (2 bolts) and clean its "
                         "small filter screen"],
                  pids=[0x0C, 0x11, 0x0E]),
    "P1297": dict(sev=1, drive="Safe to drive; idle may dip with electrical "
                  "loads.",
                  causes=["ELD unit in the under-hood fuse box"],
                  check=["Turn on headlights+defroster at idle — idle "
                         "should compensate; ELD units are cheap"],
                  pids=[0x0C, PID_BATT]),
    "P1298": dict(sev=1, drive="Safe to drive.",
                  causes=["ELD unit in the under-hood fuse box"],
                  check=["Same ELD diagnosis as P1297"],
                  pids=[0x0C, PID_BATT]),
    "P1300": dict(sev=3, drive="Drive gently and fix soon — misfires kill "
                  "catalytic converters.",
                  causes=["Plugs/wires/cap/rotor", "Vacuum leak",
                          "Low fuel pressure"],
                  check=["Tune-up parts first; then watch fuel trims"],
                  pids=_MISFIRE_PIDS),
    "P1336": dict(sev=3, drive="May stall; usually distributor-related.",
                  causes=["CKF sensor (in distributor)", "Wiring"],
                  check=["Inspect distributor connectors; a reman "
                         "distributor fixes most of these codes"],
                  pids=[0x0C]),
    "P1337": dict(sev=3, drive="May stall or no-start.",
                  causes=["CKF sensor no signal"],
                  check=["Same distributor diagnosis as P1336"],
                  pids=[0x0C]),
    "P1359": dict(sev=3, drive="May stall; check connectors before parts.",
                  causes=["Distributor connector loose/disconnected"],
                  check=["Re-seat both distributor connectors"],
                  pids=[0x0C]),
    "P1361": dict(sev=3, drive="Intermittent stall risk.",
                  causes=["TDC sensor intermittent (distributor)"],
                  check=["Distributor connectors, then the distributor "
                         "itself"], pids=[0x0C]),
    "P1362": dict(sev=3, drive="Often a crank-no-start when active.",
                  causes=["TDC sensor no signal (distributor)"],
                  check=["Distributor connectors, then the distributor"],
                  pids=[0x0C]),
    "P1381": dict(sev=3, drive="Intermittent stall risk.",
                  causes=["CYP sensor intermittent (distributor)"],
                  check=["Distributor connectors, then the distributor"],
                  pids=[0x0C]),
    "P1382": dict(sev=3, drive="May stall or no-start.",
                  causes=["CYP sensor no signal (distributor)"],
                  check=["Distributor connectors, then the distributor"],
                  pids=[0x0C]),
    "P1456": dict(sev=1, drive="Completely safe to drive — emissions-only.",
                  causes=["Loose/worn gas cap (check FIRST — most common)",
                          "Fuel tank pressure sensor", "Vent valve by the "
                          "tank", "Cracked tank-side EVAP hose"],
                  check=["Tighten the gas cap until it clicks; inspect its "
                         "seal", "Clear the code and drive a few days — if "
                         "it returns, the tank-side EVAP system needs a "
                         "smoke test"],
                  pids=[]),
    "P1457": dict(sev=1, drive="Completely safe to drive — emissions-only.",
                  causes=["EVAP canister vent shut valve (most common for "
                          "P1457)", "Cracked canister or hoses",
                          "Two-way valve"],
                  check=["Inspect the charcoal canister area near the fuel "
                         "tank for cracked hoses",
                         "The canister vent shut valve is the usual fix"],
                  pids=[]),
    "P1459": dict(sev=1, drive="Safe to drive.",
                  causes=["Purge flow switch", "Blocked purge line"],
                  check=["Check the purge line from canister to throttle "
                         "body for blockage"], pids=[]),
    "P1486": dict(sev=2, drive="Safe to drive.",
                  causes=["Stuck-open thermostat"],
                  check=["Replace the thermostat"], pids=_TEMP_PIDS),
    "P1491": dict(sev=1, drive="Safe to drive; emissions fault.",
                  causes=["Clogged EGR passages (the classic D16 fault)",
                          "Lazy EGR valve"],
                  check=["Clean the EGR ports in the intake manifold"],
                  pids=[0x0B, 0x0C]),
    "P1498": dict(sev=1, drive="Safe to drive.",
                  causes=["EGR valve lift sensor", "EGR wiring"],
                  check=["Re-seat the EGR valve connector"], pids=[0x0B]),
    "P1508": dict(sev=2, drive="Driveable; idle may surge or stall.",
                  causes=["Dirty/failed IAC valve", "IAC wiring"],
                  check=["Clean the IAC valve; re-seat its connector"],
                  pids=[0x0C, 0x0B]),
    "P1509": dict(sev=2, drive="Driveable; idle may surge or stall.",
                  causes=["Dirty/failed IAC valve", "IAC wiring"],
                  check=["Clean the IAC valve; re-seat its connector"],
                  pids=[0x0C, 0x0B]),
    "P1519": dict(sev=2, drive="Driveable; idle may surge or stall.",
                  causes=["IAC valve circuit"],
                  check=["Clean the IAC valve; check its connector"],
                  pids=[0x0C, 0x0B]),
    "P1607": dict(sev=3, drive="Behaviour can be unpredictable.",
                  causes=["ECM internal fault", "Bad grounds/battery "
                          "connections mimicking ECM faults"],
                  check=["Clean battery terminals and engine grounds, clear "
                         "and re-test before replacing the ECM"],
                  pids=[]),
}

# Codes that share diagnosis with a representative entry
_DTC_ALIASES = {
    "P0105": "P0106", "P0110": "P0111", "P0115": "P0116", "P0120": "P0121",
    "P0130": "P0131", "P0132": "P0131", "P0137": "P0136", "P0138": "P0136",
    "P0139": "P0136", "P0140": "P0136", "P0170": "P0171",
    "P0301": "P0300", "P0302": "P0300", "P0303": "P0300", "P0304": "P0300",
    "P0336": "P0335", "P0341": "P0340", "P0404": "P0401", "P0442": "P0455",
    "P0446": "P0443", "P0456": "P0455", "P0501": "P0500", "P0560": "P0562",
    "P0603": "P0601", "P0605": "P0601", "P1107": "P1106", "P1108": "P1106",
    "P1165": "P1164", "P1366": "P1361", "P1367": "P1362",
}


def dtc_info(code):
    """Full info dict for any code, with sensible fallbacks."""
    info = DTC_INFO.get(code) or DTC_INFO.get(_DTC_ALIASES.get(code, ""))
    out = {
        "code": code,
        "desc": describe_dtc(code),
        "severity": 2,
        "severity_name": "Moderate",
        "drive": "No drivability data for this code — if the engine runs "
                 "normally it is usually OK for short trips; diagnose soon.",
        "causes": [],
        "check": ["Look up this code in the Honda service manual"],
        "pids": [],
    }
    if info:
        out["severity"] = info["sev"]
        out["severity_name"] = SEVERITY_NAMES[info["sev"]]
        out["drive"] = info["drive"]
        out["causes"] = info["causes"]
        out["check"] = info["check"]
        out["pids"] = [p for p in info["pids"]]
    return out


# Mode 05 test IDs (O2 sensor monitoring, non-CAN)
MODE05_TIDS = {
    0x01: "Rich-to-lean threshold voltage",
    0x02: "Lean-to-rich threshold voltage",
    0x03: "Low voltage for switch time",
    0x04: "High voltage for switch time",
    0x05: "Rich-to-lean switch time",
    0x06: "Lean-to-rich switch time",
    0x07: "Minimum sensor voltage",
    0x08: "Maximum sensor voltage",
    0x09: "Time between voltage transitions",
    0x0A: "Sensor period",
}
