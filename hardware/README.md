# Test rig: measuring a real walker

Everything here exists to answer one question: **how well does the simulator describe a printed walker, and which parameters make it do so?** The simulator has a few physical parameters it cannot know (contact stiffness, friction, joint friction and clearance, the effect of leg mass; see `docs/EXPERIMENTS.md` §9). The rig measures the walker so those can be fitted instead of guessed.

**Status:** the software chain (raw log → Measurement → comparison → calibration) is tested on a *virtual* rig that replays simulator runs. The firmware's logic (`hardware/firmware/lib/rigcore`) is unit-tested on the host. **Nothing here has touched real hardware yet:** the Arduino glue (`src/main.cpp`), the wiring tables and the part suggestions are untested, and the first real build will find things to fix. Treat this as a careful first draft.

## What is measured

| quantity | how | used for |
|---|---|---|
| crank angle ψ(t) | encoder on the motor shaft (counts → radians) | everything; defines the gait phase |
| crank torque τ(t) | motor current × torque constant, or a load cell on a torque arm | contact stiffness, friction, dissipation |
| body position x(t) | side-view video of an ArUco marker on the body | stride per revolution, slip |
| wind speed (fan tests) | cup anemometer pulses, or readings from a handheld anemometer | sail model |

## The rig

```
 [phone/webcam, side view, fixed]                      ArUco marker on the body
            │                                                   │
   walker on a smooth, flat, level surface ── crankshaft ── coupler ── geared DC motor + encoder
                                                                        │
 USB ── ESP32 ──┬── motor driver (PWM, direction)                       │ (current sensor in the motor supply line)
                ├── encoder A/B                                         │
                ├── INA219 current sensor (I²C)  ←──────────────────────┘
                ├── HX711 + load cell (optional, torque-arm method)
                └── anemometer pulse input (optional, fan tests)
```

Part *classes* (no specific models were checked; read the datasheets, especially stall current vs your supply):
- a small geared DC motor with a quadrature encoder (N20-class, 50–200:1), 6 V or 12 V;
- a dual H-bridge driver (DRV8833 / TB6612 class) that handles the motor's stall current;
- an ESP32 dev board (Arduino framework);
- an INA219-class current/voltage sensor board (I²C), placed in series with the motor supply;
- optional: an HX711 amplifier with a small bar load cell (about 0.5 kg) and a printed torque arm;
- optional: a cup anemometer with a reed switch or Hall sensor (or just a handheld anemometer, read and typed in);
- a desk or box fan with at least three speed settings, a bench power supply, a phone or webcam on a tripod (≥ 30 fps), a printed ArUco marker (DICT_4X4_50, id 7 by default, measure its printed side), a tape measure, a kitchen scale and some small weights.

Default wiring is in `hardware/firmware/src/config.h`.

## Software

```bash
./scripts/setup-python.sh && source .venv/bin/activate
pip install -e "packages/rig[dev]"                    # video + serial extras
strandbeest-rig calibration-template cal.json         # then edit it; see "Calibration" below
```

Firmware (PlatformIO): `cd hardware/firmware && pio run -t upload`. Host tests of its logic: `make -C hardware/firmware test`.

Serial protocol (115200 baud, newline-terminated commands): `ZERO` zeroes the encoder, `S <rad/s>` sets the crank speed, `START` / `STOP` run and stop the motor (the motor is also cut on overspeed). The firmware prints `# ...` comment lines and then CSV: `t_ms,enc,current_mA,load_raw,wind_pulses,pwm`.

## Calibration (do this before any experiment; write results into `cal.json` and set `"calibrated": true`)

1. **Encoder.** Turn the crank by hand exactly one revolution and read the count; compare with `counts_per_motor_rev × gear_ratio`. Fix the config if they differ. Check the sign: positive counts must mean the walking direction (`direction` in the calibration, `ENC_SIGN` in the firmware).
2. **Idle current.** Run the motor at the test speed with the legs disconnected (crank free). The mean current is `idle_current_ma`; it is subtracted so the torque excludes motor and gearbox friction.
3. **Torque constant (current method).** Fix a lever arm of known length to the crankshaft, hang known masses from it with the motor holding the shaft still, and record the current for each mass (at least 4 masses, spread over the range you will use). Put them in a CSV with columns `mass_g,current_mA` and run `strandbeest-rig torque-cal masses.csv --arm-m 0.05`. This gives `kt_nm_per_a` and a second estimate of the idle current. The fit residual tells you how linear the motor is.
4. **Load-cell method (alternative).** Mount the motor so it can rotate freely, press its torque arm on the load cell, and calibrate counts per gram with the kitchen scale weights; record `arm_m`, `counts_per_gram`, `zero_counts`.
5. **Anemometer.** Compare pulse frequency with a handheld anemometer at three fan speeds; `wind_ms_per_hz` is the slope.
6. **Camera.** Put the marker on the body, film the walker side-on, tripod fixed, camera as far away and as perpendicular as practical. Check the scale by filming a ruler in the plane of motion; the tracker's mm per pixel should agree within 2 %.

