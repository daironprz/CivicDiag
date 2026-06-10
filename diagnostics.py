"""
Guided diagnostic presets — pick a symptom, the app watches the right
sensors and flags abnormal readings.

Each preset:
  blurb     — what this test does, in plain English
  look_for  — bullet list of what good/bad looks like
  pids      — PIDs to watch (filtered to what the car supports)
  alerts    — pid -> (low, high, message); None bound = unchecked.
              Values compared against the PID's native units (°C, km/h).
  action    — None for live watching, or "readiness" for the smog check
"""

from obd_data import PID_BATT

PRESETS = {
    "Misfire / engine shaking": dict(
        blurb="Watches RPM stability, fuel trims and the primary O2 sensor "
              "while the engine runs. Let it idle, then hold ~2500 rpm. "
              "On this engine, misfires are most often worn plugs, wires, "
              "distributor cap or rotor.",
        look_for=[
            "RPM at idle should stay within about ±50 rpm — bigger swings "
            "suggest a misfire or vacuum leak",
            "Short-term fuel trim jumping past ±10% points to a fueling "
            "cause rather than spark",
            "Primary O2 stuck low (~0.1V) = lean misfire; stuck high = rich",
            "If the shake is only under load, suspect spark (wires/cap) "
            "breaking down under cylinder pressure",
        ],
        pids=[0x0C, 0x04, 0x06, 0x07, 0x0E, 0x05, 0x14],
        alerts={0x06: (-12, 12, "Short-term trim out of range — fueling "
                                "problem likely")},
        action=None),

    "Rough / surging idle": dict(
        blurb="Watches idle speed, MAP vacuum and throttle. A warm D16 "
              "should idle near 700-800 rpm with MAP around 30-37 kPa. "
              "The usual culprits: dirty IAC valve, vacuum leak, or an air "
              "pocket in the coolant loop through the IAC.",
        look_for=[
            "Idle outside 600-950 rpm warm, or rhythmic surging = IAC/EACV "
            "valve (clean it first, it's two bolts)",
            "MAP above ~42 kPa at warm idle = vacuum leak or low compression",
            "Throttle % should sit rock-steady near 0-2% — anything else is "
            "a TPS or cable issue",
        ],
        pids=[0x0C, 0x0B, 0x11, 0x05, 0x06],
        alerts={0x0C: (600, 950, "Idle speed out of normal range"),
                0x0B: (None, 43, "Idle vacuum is weak — possible vacuum "
                                 "leak")},
        action=None),

    "Overheating / cooling system": dict(
        blurb="Tracks coolant temperature in real time. A healthy system "
              "warms steadily to 85-95°C and holds there (the fan cycles "
              "around ~93°C). Watch during idle AND driving.",
        look_for=[
            "Temp climbing past ~103°C = genuine overheating — stop the "
            "engine",
            "Temp stuck below ~75°C after 15 min = stuck-open thermostat "
            "(common, cheap fix)",
            "Rises at idle but cools when moving = radiator fan problem",
            "Rises on the highway but OK at idle = radiator flow/clogging",
        ],
        pids=[0x05, 0x0C, 0x0F],
        alerts={0x05: (72, 103, "Coolant temperature abnormal")},
        action=None),

    "Fuel trim / vacuum leak hunt": dict(
        blurb="Fuel trims are the ECU's confession about mixture problems. "
              "Read at warm idle, then at a steady 2500 rpm, and compare.",
        look_for=[
            "LTFT beyond +10% at idle that improves at 2500 rpm = vacuum "
            "leak (idle airflow is small, so a leak matters more there)",
            "High positive trim at ALL speeds = weak fuel pump, clogged "
            "filter, or dirty injectors",
            "Negative trims beyond -10% = leaking injector, high fuel "
            "pressure, or a dead O2 sensor reading rich",
            "Classic leak points on this engine: intake manifold gasket, "
            "brake booster hose, PCV hose, IAC hoses",
        ],
        pids=[0x06, 0x07, 0x0B, 0x0C, 0x14],
        alerts={0x06: (-10, 10, "Short-term trim out of range"),
                0x07: (-10, 10, "Long-term trim out of range — mixture "
                                "problem")},
        action=None),

    "O2 sensor health": dict(
        blurb="Watches both oxygen sensors with the engine fully warm. "
              "Hold ~2000 rpm for a clear picture.",
        look_for=[
            "PRIMARY (B1S1): should swing rapidly 0.1-0.9V, crossing 0.45V "
            "several times per second. Slow, lazy swings = aging sensor "
            "(causes P0133/P1163)",
            "SECONDARY (B1S2): should be comparatively steady around "
            "0.5-0.7V once warm",
            "If the secondary mirrors the primary's fast switching, the "
            "catalytic converter is losing storage capacity (P0420 next)",
        ],
        pids=[0x14, 0x15, 0x0C, 0x05, 0x06],
        alerts={},
        action=None),

    "EVAP leak (P1456 / P1457)": dict(
        blurb="EVAP leaks can't be fully tested without a smoke machine, "
              "but most '96-'00 Civic EVAP codes have cheap causes you can "
              "check yourself.",
        look_for=[
            "P1456 (tank side): tighten the gas cap until it clicks; "
            "inspect its rubber seal for cracks. This is THE most common "
            "cause",
            "P1457 (canister side): inspect the charcoal canister and its "
            "hoses near the fuel tank; the canister vent shut valve is the "
            "usual failure",
            "After fixing: clear codes, then drive normally for a few days "
            "— the EVAP monitor takes several drive cycles to re-test",
            "Fuel trims shown here should sit near 0; big swings when the "
            "purge kicks in can point at a stuck purge valve",
        ],
        pids=[0x06, 0x07, 0x0C],
        alerts={},
        action=None),

    "Smog check / readiness": dict(
        blurb="Checks whether the car would pass the OBD portion of a smog "
              "inspection: no stored codes, MIL off, and all supported "
              "readiness monitors complete.",
        look_for=[
            "All supported monitors must show Ready (California allows ONE "
            "incomplete for 1996-1999 vehicles)",
            "Monitors reset when codes are cleared or the battery is "
            "disconnected — they need several days of mixed driving to "
            "complete",
            "EVAP is the slowest monitor: it needs a cold start with a "
            "1/4-3/4 full tank, then steady driving",
        ],
        pids=[],
        alerts={},
        action="readiness"),

    "VTEC not engaging (P1259)": dict(
        blurb="Your EX's D16Y8 engages VTEC around 5600 rpm at larger "
              "throttle openings. The computer only flags VTEC faults "
              "(P1259) when engagement is attempted, so this needs a safe "
              "full-throttle pull through the rev range.",
        look_for=[
            "FIRST: check the oil level — low oil pressure is the #1 cause "
            "of P1259",
            "Watch RPM and throttle: VTEC needs >5500 rpm at substantial "
            "throttle — short-shifting never engages it",
            "If P1259 sets: clean the VTEC solenoid filter screen (under "
            "the solenoid on the back of the head, two bolts)",
            "A healthy engagement is an audible intake change near 5600 rpm",
        ],
        pids=[0x0C, 0x11, 0x0E, 0x05],
        alerts={},
        action=None),

    "Charging system / battery": dict(
        blurb="Uses the adapter's voltage reading (measured right at the "
              "OBD port) to test the battery and alternator. Test engine "
              "OFF first, then running, then running with headlights + "
              "blower + rear defrost on.",
        look_for=[
            "Engine OFF: 12.4-12.8V = healthy battery; under 12.2V = "
            "discharged or worn battery",
            "Engine RUNNING: 13.5-14.7V = alternator charging properly",
            "Running under 13.2V = weak alternator or bad connections; "
            "check/clean battery terminals and the engine ground strap",
            "Over 15.0V = failed voltage regulator — fix promptly before "
            "it cooks the battery",
            "Voltage sagging when loads switch on, with idle dipping = "
            "possible ELD (P1297/P1298) or alternator on its way out",
        ],
        pids=[PID_BATT, 0x0C],
        alerts={PID_BATT: (12.0, 15.0, "Battery/charging voltage out of "
                                       "range")},
        action=None),
}
