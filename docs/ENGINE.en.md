# Engine blueprint: an "Unreal Engine" for wind-powered walking mechanisms

> This document answers one question: **if this project is to grow into an engine (runtime + editor + content pipeline + plugins + cloud services), which things, if we do not settle them now, will we certainly have to redo later?**
> Method: map the subsystems of Unreal Engine (UE) one by one onto our domain, pick out the **one-way doors** (decisions that are expensive to get wrong), and mark the three categories **decide now, decide later, do not do**.
> Companions: the decision records are in [adr/](adr/) (0001–0008 were accepted on 2026-10-06, 0009–0010 were accepted after that); the task cards are in [ACTIONS.md](ACTIONS.md); the product shape is in [VISION.md](VISION.en.md); the platform phases are in [PLATFORM.md](PLATFORM.en.md).

## 0. Positioning: like UE, but not UE

**What we borrow from UE is the architecture, not the feature list.** The value of UE is: a headless **runtime**, with an **editor** sitting on top of it, and in between an **asset pipeline**, **undo/redo**, a **reflective property system**, **plugin modules**, a **derived data cache**, **packaging**, and **profiling tools**. These are what let content, tools and the runtime evolve independently without breaking each other.

| What we borrow | What we **do not** borrow |
|---|---|
| Assets and references, property system, transactions (undo), plugins, caching, packaging, profiling tools, "play in the editor" (PIE), live data ingest (Live Link) | Photorealistic rendering (PBR, ray tracing), skeletal animation, gameplay frameworks, audio, multiplayer, store payments, console certification |

Our "graphics quality" is **physical fidelity and reproducibility**, not pixels.

One-sentence definition: **Beest Engine** (working name) = a headless "design → simulate → manufacture → measure" runtime, plus an editor that uses it as its back end, plus a set of interfaces that people, algorithms and AI agents can use on equal terms.

---

## 1. UE concept → our counterpart

| UE's thing | What it solves | Our counterpart | Current state | When to decide |
|---|---|---|---|---|
| **Asset / GUID / references** | Content pointing at other content in a stable way | Designs, scenarios, runs, measurements, calibration results and export packages are all assets with stable IDs | **Referenced by name** (`design_name`) | **Now** (ADR-0001) |
| **Content Browser** | Browsing, searching, thumbnails | An asset browser; designs and runs generate thumbnails automatically (render one frame) | None | Later |
| **Level / World** | A scene = a set of actors | **World**: terrain, wind field, atmosphere, gravity + a number of **entities** (walker instances, obstacles, wind sources) | Scene = a single walker + terrain | **Now** (ADR-0005) |
| **Actor + Component / ECS** | Composable objects; huge numbers of instances (Mass Entity) | A walker = entity + components (links, drive, sail, body, sensors, pneumatic brain); **herds** depend on it | The simulator can only build one torso | **Now** (data model); the herd implementation comes later |
| **Details Panel / UPROPERTY (reflection)** | Declare a property once and get an editing UI, serialisation and a scripting interface for free | **Property system**: every node type declares its properties (with units, ranges, documentation); forms, API validation, MCP tool schemas and documentation are generated automatically | The UI is hand-written one by one | **Now** (ADR-0007) |
| **Transaction / Undo** | Every modification is undoable and recordable | **Edit algebra + operation log** (VISION §3.2) | None | **Now** (ADR-0003) |
| **Blueprint (visual scripting)** | Non-programmers define behaviour | **Experiment graph**: wire up "design → sweep → simulate → analyse → report" with nodes; plus a script API for agents | None (there is a sweep interface) | Mid-term |
| **Chaos / PhysX (physics backend)** | Replaceable physics | A **PhysicsBackend interface**; MuJoCo is the first implementation; Chrono (ground mechanics) and our own aerodynamics / pneumatic circuits can come later | Calls MuJoCo directly | **Now** (the interface, ADR-0005) |
| **Play In Editor (PIE)** | Run, pause and pop out the controls right inside the editor | **Simulate In the Editor (SIE)**: pause → inspect → change a parameter → continue from this frame / fork (L3 in VISION §2) | None | Mid-term, but **the state-snapshot interface must be reserved now** |
| **Replay System** | Record the inputs and replay them, saving space | **Input-log replay** (design hash + scenario hash + seed + engine version) and **state recording** coexist | Only state recording | **Now** (ADR-0004) |
| **Sequencer** | Cameras, cutscenes, animated rendering | **Reports and cameras**: camera paths, annotated replays, one-click export to mp4/gif/image, **automatically generated publishable reports** (your blog needs exactly this) | Manual | Mid-term |
| **Niagara (effects)** | Visualising particles and fields | **Field visualisation**: wind streamlines, contact-force arrows, stress heat maps | None | Mid-term (L1 in VISION §2) |
| **Live Link** | Pouring external device data into the editor in real time | **Real-time test-rig ingest**: encoders, current and wind speed shown live and overlaid on the simulation (digital twin) | Only offline CSV import | Mid-term (the device abstraction has to be thought through now) |
| **Derived Data Cache** | Expensive derived data is computed only once | **Content-addressed compute cache**: key = design hash + scenario hash + backend version + code version | None (everything is recomputed) | **Now** (ADR-0004) |
| **Cooking / Packaging** | Packaging a project into a shippable bundle | **Export**: print pack, reproduction pack (design + scenario + data + container), standalone HTML viewer (with the replay embedded) | Only the print pack | Mid-term |
| **Plugins / Modules + API versioning** | Third-party extension without forking | **Extension points**: node types, physics backends, terrain, wind, metrics, optimisers, importers, exporters, panels, MCP tools; a **versioned extension API** | Python registry (simulation side only) | **Now** (the list + the version number, ADR-0007) |
| **Unreal Insights (performance analysis)** | Seeing where each frame's time goes | **Simulation profiler**: step time, solver iterations, contact count, constraint violation, invariants panel (energy, conserved quantities) | Scattered metrics | Mid-term |
| **Automation / Gauntlet (automated testing)** | Large-scale regression | **Benchmark and regression library**: golden runs, numerical regression, visual regression, property tests of edit operations | Unit tests + a few slow tests | Continuous |
| **Source control integration** | Collaboration | Project = folder = git repository; a format that is **text, diffable and stably key-sorted** | Partial (JSON) | **Now** (ADR-0008) |
| **Marketplace / Fab** | Sharing assets | **Commons**: design registry, genealogy, leaderboards with measured results (VISION §4) | None | Late |
| **Datasmith (import)** | Importing from other software | **Importers**: STL/CAD, video, CSV, third-party mechanism data sets | Test-rig CSV | Later |
| **Localisation** | Multiple languages | **i18n**: Chinese and English message catalogues | **Chinese hard-coded in the interface** (11 files) | **Now** (ADR-0008) |

