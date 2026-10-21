# Platform design: the whole chain from designer to 3D print

> Status: design draft (2026-10). This is the basis for everything that follows; implementation details are refined when each phase starts. **The MVP slice is implemented** (see the checklist at the top of ROADMAP).
> This is the English version of [PLATFORM.md](PLATFORM.md). A longer-term, more sci-fi product shape is described in [VISION.md](VISION.en.md).

## 1. Vision

Build an open-source **Strandbeest design and validation platform**:

> Design a wind-powered beast in the browser → evaluate its performance in many scenarios with a high-fidelity simulation → check printability and export 3D-print files → build the physical thing and measure it → calibrate the simulation with the measured data → return to the design with a more trustworthy simulation.

Three principles:

1. **The simulation must be falsifiable by the physical thing.** A simulation without measured calibration is only a hypothesis. The platform makes "measure → calibrate" a first-class citizen instead of something bolted on afterwards.
2. **One design, used in many places.** The same design document drives kinematics, evolution, simulation, manufacturing export and the interface; no component may keep its own private copy of the parameters.
3. **Fidelity is selectable, never substituted.** A fast simplified model serves interaction and screening, a high-fidelity simulation serves evaluation; both take the same input and can be compared against each other; every conclusion states which layer it came from.

## 2. Users and scenarios

| User | What they want to do | What the platform gives them |
|---|---|---|
| Learner / popular-science reader | Understand why the leg walks the way it does | Interactive demo, articles |
| Designer (the main user) | Tune a design that can actually be built and can actually walk | Designer, evolution, simulation, print export |
| Researcher | Run experiments, compare designs, reproduce results | Scenario files, batch runs, data and scripts |
| Maker | Build a small one by following along | Print files, bill of materials, assembly notes, test-rig plan |
| Contributor | Add new terrain, new drives, new metrics | Registry extension points, contract tests |

## 3. Core concepts and data contracts

The skeleton of the platform is a set of **versioned, language-agnostic data documents**. They are the only interface between the components.

| Document | What it means | Who produces it / who consumes it |
|---|---|---|
| **Design** | The beast itself: link specifications and lengths, number of legs and their phases, body, drive (sail / motor / gear ratio), materials and manufacturing parameters | Produced by the designer and by evolution; consumed by simulation, manufacturing and the interface |
| **Scenario** | The environment and settings of one simulation: terrain, wind, drive mode, solver, outputs; refers to some Design | Written by the user / the interface; consumed by the simulation |
| **Run** | The result of one simulation: the fully resolved configuration, time series, metrics, code version, random seed | Produced by the simulation; consumed by the interface and by calibration |
| **Build** | A physical object: which Design version it corresponds to, which print settings / materials were used, assembly notes | Filled in by the user |
| **Measurement** | Measured data: links a Build to its test conditions, and holds time series of torque, speed, wind speed and trajectory | Produced by the test rig; consumed by calibration and comparison |
| **Profile** (calibration result) | A parameter set fitted from measurements (e.g. PLA pin friction, contact stiffness, sail drag coefficient), with its provenance | Produced by calibration; referenced by a Scenario |

Key rules:

- **JSON Schema is the single source of truth** (`schemas/`), placed at the repository root; the TypeScript types and the pydantic models are generated from it, and both sides use the same set of example files for contract testing. This is because the core is TS while the simulation is Python, so neither side may become the "standard of truth". (The pydantic models in `packages/sim` are temporary; they are migrated in P1.)
- **Every document carries a `schema_version`**; breaking changes must ship a migration function.
- **A Run must be reproducible**: store the fully resolved configuration, the `git` commit hash, the seed and the library versions.
- **Every guessed physical parameter is a named field**, its default marked `assumption`, and it is stored together with the Run.

## 4. System architecture

