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
