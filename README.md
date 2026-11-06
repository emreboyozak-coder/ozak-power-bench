# OZAK POWER — DC/DC Module Test Bench

A Python-based test system that sequentially tests isolated DC/DC converters installed in five relay-selected slots, streams measurements to a browser, and generates Excel and CSV reports.

The system coordinates a UNI-T UDP6731 power supply, a UNI-T UTL8511 electronic load, and an Arduino Uno relay selector. The interface also provides hardware-independent simulation and efficiency graphs with catalog reference values.

## Contents

- [Installation and startup](#installation-and-startup)
- [Hardware and slot layout](#hardware-and-slot-layout)
- [Interface and operating modes](#interface-and-operating-modes)
- [Module identification](#module-identification)
- [Automatic test procedure](#automatic-test-procedure)
- [Power and current limits](#power-and-current-limits)
- [Efficiency curve](#efficiency-curve)
- [Measurement and regulation calculations](#measurement-and-regulation-calculations)
- [Excel and CSV reports](#excel-and-csv-reports)
- [Calibration](#calibration)
- [Code architecture](#code-architecture)
- [API](#api)
- [Troubleshooting and current limitations](#troubleshooting-and-current-limitations)
- [Local files excluded from Git](#local-files-excluded-from-git)

## Installation and startup

### Requirements

- Python 3.10 or later; the code uses the `X | None` type annotation syntax.
- Packages in `requirements.txt`: FastAPI, Uvicorn, WebSockets, pyserial, Pydantic 2, and openpyxl.
- For hardware testing: the PSU, electronic load, Arduino, and serial/USB connections.
- A modern browser. There is no separate Node.js build step.

Open PowerShell in the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Web interface: **http://localhost:8000**

If the packages are already installed for your Python interpreter, use `python main.py` or `run.bat`. The batch file uses the `python` command on PATH. When using a virtual environment, activate it first or use the explicit interpreter path shown above.

Stop the server with `Ctrl+C` in its terminal. If a test is energized, use **Emergency Stop** in the interface first. The server runs with `reload=False`: Python changes require a restart, while HTML/JavaScript changes generally require a browser refresh with `Ctrl+F5`.

### Configuration

Defaults in [backend/config.py](backend/config.py):

| Setting | Value | Purpose |
|---|---|---|
| `HOST` | `0.0.0.0` | Network interface to listen on |
| `PORT` | `8000` | HTTP / WebSocket port |
| `PSU_PORT` | `COM16` | UDP6731 serial port |
| `UTL_PORT` | `COM11` | UTL8511 serial port |
| `RELAY_PORT` | `COM14` | Arduino serial port |
| Baud rates | `9600` | Serial communication speeds |
| `SAMPLE_INTERVAL_SEC` | `0.250` | Delay between normal telemetry cycles |
| `PSU_TEST_CURRENT_LIMIT_A` | `12.0` | Maximum input current allowed by the software |
| `LOAD_TEST_MAX_CURRENT_A` | `30.0` | Maximum electronic-load current allowed by the software |
| `INITIAL_MODE` | `HARDWARE` | Initial operating mode |

COM assignments depend on the computer and USB connections:

```powershell
python -m serial.tools.list_ports -v
```

`/api/ports/ensure` verifies instrument identities and searches again when necessary. Runtime port selection and startup configuration are separate; update `config.py` as well when making a permanent change. The Arduino port must not be assigned to the PSU or load.

The interface loads its Tailwind styling script from an external address. Fully offline operation requires providing that resource locally too.

## Hardware and slot layout

```text
                  Arduino Uno
                  relay selector
                       |
UDP6731 PSU ---> selected DC/DC module ---> UTL8511 electronic load
     |                                         |
     +-------------- Python server ------------+
                            |
                       WebSocket
                            |
                       Web interface
```

The bench and on-screen layout use the same arrangement:

```text
     [ SLOT 5 ]          [ SLOT 4 ]

                [ SLOT 3 ]

     [ SLOT 1 ]          [ SLOT 2 ]
```

| Slot | Position | Arduino pin | Serial mask |
|---|---|---|---|
| 1 | Bottom left | D2 | `10000` |
| 2 | Bottom right | D3 | `01000` |
| 3 | Center | D4 | `00100` |
| 4 | Top right | D5 | `00010` |
| 5 | Top left | D6 | `00001` |
| All off | — | — | `00000` |

### Arduino firmware

Upload [arduino/relay_selector/relay_selector.ino](arduino/relay_selector/relay_selector.ino) to the Uno. Use the Arduino IDE or the [platformio.ini](platformio.ini) configuration.

- Communication uses 9600 baud, a five-bit mask, and a newline terminator (`\n`).
- A successful response includes the requested mask, such as `OK 00100`.
- A mask selecting more than one slot is rejected, and the relays are switched off.
- The firmware switches all relays off at startup and releases the previous relay before selecting another slot.
- `RELAY_ACTIVE_HIGH = true` is the default. Set it to `false` for an active-low relay board.
- Python disables the PSU before changing relays. The visual highlight follows the acknowledged active slot, rather than the selection list.

## Interface and operating modes

### Test mode

Uses the physical instruments. The PSU output is disabled when its connection is established. Programming a voltage does not enable the output; a separate enable command is required.

### Simulation mode

Select this mode with the **Simulation / Test** button in the top bar. `ConverterSimulator` generates virtual input, output, and loss values. Normal simulation telemetry and manual simulation controls do not read the physical PSU/load or send output commands to them.

Switching from hardware to simulation disables connected outputs and releases the selected relay. Mode changes are blocked during a test or calibration. Outputs remain off when returning to hardware mode. Simulation numbers use smooth transitions of approximately 300 ms; hardware-mode measurements are displayed without interpolated intermediate values.

Automatic hardware tests and the efficiency sweep with module identification require `HARDWARE` mode. Simulation is not physical validation of these production tests.

### Controls

The application currently uses Turkish labels. The table below includes those labels so the controls can be located in the interface.

| Control | Purpose |
|---|---|
| Slot (`YUVA`) | Selects a slot for manual power-on and single-slot testing. Changing the list does not immediately switch an energized relay. |
| Power (`GÜÇ (W)`) | Selects the 20, 50, 100, or 300 W family for START TEST / TEST SLOT. |
| Input (`GİRİŞ`) | During manual power-on, disables the load/PSU, obtains relay acknowledgement, sets the current limit, and enables **24 V**. |
| Output (`ÇIKIŞ`) | Enables/disables the electronic-load input. A nonzero current target is also needed to draw current. |
| Current slider and ± buttons | Adjust the manual constant-current (CC) load target in amperes. |
| `START TEST` | Runs identification and performance tests sequentially on all five slots. |
| Test Slot (`TEST YUVA`) | Runs the same identification and six-point procedure on the selected slot. |
| Emergency Stop (`ACİL STOP`) | Disables the PSU/load, zeros the load target, releases relays, and cancels the test. It latches a restart inhibit; a new test flow can clear the latch. |
| Calibration settings | A panel that remains collapsed until needed. |

In manual operation, the selected relay is released when both Input and Output are off. Relays controlled by a test or calibration are managed by their respective workflows.

Slot colors:

- **Cyan:** Currently under test, or relay selected with no result yet.
- **Green:** Working / successful test result.
- **Red:** Empty or nonworking slot, or a failed performance point.
- **Amber:** Inconclusive result or a full-load test that cannot be completed within bench capacity.

Colors are held in browser memory and may be cleared by a new related test or page refresh. Save the report for a permanent record. The showcase view is opened by the user and is not an automatic production test.

## Module identification

The operator specifies the power family. The software estimates the catalog model within that family using the input operating range and output voltage.

1. Disable the PSU, disable and zero the load, and select only the target relay.
2. Measure the module first at **10 V**, then at **24 V**, with a **50 mA** probe load at each point.
3. Start the module unloaded at each voltage, then program the probe current and enable the load.
4. Read back the current setting with `:CURR?` and input state with `:INP?`. A failed command or readback stops the procedure.
5. Use the median of three samples. Input-voltage tolerance is `max(1 V, 10% of the setpoint)`; the output-presence threshold is **2.5 V**. At least **25 mA** of probe current must be confirmed for operation to be verified.
6. A candidate operating at 10 V is evaluated as a 24 V nominal / 9–36 V family member. A candidate with verified 10 V input but no output, which operates at 24 V, is evaluated as a 48 V nominal / 18–72 V family member.
7. Compare output voltage against catalog values using `max(0.5 V, 5% of the catalog value)`. If there is no unique match, the high-load performance matrix is not run.

A module that does not operate at 10 V but operates at 24 V is not marked faulty solely because of the 10 V result. An unverified input, or output voltage without confirmed probe current, is treated as inconclusive.

This is not a digital identity readout. Models with the same voltage characteristics may be indistinguishable. Rated power is not independently measured; an incorrect family can produce an incorrect match. In production, the selected power rating must correspond to the installed module.

## Automatic test procedure

Once a unique catalog candidate is identified, the system records **six performance points** per slot:

| PSU input condition | Electronic-load conditions |
|---|---|
| Catalog minimum input voltage | No load + full load |
| Catalog nominal input voltage | No load + full load |
| Catalog maximum input voltage | No load + full load |

**No load:** The current target is 0 A and the electronic-load input is disabled. Both the zero setting and disabled input state are read back.

**Full load:** The target is `min(catalog Imax, catalog power / catalog output voltage)`, rounded down to 1 mA resolution. The same current is maintained at all three input voltages. If PSU/load capacity is insufficient, the point is marked `skipped`; a lower load is not reported as “100%.”

For a point to pass, the input must be verified and output voltage must be within `max(0.1 V, 5% of the catalog output voltage)` of the catalog value. Full-load current error must be within `max(5 mA, 5% of the current target)`; no-load current must not exceed 10 mA.

During testing, the normal telemetry reader is paused to avoid concurrent serial reads. Test samples are sent over WebSocket, and measurements continue during long settling waits. At the end, the PSU is disabled and relay paths are opened.

## Power and current limits

The input-power budget is **150% of the catalog output-power rating**:

```text
Pin_budget = 1.5 × Pnom
Iin_limit = min(12 A, Pin_budget / Vin_setpoint)
```

The current limit is rounded down to 1 mA resolution. For a 20 W module, the budget is 30 W:

| PSU voltage | Current limit |
|---|---|
| 10 V | 3 A |
| 24 V | 1.25 A |
| 36 V | 0.833 A |

This does not force the module to consume 30 W continuously. The PSU is programmed with a **current limit** based on the selected voltage, rather than a constant-power mode. Actual power depends on measured voltage and module/load behavior.

Manual power-on uses the catalog model selected in the top bar. Automatic testing uses the operator-provided power family and the identified model. An incorrectly high power selection cannot be conclusively detected through these electrical measurements alone.

## Efficiency curve

This section runs a power sweep separate from the six-point START TEST matrix.

1. Select the section's own **Slot** and **Module Power (W)** fields.
2. Default start/end/step values are **5 / 20 / 5 W**.
3. Run 10 V / 24 V identification on only the selected slot. The full-load matrix is not repeated at this stage.
4. Once a unique model is found, obtain nominal input voltage and limits from the catalog. Display the model and slot above the graph.
5. Default output targets are **5 → 10 → 15 → 20 W**. The end target is capped by catalog power/current capability.
6. At each step, calculate `I_target = P_target / Vout_measured` and send a CC current command. This is not continuously regulated constant-power mode; achieved output power is measured separately.
7. Allow at least 5 seconds of settling, check convergence, and collect multiple samples. Remove the samples with the lowest and highest efficiency from five samples, then average the remaining samples.
8. Stop if output voltage falls below 85% of nominal, current capability is exceeded, or measured input power exceeds the 150% budget.

The X axis shows output power and the Y axis shows efficiency. The red dashed line is the identified model's typical catalog efficiency, not a certification limit. The graph has a fixed height, while the results table scrolls independently. Download the CSV report from this section.

## Measurement and regulation calculations

### Power and efficiency

```text
Pin            = Σ(V × I) across input channels
Pout           = Vout × Iout
Efficiency (%) = 100 × Pout / Pin
Loss (W)       = max(0, Pin − Pout)
```

Normal telemetry displays efficiency when `Pin > 0.5 W` and `Iout > 50 mA`; otherwise it displays 0. Displayed efficiency is clamped to 0–100%. A 0% reading during a probe or no-load measurement does not by itself indicate a fault. The efficiency sweep calculates its own efficiency from averaged power measurements.

Thermal classes do not come from a temperature sensor; they are visual indicators based on calculated power loss.

### Load regulation

The no-load/full-load voltage difference at each input condition:

```text
ΔVload = abs(Vout_no_load − Vout_full_load)
Load regulation (%) = 100 × ΔVload / Vout_catalog_nominal
```

Three separate results are produced: one each for minimum, nominal, and maximum input voltage.

### Line regulation

The output-voltage range across the three input conditions at a fixed load:

```text
ΔVline = max(Vout_minVin, Vout_nomVin, Vout_maxVin)
         − min(Vout_minVin, Vout_nomVin, Vout_maxVin)
Line regulation (%) = 100 × ΔVline / Vout_catalog_nominal
```

Two separate results are produced: no load and full load. Percentages use catalog nominal output voltage as the denominator; ensure that definitions match when comparing against other datasheets.

If an input/load condition is not verified or a full-load point is skipped, the result remains **blank** rather than being reported as zero regulation. For applicable dual-output models, `catalog_output_span_v()` uses the total rail-to-rail voltage for matching and the reference value.

## Excel and CSV reports

### Module test: XLSX files inside a ZIP archive

When START TEST completes, the browser automatically downloads `ozak_power_module_test_results.zip`. It contains `slot_<slot>_<model>.xlsx` files:

| Worksheet | Contents |
|---|---|
| `Summary` | Time, power family, slot/model, 10/24 V measurements, six performance points, status, and reasons for skipped points |
| `Raw Samples` | Vin, Iin, Pin, Vout, Iout, Pout, efficiency samples, and verification flags for each point |
| `Regulation` | Definitions, reference voltage, three load-regulation and two line-regulation results, voltage differences, percentages, and validity |

`/api/module/export-excel` exports the latest report held in memory. A single-slot test or efficiency pre-identification can also replace it, so not every report contains five slots. Restarting the server clears the report; save production records separately.

### Efficiency sweep: CSV

`/api/sweep/export-csv` includes the model/catalog target, step, target power/current, measured power, voltage, current, efficiency, loss, and stability range. Points are held in `SweepEngine` memory.

## Calibration

The collapsed-by-default panel models slot-specific cable/PCB voltage differences at two load points.

1. Select the slot and appropriate catalog model.
2. Enter a lower current for point A and a higher current for point B.
3. Apply each point; PSU/load terminal measurements are recorded.
4. Measure Vin/Vout directly at the module pins with a multimeter and enter the values.
5. Save; the PSU/load are disabled and the relay is released. Canceling, or 3 minutes of inactivity, also shuts the outputs down.

The two-point correction model is:

```text
Vin_DUT  = Vin_PSU  − (input_offset + Iin × input_resistance)
Vout_DUT = Vout_load + (output_offset + Iout × output_resistance)
```

Profiles persist in `backend/slot_calibrations.json`, which is tracked in Git as a backup of this bench's calibration. It contains each slot's raw A/B measurements, input/output voltage offsets, equivalent cable/PCB resistances, and calibration timestamp. Do not assume these coefficients apply to a different bench; calibrate that bench separately. If the file is missing, empty profiles are used. Capture uses the selected catalog model's nominal input; the panel's 24 V description is not a fixed guarantee for models with another nominal input.

The UTL8511 connection selects local sensing (`set_remote_sense(False)`). Some “4-Wire” interface labels do not prove that remote sensing is enabled; verify the physical connection and instrument settings separately. Tare is a separate correction that subtracts a small positive residual current from the reading.

## Code architecture

```text
main.py                       Uvicorn entry point
run.bat                       Windows launcher
requirements.txt              Python dependencies
platformio.ini                Arduino Uno configuration
backend/
  server.py                   REST, test workflows/locks, XLSX/ZIP
  engine.py                   Telemetry, modes, broadcasting, calibration application
  config.py                   Ports, sampling, and upper limits
  dut_catalog.py              Model, power, voltage, current, and efficiency catalog
  math_engine.py              Telemetry schemas and calculations
  sweep_engine.py             Power-stepped sweep and CSV
  simulator.py                Virtual converter
  slot_calibration.py         Two-point calibration and persistent profiles
  drivers/base_driver.py      Serial/SCPI communication and numeric response parsing
  hal/utl8511_load.py          Active load driver and setting readback
  hal/drivers/unit_udp6731.py  Active PSU driver
  hal/relay_selector.py       Arduino commands and acknowledgement checks
  hal/base_*.py               Hardware interfaces
  hal/mock_psu.py             Alternative mock PSU
frontend/
  index.html                  Page structure and panels
  css/styles.css              Additional styles
  js/app.js                   API/WebSocket, modes, and interactions
  js/gauge.js                 Efficiency gauge
  js/trend_chart.js           Live trend / module-test display
  js/sweep_chart.js           Power–efficiency graph
  js/showcase.js              User-activated showcase
  assets/                     Logos and example screenshots
arduino/relay_selector/
  relay_selector.ino          Five-slot relay firmware
```

Alternative/legacy instrument drivers are also included. Active instances are selected in `TelemetryManager.__init__()`; the drivers are not all used simultaneously.

### Data flow

1. The FastAPI lifecycle starts the background task through `MANAGER.start()`.
2. `_telemetry_loop()` reads instruments or generates simulation data.
3. Slot calibration is applied, and `MathEngine` calculates power/efficiency.
4. `broadcast()` adds active-slot and test-state information and sends it over `/ws/telemetry`.
5. `app.js` updates measurements, slot colors, the gauge, and charts.
6. During a test, `is_sweep_active` pauses the normal loop; `acquire_and_broadcast()` publishes test samples.

The actual update interval also depends on serial query durations; a 250 ms setting does not guarantee a 4 Hz measurement rate.

## API

With the server running, **http://localhost:8000/docs** provides the interactive FastAPI schema.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status` | Mode, connections, outputs, and active slot |
| GET | `/api/ports` | Serial port list |
| POST | `/api/ports/ensure` | Instrument identification / rediscovery |
| POST | `/api/ports/configure` | Runtime port settings |
| POST | `/api/mode` | `SIMULATION` / `HARDWARE` |
| GET | `/api/dut/catalog` | Catalog and active model |
| POST | `/api/dut/select` | Model selection; blocked during testing |
| POST | `/api/psu/state` | Manual PSU / slot power control |
| POST | `/api/psu/voltage` | Voltage programming without enabling output |
| POST | `/api/load/state` | Load enable/disable |
| POST | `/api/load/current` | CC current target |
| POST | `/api/load/tare` | Current-offset correction |
| POST | `/api/module/detect` | Five-slot identification and performance testing |
| POST | `/api/module/test-slot` | Single-slot version of the same procedure |
| GET | `/api/module/export-excel` | XLSX/ZIP export of the latest report |
| POST | `/api/sweep/start` | Identification and power-stepped sweep |
| POST | `/api/sweep/stop` | Sweep cancellation/shutdown |
| GET | `/api/sweep/status` | Points, progress, and model |
| GET | `/api/sweep/export-csv` | CSV export |
| GET | `/api/telemetry/latest` | Latest telemetry frame |
| POST | `/api/emergency-stop` | Test cancellation / output and relay shutdown |
| GET | `/api/calibration/slots` | Calibration profiles |
| POST | `/api/calibration/capture` | Apply an A/B calibration point |
| POST | `/api/calibration/slot/save` | Save and shut down |
| POST | `/api/calibration/cancel` | Cancel calibration |
| WS | `/ws/telemetry` | Live measurement stream |

Efficiency sweep request body:

```json
{
  "slot": 3,
  "rated_power_w": 20,
  "start_power_w": 5,
  "end_power_w": 20,
  "step_power_w": 5,
  "dwell_time_sec": 5
}
```

Single-slot test request body:

```json
{ "slot": 3, "rated_power_w": 20 }
```

`/api/module/detect` obtains the power family from the model selected on the server. Before START TEST, the interface selects that family according to the power field.

Direct SCPI debug endpoints and additional calibration endpoints are also available. The API has no authentication, CORS is permissive, and the default `HOST` listens on all interfaces. This version is intended for a controlled bench network; it does not provide internet-facing deployment security or multi-user production authorization.

## Troubleshooting and current limitations

| Symptom | Check |
|---|---|
| Page does not open | `main.py` output, installed packages, and other processes using port 8000 |
| COM port missing | USB/adapter, driver, and `serial.tools.list_ports` output |
| COM port exists but does not respond | Instrument power, identity-to-port mapping, baud rate, and other programs using the port |
| Windows device error | Reconnect the USB device/adapter; changing the port number may not resolve it |
| Input cannot be enabled | Arduino acknowledgement, selected slot, instrument connections, test/calibration locks, or emergency-stop latch |
| Load enabled but no current | Current target, module output, wiring, and whether the module can operate at 10 V |
| Ambiguous model | Power family, actual output voltage, and multiple catalog matches |
| Blank regulation result | Missing/skipped point, unverified input, or target load not achieved |
| 300 W test cannot complete | 30 A load limit, 12 A PSU limit at low Vin, and actual instrument capacity |
| Efficiency is 0% | Probe/no-load display threshold or disabled output |
| Interface appears outdated | `Ctrl+F5`; restart the server after Python changes |

Current limitations:

- The application does not store serial numbers, operator identities, a database, or persistent test history.
- Although the catalog contains 3 W models, standard automatic selection supports 20/50/100/300 W. The 2.5 V threshold and 10/24 V identification procedure are not universal tests for every converter.
- For small or missing current readings, the PSU driver may estimate input current/power from load power. Reported efficiency may therefore not always rely on an independent input-power measurement. For metrological validation, remove this fallback or explicitly flag its use.
- Visual sensing/thermal labels do not always represent instrument settings or actual temperature.
- Regulation percentages use the documented formulas; there is no separate automatic regulation pass/fail decision against catalog regulation limits.
- NumPy is not listed in `requirements.txt`. If installed separately, optional loss-model regression can be calculated; otherwise that field remains empty.
- The repository does not contain a persistent automated test suite. A syntax check is not a hardware test:

```powershell
python -m compileall -q main.py backend
```

## Local files excluded from Git

`.gitignore` excludes caches, virtual environments, local PlatformIO tools/builds, logs, downloaded reports, and the temporary calibration-write file. `backend/slot_calibrations.json` is tracked as a backup of this bench's calibration; commit and push changes after recalibration to update the backup.

### What do the caches contain?

| Directory | Contents | Can it be regenerated? |
|---|---|---|
| `__pycache__/`, `backend/**/__pycache__/` | `.pyc` bytecode compiled from Python source modules, with separate files for different CPython versions | Yes, Python recreates it. It is not calibration data or test history. |
| `.pio/build/` | Arduino object files, firmware output, and intermediate build files | Yes, by rebuilding the firmware |
| `.platformio-core/.cache/` | PlatformIO download/resolution caches | Yes, downloaded again as needed |
| `.platformio-core/packages/` | Downloaded compilers, frameworks, and upload tools | Yes, through PlatformIO |
| `.platformio-core/platforms/` | Platform definitions and build/upload scripts | Yes, through PlatformIO |

`.platformio-core/appstate.json` contains local PlatformIO application state. The `bench-server.*.log` files are not caches: they contain runtime messages, errors, and instrument communication logs. In-memory test reports and measurement points are not written to `.pyc` files; export them separately as Excel/CSV.