---

## 2. The 14 one-way doors: things that will certainly have to be redone if they are not settled now

> The criterion: **wrong means you have to migrate existing data, or you have to change the interfaces of many modules.** I suggest settling all of these before writing more features (each decision record has the options, the recommendation and the consequences).

| # | Decision | Why it is a one-way door | Recommendation | ADR |
|---|---|---|---|---|
| 1 | **Asset identity and references**: name or stable ID | All the files reference each other; changing it means migrating all the data | Stable ID (ULID/UUIDv7), with the name used for display only; immutable artefacts additionally get a content hash | 0001 |
| 2 | **Units and coordinate conventions** | We have already stepped on this: N/m vs 1/s², mm vs m, the sign of the crank angle | SI everywhere at the engine boundary; unit suffixes on field names; write a **coordinate-system and symbol convention** document and pin it with tests | 0002 |
| 3 | **The source of truth of a design: state or an operation log** | Decides how undo, genealogy, agents and merging are done | The operation log is the truth, snapshots are a cache; operations are typed, reversible, and carry an actor and a reason | 0003 |
| 4 | **Determinism, state snapshots, the reproducibility key** | Decides PIE, forking, caching and the reproduction pack | The simulation interface has `reset(seed)`, `snapshot()`, `restore()`; every run records (design hash, scenario hash, backend version, platform) | 0004 |
| 5 | **The world and entity model** | Right now only one torso can be built; herds, wind sources and sensors do not fit in | World + Entity + Component; a single walker is just N=1 | 0005 |
| 6 | **The physics backend boundary** | The places that depend on MuJoCo directly will keep multiplying | A `PhysicsBackend` protocol + one set of **backend contract tests** | 0005 |
| 7 | **Data formats for time series and geometry** | It is npz today; large runs, streaming and cross-language use will hurt | Telemetry in Arrow/Parquet, geometry and scenarios in glTF, metadata in JSON; npz stays as a legacy-format importer | 0006 |
| 8 | **The property system (declare once, generate everywhere)** | Otherwise every new node means hand-writing a form, validation, tools and documentation | JSON Schema + UI annotations (units, ranges, groups, documentation); **the forms, the API, the MCP tools and the documentation are all generated from it** | 0007 |
| 9 | **Extension points and the extension API version** | Both third-party plugins and our own depend on it | Enumerate the extension points; the plugin manifest carries `api_version`; **no extension may bypass the operating system to change a design** | 0007 |
| 10 | **The provenance DAG and the content-addressed cache** | Decides whether "where did this number come from" can be answered with one click | Every artefact = a node (ID + input hashes); an edge = derived from; the cache key = the input hash | 0004 |
| 11 | **The project and file format** | Decides collaboration, version control and migration | Project = folder + `project.json`; assets are text JSON with stably sorted keys; the database is only an index/cache | 0008 |
| 12 | **i18n** | Every additional screen adds another round of rework | Message catalogues (zh/en); every interface string goes through a key | 0008 |
| 13 | **The single source of truth for kinematics** | TS and Python each have a solver / gait metrics, kept in line by contract tests; at scale they will drift apart | **Keep the two implementations for now + one shared contract corpus**; define a "when to switch" trigger line (see §4) | 0009 |
| 14 | **The asynchronous and streaming protocol** | Real-time simulation, test-rig livestreaming and agents all need it | A typed event stream (WebSocket); a session model (`step/pause/set/fork`); jobs are upgraded from "single" to a **DAG** | 0004 |