```
                            ┌───────────┬───────────────────────────────┬─────────────────────────── apps/web (Svelte) ────────────────────────────┐
                            │ Designer · Evolution · Scenario editor · Results viewer · Fabrication preview · Lab notes · Community design library │
                            └───────────┬───────────────────────────────┬──────────────────────────────────────────────────────────────────────────┘
               Browser compute (fast)   │                               │ HTTP / WebSocket (slow tasks)
                 packages/core (TS)◄────┘                               ▼
          Kinematics · Evolution · Simplified dynamics     apps/api (Python FastAPI)
                                                    REST + job queue + progress push for design/scenario/run/export/measurement/calibration
                                                              │            │             │
                                              packages/sim (MuJoCo) packages/fab   packages/calib
                                              High-fidelity sim Geometry export   Parameter fitting
                                                              │            │             │
                                                              └─────── Storage (SQLite/Postgres + file/object storage)
                                                                   designs · scenarios · runs · builds · measurements · profiles

  Offline: hardware/ (test-rig plan, firmware, data-collection scripts) ──► produce Measurement files ──► upload to the api or put them in the repository
```

### 4.1 Component responsibilities

- **`schemas/`**: JSON Schema + examples + migration functions. No runtime code.
- **`packages/core` (TypeScript, exists)**: kinematics solver, gait metrics, genetic algorithm, simplified dynamics. Pure logic, runs in the browser, and is the designer's "real-time feedback layer".
- **`packages/sim` (Python + MuJoCo, S1 exists)**: builds a model from a Design + Scenario and runs it. Terrain, wind, drive and metrics go through registries. Usable as a library, as a command line, or called by the api.
- **`packages/fab` (Python, new)**: generates printable parts from a Design. CadQuery is the intended tool for parametric modelling; output is STL/3MF/STEP, plus optional laser-cut SVG/DXF; it runs printability checks (minimum wall thickness, pin clearance, build-plate size, print orientation); it generates a bill of materials and assembly notes.
- **`packages/calib` (Python, new)**: reads a Measurement together with the corresponding Scenario, fits a Profile with an optimiser (e.g. CMA-ES), and reports the fit residuals and the uncertainty.
- **`apps/api` (Python FastAPI, new)**: a thin orchestration layer. Long-running jobs (simulation, batches, export, calibration) go into a queue; status and progress are pushed to the front end over WebSocket. It contains no physics logic.
- **`apps/web` (Svelte, evolved from the existing `web-demo`)**: see 5.
- **`hardware/` (new)**: test-rig documentation and bill of materials, microcontroller firmware (torque/current, encoders, anemometer), video-tracking scripts; it produces files that conform to the Measurement contract.

### 4.2 API sketch (refined in P4)

```
POST   /designs            GET /designs/{id}      PUT /designs/{id}
POST   /scenarios          GET /scenarios/{id}
POST   /runs               {design_id, scenario_id | inline scenario}  → job
GET    /runs/{id}          status + metrics;  GET /runs/{id}/series  time series (chunked)
POST   /sweeps             parameter sweep → a set of runs
POST   /exports            {design_id, format, options} → job → file
POST   /measurements       upload measurements;  POST /calibrations  {profile_target, measurement_ids} → job
WS     /jobs/{id}/events   progress and logs
```

The job queue starts as an in-process worker pool + SQLite (enough for a single machine); swap in Redis/RQ or a Postgres-based queue when needed. Storage goes through an abstraction interface (local files → object storage later).

### 4.3 Deployment forms (one codebase, three modes)

| Mode | Composition | Suits |
|---|---|---|
| **Static** | Front end + pre-computed Run/Design files, hosted on GitHub Pages | Popular science and showcasing results, zero operations |
| **Local** | `docker compose`: web + api + worker | Designers use it themselves, data stays on their machine |
| **Hosted** | The same thing in the cloud, plus login, quotas and rate limiting | Open to the public; the highest cost and abuse risk, so it comes last |

Running MuJoCo in the browser (WebAssembly) is a fourth option besides "hosted": it needs no back-end compute, but performance and stability have to be measured before deciding.

## 5. Front-end functional areas

1. **Designer**: drag the lengths and watch the foot path (exists), the number of legs / phases, the body, the drive parameters; one-click evolution (exists, in the browser); save the design as a Design file.
2. **Simulation**: the scenario form is generated directly from the Schema; submit, watch the progress; a results viewer (body animation, torque and speed curves, contact and slip diagnostics), and side-by-side comparison of several runs.
3. **Fabrication**: 3D preview of the parts, a printability report (where is it too thin, is the clearance enough, does it exceed the build plate), download STL/3MF, bill of materials, assembly steps.
4. **Laboratory**: register a Build, upload a Measurement, overlay the measured curves on the simulated ones, and see the difference before and after calibration.
5. **Design library**: community designs live in the repository as files and are contributed through PRs; the front end reads and displays them. No account system is needed at the start.