## Experiments

Each experiment says which simulator parameter it constrains. Repeat each condition at least 3 times and note the surface; a single run says little.

**E0 – Leg by hand (before any motor).** Assemble one leg flat on a table and turn the crank by hand while filming. Compare the foot path with the design's (`/evaluate`). This checks print accuracy and the clearance setting, and costs nothing. *Constrains: clearance, joint play (not yet modelled).*

**E1 – Slow motor-driven walk (the core experiment).** Walker on a smooth flat surface, no wind, crank at a constant 1–2 rad/s for at least 5 revolutions; log, film. Convert with `strandbeest-rig convert … --kind motor_no_wind --omega 2`. Compare torque curve and stride with a simulation of the same design. *Constrains: the simulator's contact stiffness (a mass-normalised parameter in 1/s², not a pad stiffness in N/m: the fitted value is a simulator setting, not a property you can look up), friction, slip dissipation.*

**E2 – Surface and speed variants.** Repeat E1 on two other surfaces (e.g. glass, paper, rubber mat) and at two other crank speeds. *Constrains: friction (surface), speed dependence (inertia, joint friction).*

**E3 – Idle and stall checks.** Log with the legs disconnected (idle) and with the motor held (stall) to bound the current-to-torque conversion. *Constrains: calibration quality of the rig itself; do this first if E1 looks odd.*

**E4 – Fan test (needs a sail).** Mount the sail, set the fan to three speeds, measure wind at the walker's position (handheld or anemometer), record start/no-start and speed. Convert with `--kind fan --wind <m/s>`. *Constrains: sail drag, start wind. The simulator's wind model is the least validated part; expect large discrepancies.*

## From log to the platform

```bash
strandbeest-rig log /dev/ttyUSB0 --out raw.csv --duration 40 --omega 2      # or use any serial logger
strandbeest-rig track video.mp4 --marker-id 7 --marker-mm 20 --out track.csv
strandbeest-rig convert raw.csv --calibration cal.json --name e1-glass-1 --design-id 0000000000YNGRWX0MDFYPZHXT --design-name jansen-small-6leg \
    --omega 2 --surface glass --track track.csv --out e1-glass-1.json
```

Or upload the raw CSV and calibration in the web UI's **Lab** tab, which runs the same conversion. The result is a Measurement with a **quality report**; read its warnings before trusting a fit (low sample rate, serial dropouts, too few revolutions, unsteady speed, wrong encoder direction, uncalibrated constants, how the video was aligned). Then compare with a simulation and calibrate in the Lab tab.

Start the video and the log together (e.g. clap, or start the motor while the camera is already filming); the converter aligns the two clocks from the start of motion and reports the uncertainty (about one video frame).

## Practice without hardware

```bash
strandbeest-rig virtual schemas/examples/design-jansen-small-6leg.json --out /tmp/virtual.csv
strandbeest-rig convert /tmp/virtual.csv --calibration cal.json --track /tmp/virtual.track.csv \
    --name virt --design-id 0000000000YNGRWX0MDFYPZHXT --design-name jansen-small-6leg --omega 2 --out /tmp/virtual.json
```
The virtual rig is generated from the simulator itself, so it can test the software chain but proves nothing about the simulator.

## Safety
Moving parts, pinch points between legs and crank, motor stall currents (use a current-limited supply), fan blades, and printed parts that can snap under load. Keep fingers clear while the motor is powered, use a supply with a current limit, and cut power before touching the walker. The firmware cuts the motor on overspeed or on `STOP`, but it is not a safety device.

## Lab notebook
Copy `hardware/templates/lab-notebook.md` for each session and fill it in; the converter stores the calibration and raw file name with every Measurement, but things like the print settings and the surface are only as good as the notes.