> Everything else (the rendering framework, front-end state management, the charting library, the specific optimisation library) is a **two-way door**: if you get it wrong you can just swap it out, so it is not in this table.

---

## 3. Target architecture

```
┌───────────────────────────────────────────── Agents / scripts / CLI (same API as the editor) ──────────────────────────────────────────────┐
│                                                                                                                                            │
│  Editor (client)                                                    Services (server, local or remote)                                     │
│  ├ Viewport (3D + overlays + gizmos)                                ├ Job Graph (DAG scheduling, caching, retry, GPU tags)                 │
│  ├ Asset Browser / Outliner / Details (property system)             ├ Simulation Sessions (realtime/batch, snapshot and fork)              │
│  ├ Timeline / Sequencer / Report                                    ├ Provenance + Cache (content-addressed)                               │
│  ├ Experiment Graph (experiment graph)                              ├ Live Link (test-rig device ingest)                                   │
│  └ Profiler / Invariants                                            └ MCP tool surface (auto-generated from ops and properties)            │
│                                                                                                                                            │
├────────────────────────────────────────────── Engine Runtime (headless, Python/TS, library) ───────────────────────────────────────────────┤
│  Edit Algebra + Op Log  │  Design IR (graph)  │  Kinematics/Assur solver  │  Fab planning  │  Optimizers  │  Calibration                   │
│  World/Entity model  │  PhysicsBackend interface ──► MuJoCo  │  (Chrono│aero│…)  │  Telemetry (Arrow/Parquet)                              │
├───────────────────────────────────────────────── Content (project folder, text, git-able) ─────────────────────────────────────────────────┤
│  project.json │ assets/ (designs, scenarios, worlds, graphs)│ runs/ (content-addressed)│ data/ (measurements)│ derived/ (cache, not in git)│
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                 ▲ Plugins (extension points with api_version: nodes, backends, terrain, wind, metrics, optimizers, import/export, panels, tools)
```

**Two hard rules**
1. **Anything the editor can do is one API call** (equivalent at the command line). Agents, scripts, CI and people all go down the same road.
2. **Every action that changes a design must be an operation** (written to the log, undoable). The genetic algorithm, agents, plugins and the editor are no exceptions.

---

## 4. The subsystems (short description + decision points)

### 4.1 Assets and projects
- Asset types: `Design`, `Module` (reusable leg/crankshaft and so on), `Scenario`/`World`, `ExperimentGraph`, `Run`, `Measurement`, `Profile`, `Report`.
- A reference = `{id, (optional) version | hash}`; names, tags and thumbnails are only metadata.
- Project folder: text JSON, **stably key-sorted**, one top-level item per line (diff friendly); large binaries (Parquet, meshes) go through LFS or a content-addressed directory; `derived/` is not committed.
- **Migration**: every asset carries `schema_version`, and a migration is an explicit function + a round-trip test (a first version exists).

### 4.2 The property system (our UPROPERTY)
A single declaration gives at once: the editing form, the validation, the serialisation, the MCP tool schema and the documentation. The declaration contains: the type, the **unit**, the range, the default value, the group, `assumption` (the "guessed value" marker), `calibratable` (can be calibrated) and `affects` (which derived data it affects → cache invalidation).
This is **the biggest lever**: adding a new node type (say a "spring") means writing the declaration once, and everything else is automatic.

### 4.3 Editing and undo
An operation = `{id, type, args, actor{kind,id}, reason, timestamp, inverse}`. Linear history + branches; a snapshot every N operations; before merging, do a "rebase"; for concurrent work by several people or agents, upgrade to a CRDT later. Property tests: `apply(op); undo()` is always identical to the original design; `replay(log)` always yields the same design.

