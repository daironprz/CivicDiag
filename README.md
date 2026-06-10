# CivicDiag v2.0

Open source under the MIT License.

OBD-II diagnostic suite for a **1999 Honda Civic EX coupe** (D16Y8) — runs on
any Windows laptop with a cheap ELM327 USB adapter. Also works on any other
1996+ OBD-II vehicle.

Open source under the MIT License.

**Launch:** double-click `CivicDiag.exe` (in `dist\`, or the Desktop
shortcut). It's a standalone single-file app — copy it anywhere, no Python
needed. **No adapter yet?** Pick **DEMO** in the port list to explore every
feature with a simulated Civic.

## Tabs

| Tab | Function |
|---|---|
| **Trouble Codes** | Stored + pending DTCs with severity levels, "safe to drive?" notes, common causes on this car, "check this first" steps, and a one-click jump to the related live sensors. Copy to clipboard, save reports, and a guarded clear-codes flow that makes you acknowledge what gets erased. |
| **Live Data** | Big RPM/Speed/Coolant/Throttle cards, full sensor table with min/max/avg, searchable PID picker with favorites, one-click session logging (auto-named CSV + JSON summary sidecar), event marking ("felt stumble", "revved engine"…), and a notes field. |
| **Charts** | Live multi-line graphs of your selected PIDs with abnormal ranges drawn in red. Load a saved log to zoom (wheel), pan (drag), replay (▶), or overlay a second log for before/after comparison. |
| **Guided Diagnostics** | Pick a symptom — misfire, rough idle, overheating, fuel trim/vacuum leak, O2 health, EVAP leak, smog readiness, VTEC, charging/battery — and the app watches the right sensors and flags abnormal readings automatically. |
| **Reports** | One-click **Check-Engine**, **Pre-Smog** (pass/fail verdict), **Mechanic**, and **Share-with-Mechanic** reports. Each reads fresh data, saves an auto-named HTML file, and opens it in your browser — Ctrl+P → "Save as PDF" for printing. Plus a **Before/After repair** workflow: save a baseline, wrench, compare. |
| **Freeze Frame** *(advanced)* | Sensor snapshot from the moment the check-engine light tripped. |
| **Readiness** *(advanced)* | Per-monitor smog-check readiness. |
| **O2 Tests** *(advanced)* | Mode 05 oxygen-sensor test results. |
| **Vehicle Info** *(advanced)* | Protocol, adapter battery voltage, supported PIDs, VIN attempts. |
| **Terminal** *(advanced)* | Raw AT/OBD console with ↑/↓ command history and full traffic log. |

Advanced tabs are hidden by default — enable **View → Advanced mode**.
Other View options: **Light mode** and **Large controls** (bigger buttons
for using the laptop in the car). Everything (theme, mode, favorites,
selected PIDs, save folder, last port) is remembered between runs.

Exports: session as **.txt / .json**, codes as **.csv**, reports as
**.html** (→ PDF via browser print), logs as **.csv** with a **.json**
stats sidecar, plus 📷 window screenshots. Files are auto-named like
`CivicDiag_2026-06-09_P1456.csv` and land in your save folder
(default `Documents\CivicDiag`, changeable under File).

## Hardware you need

A **USB ELM327 OBD-II adapter** (~$15-25):

- Best: **OBDLink SX USB** — rock-solid on ISO 9141-2, the protocol your '99 Civic uses.
- Fine: any "ELM327 USB v1.5" cable. Avoid clones advertising "v2.1" —
  many have broken ISO 9141 support and won't talk to pre-2003 cars.

**Driver:** most cables use a CH340, CP2102, or FTDI USB-serial chip.
If no COM port appears, install the chip vendor's driver and click Rescan.
Ports that look like an adapter are marked "✱ likely adapter". There's a
full walkthrough under **Help → Connection troubleshooting**.

## Using it on the Civic

1. OBD port is **under the dash, driver's side**, above the pedals.
2. Adapter into the car, USB into the laptop, ignition to **ON (II)**.
3. Pick the COM port → **Connect** (first handshake takes ~10 s — ISO
   9141-2 uses a slow 5-baud init; that's normal).

ISO 9141-2 manages roughly **5-8 sensor readings per second total**, so
watching 4-6 parameters gives the snappiest display.

### Known weak spots on a '96-'00 Civic
- **P1456/P1457** EVAP leaks — gas cap first, then canister vent valve.
- **P0401/P1491** — clogged EGR passages in the intake manifold.
- **P1259** — VTEC: check oil level, then clean the solenoid screen.
- **P0335/P1361/P1381** family — the distributor houses all three engine
  position sensors; one reman distributor often clears them all.
- Fuel trims beyond ±10% — vacuum leak (lean) or fuel delivery/O2 (rich);
  use the Guided preset.

## What OBD-II can't reach on this car

OBD-II exposes the **engine/transmission computer only**. ABS and SRS on a
'99 Civic report **blink codes**: jumper the 2-pin service check connector
(behind the passenger kick panel), ignition ON, count the warning-light
flashes (long = tens, short = ones). Never probe SRS wiring with a test
light. For the powertrain, this app sees what the dealer tool saw.

## Changelog

### v2.0 - June 10, 2026

- Added demo mode so the app can be explored without an OBD-II adapter.
- Added guided diagnostic presets for common Civic symptoms and smog checks.
- Added live charts, saved-log playback, and before/after log comparison.
- Added one-click live-data logging with CSV output and JSON summaries.
- Added printable HTML reports for check-engine, pre-smog, mechanic, and share-with-mechanic workflows.
- Added stronger trouble-code explanations with severity, safe-to-drive notes, common causes, and first checks.
- Added preferences for theme, advanced mode, large controls, save folder, favorite PIDs, and last port.

## Rebuilding after code changes

```
python -m PyInstaller --onefile --windowed --name CivicDiag --icon civicdiag.ico main.py
```

Tests (no car needed): `python test_decoders.py` and `python smoke_test.py`.