## 6. Details of the key links

### 6.1 From high-fidelity simulation to 3D printing

This is the part of the platform that is most easily underestimated. The "ideal pin" in the simulation is, on a printed part, a **plastic pin hole with clearance, with friction, that wears out**. Therefore:

- The "manufacturing parameters" in the Design (pin diameter, mating clearance, member cross-section, material, print layer height) must enter the simulation: **joint friction, clearance and member flexibility are configurable effects of the simulation**, not something that only matters once you are manufacturing.
- The output of `fab` has to guarantee that the geometry matches the simulation: the same Design produces the parts, and hole positions are guaranteed by tests (geometry unit test: hole centre-to-centre distances agree with the design within tolerance).
- In the MVP phase, first make the export package complete and usable; **after printing offline**, hand-crank the printed part to check whether the foot path agrees with the design, and feed the conclusion back into the default values for clearance and friction. This step does not block the other work.

### 6.2 Measurement and calibration

- Two experiments on the test rig: **motor-driven without wind** (torque–angle curve, stride, slip) calibrates contact and friction; **fan plus sail** (starting wind speed, speed–wind-speed curve) calibrates the sail and the wind.
- The calibration target is a small number of **physically meaningful parameters**, not fitting everything into a black box. Keep the residuals after the fit; large residuals mean the model is missing something, not that the parameters should be tuned further.
- The calibration result is written as a Profile, which a scenario references by name, for example `profile: pla-0.4mm-printed-pin`.

### 6.3 Multi-fidelity optimisation

The evolution loop does not use the high-fidelity simulation directly (it is too slow):

1. The simplified model (`core`) runs a large-scale genetic algorithm and screens out candidates;
2. The MuJoCo simulation re-evaluates the top few;
3. The best one or two designs, calibrated against measurements, are validated on the physical thing.

The deviation between the simplified model and the high-fidelity model is itself a quantity that is monitored continuously (see section 8).

## 7. Repository layout (target)

```
schemas/            JSON Schema, examples, migrations
packages/core/      TS: kinematics, evolution, simplified dynamics         (exists)
packages/sim/       Python: MuJoCo simulation                            (S1 exists)
packages/fab/       Python: printable geometry export                    (new)
packages/calib/     Python: parameter calibration                        (new)
apps/api/           Python: FastAPI orchestration                        (new)
apps/web/           Svelte: designer and viewer                          (evolved from web-demo)
hardware/           Test rig, firmware, data collection                  (new)
docs/               This document, the roadmap, the experiment log, the research notes
```

## 8. Quality and validation strategy

- **Contract tests**: the same set of example documents is validated on both the TS and the Python side; migration functions have round-trip tests.
- **Cross-validation**: the comparison script between the simplified model and MuJoCo (a first version exists) goes into CI, with an "allowed deviation" threshold that fails the build when exceeded, so that the two cannot quietly drift apart.
- **Regression**: the key simulation metrics (stride, starting wind speed, …) are pinned by golden files plus a tolerance.
- **Geometry tests**: the hole positions, dimensions and clearances of the `fab` output agree with the design.
- **Honest records**: the conclusion, the parameters and the limitations of every experiment are written into `docs/EXPERIMENTS.md`, including negative results (there are already precedents).
- **CI**: a Node and Python matrix; slow simulation tests are separated by a marker.

## 9. Phase plan

### 9.1 Definition of the MVP: first get the whole chain working (walking skeleton)

The MVP is not "doing one link of the chain really well", but rather **giving every link of the chain a thinnest workable implementation and stringing them together end to end**:

```
Design ─► evaluate (simplified) ─► simulate (MuJoCo) ─► printability check + export (STL/BOM/assembly) ─► [offline printing, measurement]
   ▲                                                                                                          │
   └──── calibrated Profile ◄── calibration ◄── simulation comparison ◄── Measurement (upload/import) ◄───────────┘
```

- **Offline printing and measurement are not the blocker.** While there is no measured data, use **synthetic data** (generated by adding noise to a simulation with known parameters) to verify that the "import → compare → calibrate" chain itself is correct; replace it with real data when it arrives.
- The exit criterion for each link is "contract + test + one command to run it", **not** "physically accurate". Physical accuracy is deepened link by link in the later phases.
- The front end and the back end are also built thinnest first: one API offers "validate a design / submit a simulation / export a print pack", and the front end can walk the same path.