### 4.4 World, entities and simulation
- **World** is an asset: terrain (height map / parametric), ground surface (friction / hardness / sand), atmosphere (density, wind field over time), gravity.
- **Entity** = a bag of components: `Linkage`, `Drive(sail|motor)`, `Body`, `Sensor`, `Brain` (further out), `Marker` (video tracking).
- **PhysicsBackend protocol**: `build(world) → handle`, `step(n)`, `snapshot()/restore()`, `contacts()/forces()/energies()`, `set_param(path, value)`; **contract tests**: energy conservation, mirror symmetry, invariance under unit scaling, known analytic solutions (simple pendulum, inclined-plane slider).
- **Sessions**: `reset(seed)`, `step`, `pause`, `fork(from_frame)`, `set(param)`; they emit an event stream (footfall, slip, blocked, stalled).
- **The determinism promise must be written down clearly**: the same (design hash, world hash, backend version, platform) gives results that agree within a numerical tolerance; **bit-for-bit agreement across CPUs is not guaranteed**, and we do not pretend otherwise.

### 4.5 Compute and caching
- Jobs are upgraded from single to a **DAG** (a sweep = a batch of parallel nodes + a summary node); resource tags (CPU/GPU); retry, cancel, budget.
- An **ask/tell interface** for the optimisers (the optimiser asks for a batch of candidates, the engine evaluates them and answers), so that swapping CMA-ES, BO or QD does not require changing the engine.
- The cache key = the input hash; a hit is reused directly, and **invalidation is driven by the property system's `affects`**.

### 4.6 Data
- Telemetry (time series, contact forces, energy terms): **Arrow/Parquet**, with a schema, appendable in a stream, readable column by column (a replay only reads the layers it needs).
- Geometry and scenarios: **glTF** (a replay can also be stored as a glTF animation and opened in any viewer).
- Small metadata: JSON. npz is kept as a **legacy-format importer**.

### 4.7 The editor
- **Viewport**: a renderer abstraction (three.js today); an overlay system; picking, gizmos, selection sets; **headless rendering** (for agents and reports: the server produces the images and videos).
- **PIE (simulate in the editor)**: pause → inspect → change a parameter (hot update) → continue or fork.
- **Timeline/Sequencer**: event tracks, footfall diagrams, camera paths, annotations, one-click export.
- **Experiment Graph**: node-based experiments; every node is an engine job; the whole graph can be saved, re-run and shared.

### 4.8 Extension points (plugins)
Node types, physics backends, terrain, wind, metrics, optimisers, importers, exporters, panels, MCP tools. Every extension declares `api_version`, dependencies, capabilities and permissions; **compatibility is checked at load time**. The built-in features go through the same extension points ("eating our own dog food") — this is the most effective way to stop the API from rotting.

### 4.9 Live device ingest (Live Link)
The test rig as a **device**: it declares channels (encoders, current, wind speed, …), sampling rates, units and calibration files; the editor shows them live and overlays them on the simulation; what is recorded is a `Measurement`. The device abstraction is not finished now, but **the measurement format has to match it** (it already basically does).

### 4.10 The single source of truth for kinematics (one-way door #13, discussed on its own)
Current state: the same dyad solver and gait metrics exist twice — once in TS (used by the designer in real time), once in Python (used by the server, manufacturing and simulation) — kept in line by shared contract tests.
Options: A two implementations + a contract corpus (the current state); B a single **Rust core** compiled to WASM for the browser and bound to Python; C running the Python core in the browser with Pyodide; D keeping only TS or only Python.
**Recommendation**: start with A, but turn the contract corpus (a batch of designs and the expected trajectories / metrics) into an asset of its own that every implementation must pass. **Trigger line**: if a second "the two sides disagree" incident happens, or more than 3 modules end up needing a duplicate implementation (topology editing and constraint solving are likely candidates), then evaluate B. Do not rewrite now for the sake of "tidy purity".

---

## 5. Current-state inventory: what is already aligned, what will conflict

