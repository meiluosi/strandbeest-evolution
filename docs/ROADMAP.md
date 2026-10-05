# Roadmap

## MVP walking skeleton (done, thin)
- [x] `schemas/`: Design, Measurement, Profile, Run (JSON Schema, examples, TS + Python contract tests)
- [x] `packages/common`: Design model, linkage solver, gait metrics (Python port checked against core)
- [x] `packages/fab`: bars/crank/frame, layer assignment (collision-free over the crank cycle), printability checks, STL + BOM + assembly notes + zip
- [x] `packages/sim`: Design → scenario (printed-bar mass from material), small-walker settings
- [x] `packages/calib`: Measurement import, compare, fit, Profile; recovery tested on synthetic data
- [x] `apps/api`: validate / evaluate / export / run jobs / series; `strandbeest-pipeline` one-command CLI
- [x] `apps/web-demo`: Fabricate panel (evaluate, printability + download, simulate) wired to the API
- [x] Fab depth: gripping crank arms + phase jig, spacers/washers computed per axle, standoffs, motor bracket and shaft coupler (N20-class motor assumed), more checks
- [x] Front end: four tabs (design, fabrication, simulation, lab), design save/load/import/export, run history with overlay, part outlines, measurement import (CSV/JSON), measured-vs-simulated comparison, calibration from the UI; torque reported as a range
- [x] P4: SQLite job queue (persistent, progress, cancel, restart recovery), run index, parameter sweeps (grid up to 60 points, linked paths), STL endpoint, 3D assembly/part preview (three.js), UI refresh with design system, `docker compose` (see docs/DEPLOY.md)
- [x] P5 tooling: `hardware/` (rig design, calibration procedures, experiments E0–E4, lab notebook), ESP32 firmware (logic host-tested; Arduino glue NOT compiled or run on hardware), `packages/rig` (raw CSV → Measurement with quality report, ArUco video tracking, torque calibration, serial logger, virtual rig), `/rig/convert` API and Lab-tab import
- [ ] First real measurements (needs a printed walker and the rig)
- [ ] Known thin spots: no auth; geometry for the motor/coupler is an unverified assumption until printed; torque is a range (EXPERIMENTS §8)

> Platform-level plan (phases P0–P7 with exit criteria): [PLATFORM.md §9](PLATFORM.md). The milestones below (M0–M5) are the research track and feed into those phases.

| phase | goal | status |
|---|---|---|
| P0 foundations | core, demo, sim S1, docs | mostly done |
| MVP walking skeleton | schemas, fab export, thin API, front end, calibration on synthetic data, one-command pipeline | **done (thin)**, see below |
| P1 trustworthy sim | contact study, timestep convergence | **done**: findings in EXPERIMENTS §8; torque level remains model-dependent |
| P2 front end + P3 fab depth | tabs, history, lab, outlines; crank arms, jig, spacers, motor bracket, coupler | **done (first version)**; P3 print feedback pending |
| P4 local backend deepening | persistent job queue, cancel, sweeps, docker compose | **done (first version)**, see docs/DEPLOY.md |
| P5 test rig + first data | hardware/, measurement tooling | **tooling done (first draft, untested on hardware)**; real data **pending your build** |
| P2 static viewer + design save/load | run viewer and designer without a backend | |
| P3 fab MVP | printable single leg, you print it | |
| P4 local backend | FastAPI + jobs + storage | |
| P5 test rig + first data | measurements | |
| P6 calibration + extended sim | calib, S2–S4, multi-fidelity evolution | |
| P7 public release | hosted/WASM, docs site, design library | |

## M0 — Scaffold
- [x] pnpm workspace, TypeScript, Biome, Vitest
- [x] `core/geometry`: circle intersection

## M1 — Kinematics (core)
- [x] Declarative linkage spec (joints, rigid triangles, crank) so topology is data, not code
- [x] Jansen linkage with the standard 13 lengths; verify foot path is D-shaped (flat stroke) via test
- [x] Assemblability check across full crank rotation; detect branch flips
- [x] Foot-trajectory metrics: stride length, lift height, flatness of ground stroke, duty cycle
- [x] Multi-leg phase offsets (Strandbeest uses many legs on shared crankshaft)

## M2 — Evolution (core)
- [x] Seeded RNG, genome = link lengths, GA (selection, crossover, mutation)
- [x] Fitness v1: reproduce Jansen's "holy numbers" style objective (flat stroke, high lift)
- [x] Experiment runner + reproducible result files (JSON)
- [x] Fitness v2: step height (`fitnessHighStep`)
- [x] Variants: speed and efficiency proxies (`fitnessSpeed`, `fitnessEfficiencyProxy`), match-a-path (`fitnessMatchPath`)
- [ ] Systematic comparison of objectives against the original over many seeds (see docs/EXPERIMENTS.md for the first study)

## Notes
- Fitness thresholds (min lift 15% of width, duty credited up to 0.6) are our design choices to block degenerate GA solutions (sliding foot, foot swinging through the body); they are not Jansen's.
- Run the demo: `pnpm --filter @strandbeest/web-demo dev`.

## M3 — Web demo
- [x] Canvas viewer: drag lengths, see foot path live
- [x] In-browser GA with progress/visualization (Web Worker)
- [ ] Embed as Svelte component in the blog

## M4 — Dynamics
- [x] Quasi-static walking model: torque from energy conservation (slope, drag, body lift), stability and slip-spread checks, tested for energy balance
- [x] Wind-driven torque model (geared drag sail → crank), start wind and steady speed
- [x] Wind panel in the web demo
- [ ] Ground contact with friction limits and slip (currently only a slip-spread indicator)
- [ ] Soft/sand-like ground
- [x] Inertia (reduced-order 1-DOF time-domain model: start-up, ripple, coasting; no impact loss, no slip) — see docs/EXPERIMENTS.md §5
- [x] Torque-aware objective (`fitnessWindSpeed`) — see docs/EXPERIMENTS.md §4
- [ ] Optional: pneumatic storage model (bottle + piston pump)

## M4b — MuJoCo simulator (packages/sim, design in docs/SIM-DESIGN.md)
- [x] S1: planar builder, motor drive, flat/slope, metrics, CLI, cross-check script
- [x] Contact-model study and timestep convergence (EXPERIMENTS §8); torque level stays dependent on friction regularisation, report as a range until measured
- [ ] Explain why leg mass raises mean torque; fix the small walker's stiff-loop instability; torque range reporting in the API/UI
- [ ] S2 sail + wind; S3 leg mass/joint friction sweeps; S4 sand (RFT); S5 wind on tubes/body; S6 flexibility, 3D (see SIM-DESIGN.md)
- [ ] Measured data from a small physical model

## M5 — Writing & outreach (blog repo)
- [x] Series drafted (zh): evolution history / leg geometry / re-evolving it (blog drafts, `draft: true`)
- [x] English versions drafted
- [x] Bilingual README, demo GIFs
- [x] Verify the evolution timeline against strandbeest.com (done except Pregluton, whose page was empty)
- [ ] Publish: enable GitHub Pages (workflow `pages.yml` is manual), npm publish, flip `draft` to false