### 9.2 Phases

| Phase | Goal | Exit criterion | Mainly responsible |
|---|---|---|---|
| **P0 Foundations** (largely done) | Core library, web demo, simulation S1, documentation | Done; simulation torque has not converged yet | Done |
| **MVP: the whole chain works** | Contracts (`schemas/`), `fab` export, measurement and calibration (synthetic data), thin API, front end walks the path; one command ties it together | Starting from one Design, a single command produces: the evaluation result, the simulation result, the printability report, the STL/BOM/assembly notes; a synthetic measurement can be imported, compared and calibrated back to the known parameters | Me |
| **P1 Trustworthy simulation** | Contact-model research (stiffness, friction, foot geometry), timestep convergence | Under the default contact settings the torque no longer drifts violently with the parameters, or the "unreliable range" is explicitly recorded | Me |
| **P2 Completing the front end** | Designer, results viewer, fabrication preview, laboratory page | Results can be browsed without starting the back end; with the back end running, scenarios can be submitted and compared | Me (you may join in on the interface) |
| **P3 Deeper manufacturing** | Whole-machine frame / crankshaft, default pin and clearance values, several materials and processes | After you print offline, the results are fed back into the default clearance and friction values (does not block the other phases) | I write, you print |
| **P4 Deeper back end** | Job queue, storage, batch sweeps, `docker compose` | Scenarios can be submitted in the interface, progress watched, and several runs compared | Me / you together |
| **P5 Test rig and real data** | Test-rig plan and firmware, data-collection scripts, the first measurements | One complete "motor-driven without wind" data set, compared against the simulation | You do it, I write the tools |
| **P6 Calibration and extended simulation** | Calibration against real data; simulation S2–S4 (sail and wind, member/joint effects, sand); multi-fidelity evolution | The error of the calibrated simulation on held-out data has a quantitative conclusion | Me |
| **P7 Public release** | Hosted or in-browser simulation, documentation site, community design library, English documentation, results report | An external user can design—simulate—export a small beast without installing anything | Together |

Dependencies: after the MVP, P1/P2/P3/P4 can largely run in parallel; P5 depends on the printed parts from P3; P6 depends on P5. **Before P1 is done well, do not invest heavily in front-end or back-end work on the simulation results** — that is why the front end and the back end of the MVP are only built thinnest.

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Simulation torque is too sensitive to the contact parameters and cannot predict the real machine | P1 quantifies the sensitivity first; P5/P6 calibrate with measurements; the applicable range is stated in the conclusions |
| The clearance, friction and wear of the 3D-printed pins decide whether it works at all | P3 prints one leg first; clearance and friction are made configurable effects and enter the calibration |
| The scale effects of a small model make the conclusions impossible to extrapolate | The small model is mainly used to calibrate the model rather than to extrapolate directly; say so clearly in paper-style reports |
| The scope is too large for a single maintainer | Proceed strictly by phase and exit criterion; contracts and tests come first; the design library is contributed through PRs |
| Compute cost and abuse of the hosted mode | Static/local modes first; hosted last, with rate limiting and quotas |
| The "assumptions" in the parameters are taken for facts | Named fields + default-value marking + stored with the Run; both articles and the interface show the source |

## 11. Open source and governance (pending)

- Code: MIT (settled).
- Designs and data: CC BY 4.0 is suggested (design library), CC0 or CC BY for the measured data sets. **Waiting on your decision.**
- Contributions: `CONTRIBUTING.md` (description of the extension points, requirements for contract tests, requirements for the experiment log); the design library is contributed through PRs; the Issue templates distinguish "design request / model defect / data contribution".

## 12. Open questions

1. The licence for the design library and the data sets.
2. Whether to use JSON Schema as the single source of truth from the start (recommended), and which code-generation tool to choose.
3. The 3D rendering approach in the front end: Three.js rendering the trajectory returned by the back end (the safe choice), or MuJoCo WASM in the browser (needs to be measured).
4. The test-rig specifications for the physical validation: the exact choice of motor, sensors and fan (decided before P5).
5. The preferred printing material and process (PLA/PETG; FDM), and whether a laser-cut version is supported.