| Aspect | Already aligned | Will conflict / has to change |
|---|---|---|
| Data contracts | `schemas/` holds Design/Measurement/Profile/Run; they carry `schema_version` | **Scenario has no JSON Schema** (pydantic is the truth); references are by name |
| Extension points | There is a registry on the simulation side (terrain, wind, drive, metrics) | Python side only; no version number; nothing on the TS side |
| Jobs | Persistent queue, cancel, restart recovery, sweeps | Not a DAG; no cache; no resource tags |
| Provenance | Run records carry the code version, the engine version and the full configuration | No input hashes; no provenance graph; cannot "ask why with one click" |
| Simulation | Headless, batchable, replayable | Directly coupled to MuJoCo; only builds a single torso; no snapshot/fork; no event stream |
| Data | npz + JSON | No schema, not streamable; a replay reads the whole file |
| Design | The solver / gait / manufacturing / simulation builder are already generic dyad chains | The viewer, the sliders, the genes and the 3D preview are hard-coded to Jansen; no operation log; no undo |
| Interface | Four tabs, a design system, 3D replay | **Chinese hard-coded in 11 files**; every panel is hand-written; no command system |
| Coordinates / units | The crank-angle convention is written down in the builder documentation | No unified document; three.js and MuJoCo each have their own axes; unit accidents have already happened |
| Testing | Unit tests + a few slow tests + a cross-validation script | No property tests of operations, no golden-run library, no visual regression, no backend contract tests |

**The good news**: the data contracts, the registry, the persistent jobs and the provenance fields are the skeleton of the engine; they already exist and only need to be "promoted", not rewritten.

---

## 6. Migration order (least rework)

> The principle: **settle the conventions and the interfaces first (almost no feature code), then replace layer by layer following the dependencies.** Every step keeps the existing features working.

| Step | Content | What it touches | Rework risk |
|---|---|---|---|
| E0 | **Settle ADR 0001–0008**, write the *Coordinate Systems and Symbol Conventions*, extract the **kinematics contract corpus** | Documentation, tests | None (it only sets rules) |
| E1 | **i18n and property-system declarations**: interface strings go through keys; first add unit/range/assumption annotations to the fields of `Design`/`Scenario` | The 11 interface files, the schemas | Low, but the earlier the better |
| E2 | **Asset IDs**: every asset gets an `id`, references become `{id}`, and a name→ID migrator is kept | Schema, API, storage | Medium (one migration, stable afterwards) |
| E3 | **Spec-driven-ness + edit algebra v0 + operation log + undo** (steps 1 and 2 of VISION §7) | Viewer, sliders, genes, 3D | Medium |
| E4 | **World/entity model + PhysicsBackend interface + snapshot/fork**: wrap MuJoCo in a backend, and let the builder accept N entities | `packages/sim` | Medium-high (but it is isolated in one package) |
| E5 | **Provenance DAG + content-addressed cache + job DAG** | `apps/api` | Medium |
| E6 | **Parquet/glTF telemetry and scenarios**; turn npz into a legacy-format importer | sim output, API, player | Medium |
| E7 | **Extension API v1**: promote the existing registry (list + version); the built-in features go through the same one | sim, core | Low |
| E8 | **MCP tool surface (auto-generated from the operations and the properties)**, PIE, Live Link, Sequencer, Profiler | Everywhere | Depends on whether the earlier steps were done right |

**If you can only do three things first**: E0 (zero code, pure conventions), E2 (asset IDs, the later you do it the more it costs) and E3 (the edit algebra, the fulcrum of the whole design).

---

## 7. Guardrails against "over-engineering"

UE is something thousands of people built over twenty years. We have to avoid two extremes: **deciding nothing and paying for it in rework**, and **doing everything first and never shipping anything**.

1. **Turn only the "one-way doors" into architecture; write the two-way doors as plain code.**
2. **For each subsystem, start with "minimal viable + a replaceable interface"**: for example the cache starts as a local folder; as long as the definition of the key is right, swapping in object storage later does not change the layers above.
3. **Eat your own dog food**: the built-in features go through the extension points; otherwise the API will definitely rot.
4. **Every new subsystem comes with a validation gate**: the energy account closes, `apply+undo=identity`, the backend contract tests… but the gates do not block merges (in the past few weeks validation caught three bugs for us).
5. **Ask "is this useful for a walking mechanism?" at any moment**: rendering, animation and multiplayer are not something we do.
6. **Stay able to run on a single machine, offline, under git**: this project is for developers and enthusiasts, not a SaaS.

## 8. Open questions
1. ~~Engine name~~ Settled: keep **Beest Engine**. (Before open-sourcing, still watch out for trademark / attribution issues with the word Strandbeest.)
2. Git LFS or a content-addressed directory for the large binaries in the project folder (Parquet, meshes)?
3. ~~The carrier of the property-system annotations~~ Settled: the `x-` extensions of JSON Schema.
4. Does real-time simulation run on the server or in the browser (WASM)? This decides the details of the "session" protocol.
5. Is the kinematics moved to a Rust core (the trigger line is in 4.10)?
6. The node language of the experiment graph: our own, or borrowing an existing workflow / node-graph library?
