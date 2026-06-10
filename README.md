# CivicDiag

Open source under the MIT License.

OBD-II diagnostic suite for a **1999 Honda Civic EX coupe** (D16Y8) — runs on
any Windows laptop with a cheap ELM327 USB adapter. Also works on any other
1996+ OBD-II vehicle.

## What it can do

| Tab | Function |
|---|---|
| **Trouble Codes** | Read stored (Mode 03) and pending (Mode 07) DTCs with plain-English descriptions, including Honda-specific P1xxx codes (P1456, P1457, P1259, P1491…). Clear codes / reset the check-engine light. |
| **Live Data** | Real-time sensor dashboard — RPM, speed, coolant temp, MAP, timing advance, throttle, short/long fuel trims, both O2 sensors, and every other PID your ECU supports. Min/max tracking and **CSV data logging** for catching intermittent problems. |
| **Freeze Frame** | The sensor snapshot the ECU saved at the instant the check-engine light was triggered, plus which code caused it. |
| **Readiness Monitors** | Smog-check readiness status for every emissions monitor. |
| **O2 Sensor Tests** | Mode 05 on-board O2 sensor test results (threshold voltages, switch times) where the ECU supports them. |
| **Vehicle Info** | Protocol, adapter battery-voltage reading, OBD standard, supported-PID map, VIN/CAL-ID attempts. |
| **Terminal** | Raw AT / OBD command console with a full traffic log — lets you poke at anything the standard screens don't cover. |

## Hardware you need

A **USB ELM327 OBD-II adapter** (~$15-25). Recommendations:

- Best: **OBDLink SX USB** — rock-solid on ISO 9141-2, the protocol your '99 Civic uses.
- Fine: any "ELM327 USB v1.5" cable. Avoid ultra-cheap clones advertising
  "v2.1" — many have broken ISO 9141 support and won't talk to pre-2003 cars.
- Bluetooth/WiFi adapters also work if Windows assigns them a COM port, but
  USB is far more reliable.

**Driver:** most cables use a CH340, CP2102, or FTDI USB-serial chip.
Windows 10/11 usually installs the driver automatically; if no COM port
appears in the app after plugging in, install the driver from the chip
vendor (search "CH340 driver" etc.), then click **Rescan**.

## Launching

Double-click **`CivicDiag.exe`** (in the `dist` folder, or the **CivicDiag**
shortcut on the Desktop). It's a fully standalone single-file app — no
Python or console window needed — and you can copy the .exe anywhere
(USB stick, another laptop, etc.).

To rebuild the .exe after changing the code:
`python -m PyInstaller --onefile --windowed --name CivicDiag --icon civicdiag.ico main.py`

(`run.bat` still works as a fallback launcher if you have Python installed.)

## Using it on the Civic

1. The OBD port is **under the dash on the driver's side**, above the pedals
   (behind a small panel on some trims).
2. Plug the adapter into the car, the USB end into the laptop.
3. Turn the ignition to **ON (position II)** — engine running or off both work.
4. Pick the COM port, click **Connect**. The first connect takes ~10 seconds:
   ISO 9141-2 uses a slow 5-baud handshake. That's normal.

### Speed expectations
ISO 9141-2 runs at 10.4 kbit/s, so live data manages roughly **5–8 sensor
readings per second total**. Watching 4–6 parameters gives a snappy display;
selecting everything slows the refresh. Use **Select PIDs…** to choose.

### Reading tips for this car
- **P1456 / P1457** (EVAP leaks) are the classic '96–'00 Civic codes — check
  the gas cap and the canister vent valve by the fuel tank.
- **P0401 / P1491** — clogged EGR passages in the intake manifold, a known
  D16 issue; the fix is cleaning the EGR ports.
- **P1259** is the VTEC pressure-switch/solenoid code (EX has VTEC) — usually
  a dirty solenoid screen or low oil.
- Fuel trims (STFT/LTFT) beyond about ±10% point to vacuum leaks (lean,
  positive) or fuel-delivery/O2 issues (rich, negative).
- Mode 05/09 support is spotty on a 1999 ECU — "not supported" results there
  are normal, not a fault.

## What OBD-II can't reach on a '99 Civic (honest limits)

The OBD-II port only exposes the **engine/transmission computer (ECM/PCM)**.
On this generation:

- **ABS codes**: read via blink codes — jumper the 2-pin **service check
  connector** (blue, behind the passenger-side kick panel), turn ignition ON,
  and count the ABS light flashes (long = tens, short = ones).
- **SRS/airbag codes**: same connector; count SRS light flashes. **Do not
  probe SRS wiring with a test light.**
- Honda's dealer HDS tool of that era used the same OBD-II data for the
  engine — for the powertrain, this app sees what the dealer saw. The extra
  dealer functionality was for body/chassis modules that simply aren't on
  this car's diagnostic bus.

## Safety

- Never clear codes before noting them and the freeze frame — that evidence
  is gone once cleared, and clearing resets all smog-readiness monitors.
- If you drive while logging data, have a passenger watch the laptop.
