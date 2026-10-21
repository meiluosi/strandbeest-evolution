# Product shape and design vision (second edition)

> This is a **design and imagination document**, not a promise. Every idea is marked with: what in the repository it builds on, what is still missing, and what the biggest risk is. The further down it goes, the more sci-fi it gets, and the more it needs real data first.
> The architectural blueprint for turning this into an "engine" and the pending architectural decisions are in [ENGINE.md](ENGINE.en.md) and [adr/](adr/).
> The literature links come from a single search; I have **not** read every paper end to end; "SOTA" here means "representative work visible in the search", not a rigorous survey.

## 0. Principles (set the rules first)

1. **Honesty is itself a feature.** The interface always shows where a number came from, how uncertain it is and whether it has been measured — instead of a pretty single value.
2. **Glass-box simulation.** The simulation is not "run it and give you a few numbers", it is a process you can walk into and inspect: every number can be broken open to see where it came from.
3. **One edit algebra.** People, genetic algorithms, LLM agents and reinforcement-learning policies all change designs through **the same typed design operations**. The editor, the optimisers, the agents and the version history therefore share one foundation.
4. **Growing, not parameter tuning.** A design has to be able to change structurally (add a dyad, swap a module) and grow different shapes in different environments.
5. **AI-native.** Every capability of the platform is "agent-ready": typed interfaces, machine-readable schemas, verifiable scores, budgets, logs. Agents are first-class users, not an add-on chat box.
6. **The data loop.** Real measurements make every layer above more honest; a conclusion without data is always labelled "within the model".
7. **Accountability.** Who (a person / an algorithm / an AI), when and why changed something is always traceable; AI-generated designs are tagged; actions that affect the real world (exporting prints, publishing) need human confirmation.

---

## 1. Inventory: where we are now (the honest version)

| Capability | Current state | Distance from the "vision" |
|---|---|---|
| Kinematics solver, gait metrics, manufacturing planning (layering, clearance, bushings), MuJoCo simulation building | **Already generic**: all of them are based on `LinkageSpec`, i.e. a "dyad chain" (each joint = the intersection of two circles) | Small |
| Designer, sliders, evolution genes, 3D assembly preview | **Hard-coded to Jansen**: the link list, the 13 parameter names and `jansenSpec(params)` are scattered across `LinkageViewer`, `LengthSliders`, `fitness`, `Viewer3D` | Medium: it has to become spec-driven |
| Simulation replay | **A recording**: it replays the recorded poses, with foot-contact colouring and synchronised curves | Large: see section 2 |
| Optimisation | A self-written small genetic algorithm (for teaching) | Large: see section 5 |
| AI | None | Large: see section 4 |
| Real data | We have the tools, not the data | The largest |

The most useful line in this inventory is the first one: **structured design is closer to us than we imagined**, because the solver, the manufacturing and the simulation have long stopped depending on Jansen's topology — only the interface and the evolution are still hard-coded.

---

## 2. The simulation is a process you can "walk into" (the glass box)

### 2.1 The problem
The 3D replay today is a **recording**: you see that it moved, but not why it moved that way. We have already seen the cost of this in this week's work: the judgement that on flat ground the mean torque is "almost entirely slip dissipation" started out as our speculation; we only verified it by writing an extra energy-accounting script. The verification result (`packages/sim/scripts/energy_account.py`, small model with a motor drive, averaged after skipping the start-up revolution): **97 % of the input work per revolution is dissipated at the contacts, 3 % in the loop closures, and the remaining 0.2 % is integration error**. This conclusion should have been shown directly in the interface, not left to a script.

### 2.2 Layered capabilities (L0 to L5)

| Layer | Content | State |
|---|---|---|
| L0 Recording | Replaying the recorded poses, the foot coloured on contact, synchronised curves | **Exists** |
| L1 Overlays | Contact-force vectors and contact points, joint reaction forces, torque flow, slip indicators (the tangential velocity of the foot), the centre-of-mass trajectory and the support polygon, the **footfall diagram** (the ground-contact / lift-off timing of each leg), the phase ring, the **energy-flow Sankey diagram** (wind/motor → crankshaft → potential/kinetic energy → contact dissipation / loop-closure dissipation) | The data is available (MuJoCo's constraint forces and velocities); it has to be recorded and drawn |
| L2 Events and causality | Automatically detecting and annotating: footfall, lift-off, slip, blocked by the terrain, loop closure opening, start-up / stalling, gusts; clicking an event on the timeline jumps to it; an automatic diagnosis of **"why did it stop?"** (rules find the evidence, an AI turns the evidence into plain language) | All of it has to be built |
| L3 Interaction | Real-time streaming simulation (the back end steps over WebSocket, or MuJoCo WASM in the browser); push it with a drag; change the wind, the friction or the slope while it runs; **pause, inspect, change a parameter, continue from this frame (fork)**; save state checkpoints for time travel; A/B side-by-side synchronised replay that highlights the differences | To be built; the feasibility of WASM has to be measured first |
| L4 Multi-scale | Whole machine ↔ single leg ↔ single pin hole: forces and stresses (beam or finite element); the "breaking its own spine" of the Suicideem era should be able to raise a warning | Far off |
| L5 Immersion | Walking into it in VR; AR overlaying the predicted foot path on your physical model | Far off |

### 2.3 Key points of the technical approach
- **Record more**: for every frame add the normal/tangential force of every foot contact, the joint reaction forces and the individual energy terms; a separate **event log** (with time, type and evidence). Data-volume budget: for the current 6-leg small model at 30 Hz × 2 seconds the JSON is about 1 MB; adding forces and energy roughly doubles it, which is acceptable; the 12-leg large model needs thinning and binary transfer.
- **API**: `GET /runs/{id}/replay?layers=forces,events,energy`; `WS /sessions` for real-time sessions (`step`, `pause`, `set(param)`, `fork`).
- **Front end**: one Inspector panel (select a foot or a joint and see its forces, power and history); timeline tracks (events, footfall diagram); overlay toggles.
- **What it does for scientific honesty**: the glass box makes the uncertainty visible. For example the mean torque depends on the numerical treatment of friction (by up to a factor of 2.4); the energy Sankey diagram will **show directly "this number is slip dissipation, so it is sensitive to the friction modelling"**, instead of making the user read the documentation.

### 2.4 Risks
- Real-time streaming simulation makes high demands on the back end's compute and latency; first do "inspectable after the run" (L1, L2), then real time (L3).
- Too many overlays turn into noise; only two or three are on by default, the rest on demand.

---

## 3. Design is structure, not parameters

### 3.1 Design IR (intermediate representation)
Upgrade the design from "13 lengths" to a **graph**:

- **Nodes**: `Ground`, `Crank`, `Link`, `Joint` (dyad joint), `Foot`, `Body`, `Sail`, `Rotor`, `Spring`; further out: `Bottle`, `Pump`, `Valve`, `Piston-Muscle`, `Water-Feeler`, `Pedometer` (Jansen's pneumatic elements).
- **Properties**: length, mass, material, manufacturing parameters, colour, notes.
- **Constraints**: assemblability (assemblable over a whole cycle, consistent branches), printability, no collisions, symmetry, degrees of freedom = 1.
- **Modules**: `Leg` is a reusable module; `array(Leg, n, phases)` generates multiple legs; the body, the sail and the crankshaft are modules too.

The existing `LinkageSpec` is a **subset** of this IR: every `JointDef` = the intersection of two circles = one RRR **dyad (Assur dyad)**. A large class of planar single-degree-of-freedom mechanisms can be built from dyad chains, so this subset is not small; but it is **not everything** (mechanisms with sliders, structures where several loops have to be solved at once, are not simple dyad chains). Saying this boundary out loud is better than pretending to be general.

### 3.2 Edit algebra
All changes are typed operations, and every operation has **precondition checks, is reversible, produces a diff and is written to the log (who / when / why)**:

```
add_dyad(centers, radii, side)     remove_joint(id)       set_param(name, value)
scale(group, factor)               mirror(group)          array_legs(n, phases)
split_link(id, at)                 insert_module(kind, at)  set_material(group, material)
attach(sail | spring | sensor, at) rename / tag / note
```

Why this is the fulcrum of the whole design:
- **The editor is a visualisation of the operations**: dragging a point = `set_param`, clicking "add dyad" = `add_dyad`.
- **The mutations and crossovers of the genetic algorithm = operation sequences**: topological mutation (adding/removing dyads) is no longer special code, and validity is caught by the solver.
- **The agent's toolset = the operation set**, and the action space of a reinforcement-learning policy is the operation set too.
- **Version control and genealogy come for free**: the operation log is a sequence of patches, and the genealogy tree (the Jansen website has a Genealogy page) is a branch diagram of the log.
- **Reproducibility**: the same initial design plus the same string of operations yields the same result.

### 3.3 The editor (for people and for agents)
Three linked views:
1. **Mechanism sketch (2D)**: drag points directly, add dyads; it shows the **degrees of freedom, the assembly range, singular-configuration warnings** and the foot path live; red = it cannot be assembled / it collides / it is not printable.
2. **Structure tree**: legs, crankshaft, body, sail; reuse and arrays.
3. **3D / manufacturing**: parts, layer stacks, assembly; this is the current fabrication page, but linked to the two views above.

On top of that: a **command palette** (people and agents share the same commands), a **history/branch/compare panel** (the genealogy tree), and a **test-rig sidebar** (pick a scenario on the spot and run it to see the effect).

### 3.4 "Growing": three meanings
1. **Evolutionary**: a population + environmental selection (quality diversity, see section 5).
2. **Developmental**: the design is generated by a **growth program** (L-systems, shape grammars, CPPN), with the environment parameters as input. The design becomes a function: `design = f(environment)` — strong wind gives a big sail and short legs, soft sand gives big feet. A "design family" file holds the tunable parameters and the adaptation rules and instantiates different individuals ("species") in different scenarios.
3. **Adaptation in use**: adjustable mechanisms (sail trim, leg length, anchoring) and pneumatic reflexes (Jansen's Cerebrum era: hose water sensors and a pedometer, using pneumatic circuits as logic). This is **morphological computation**: using the mechanism itself to do the "control".

### 3.5 Scope and risks
- Topological editing makes the search space explode; first build **validity gating** (assemblable over a whole cycle, no branch flips, degrees of freedom, printable, no collisions), so that invalid designs are rejected before they enter the simulation.
- The incremental route: (a) make the viewer / sliders / genes / 3D spec-driven (remove the hard-coding); (b) add `add_dyad`; (c) topological evolution; (d) modules and pneumatic elements.

---

## 4. AI-native

### 4.1 Three roles, plus "the model in the loop"
- **Collaborator**: change the design conversationally, explain the results, answer "why".
- **Operator (agent)**: run experiments, sweeps, optimisations and keep the records tidy by itself, through tools.
- **Analyst**: read the replays and the data, write reports with provenance.
- **The model in the loop**: surrogate models, neural calibration, generative models, policies (section 5).

### 4.2 The five conditions for being agent-ready
Every capability of the platform has to satisfy: **① typed interfaces, ② machine-readable schemas, ③ verifiable numerical scores, ④ budgets (time / compute / cost), ⑤ logs**. Our `schemas/`, the job queue and the run records already satisfy a large part of that; what is missing is wrapping them in a protocol that agents can discover and call.

### 4.3 The tool surface (MCP server)
Exposed through a standard protocol such as Model Context Protocol (MCP) (the search results say it has become the mainstream standard for LLM agents to access external tools):

| Tool family | Examples |
|---|---|
| `design.*` | All the operations of the edit algebra, `validate`, `diff`, `history` |
| `simulate.*` | `run`, `sweep`, `replay.query` (only the layers and the time range you need), `inspect.event`, `render.frame` (for a multimodal model to look at the image) |
| `fab.*` | `export`, `checks`, `bom` |
| `lab.*` | `import`, `compare`, `calibrate`, `quality` |
| `notes.*` | Reading and writing the experiment log (`EXPERIMENTS.md`), with numbers and provenance mandatory |

Every tool carries a permission level: **read-only / may write the design / may run simulations (consumes budget) / may export files (needs human confirmation)**. Agents are not allowed to publish or print on their own.

### 4.4 The loop: propose → edit → simulate → criticise → revise
The search already contains representative work in this direction: turning CAD generation, CAE solving, result parsing and geometry revision into one interactive reinforcement-learning environment ([COSMO-Agent](https://arxiv.org/html/2605.20190), [ToolCAD](https://arxiv.org/html/2604.07960), [CADDesigner](https://arxiv.org/pdf/2508.01031)), and the survey of [LLM-enabled next-generation CAE](https://arxiv.org/html/2509.11447v1). Our difference is: **the criticism comes from several mutually independent sources** — metrics, stress tests (change the friction modelling, change the contact stiffness, change the random seed: does the ranking stay stable?), vision (render a frame and let a multimodal model look at "does this leg scrape the ground while it swings?") and physical-consistency checks.

### 4.5 A few concrete agents
- **Experimenter**: design experiments (active learning, optimal experiment design: which condition should we measure next for the most information?), run sweeps, summarise, write the results — including the negative results — into the experiment log.
- **The simulator's sceptic (a self-check agent)**: it goes looking specifically for bugs in the simulator. This week's bug was found by a naive question: "why is the foot always on the ground?" Let agents do this systematically: **fuzz** the invariants (energy conservation, mirror symmetry, stride against kinematics, plausibility of the contact count, invariance under mass scaling, invariance under unit changes).
- **Intent compiler**: natural language → structured goals and constraints → optimisation problem → candidate designs → stress test → explanation. **The LLM only translates and explains, the numerical part goes to the optimisers and the simulator**; the LLM is not allowed to guess physics.
- **Data worker**: extract measurements from phone videos/photos (a vision model plus ArUco), quality-review them, detect anomalies.
- **Knowledge layer**: make Jansen's official pages, the papers and our experiment log searchable; **an answer must cite its source, otherwise it is labelled "assumption / unverified"**.

### 4.6 Turning the platform into a sandbox for training and evaluating agents
"Design → simulate → numerical score" is an environment **with verifiable rewards**. That makes it a good benchmark for evaluating agents (**a design benchmark**: given an intent and a budget, compare the agent against the genetic-algorithm and Bayesian-optimisation baselines on blind scenarios) and a good environment for post-training agents (RLVR style).

### 4.7 Guardrails
- Every change an agent makes is auditable and rollbackable; AI-generated designs are tagged.
- **Against reward hacking**: the genetic algorithm has already gamed our scoring three times (feet passing through the body, sliding without lifting, "flat" getting looser as the leg lifts). Agents are better at gaming it than a genetic algorithm is; so the score always includes a **stress test**, and the evaluation scenarios are kept secret from the agent (to avoid evaluation leakage).
- Budget and cost ceilings; actions that affect the real world need human confirmation.

### 4.8 Risks
Physical hallucination (the LLM invents numbers), overfitting to the simulation, evaluation leakage, cost blow-up. The countermeasures are all written above, but they are worth repeating: **the value of AI in this project is "letting people see the truth faster", not "drawing conclusions for people"**.

---

## 5. Algorithm map

Selection principle: only accept methods that are **directly relevant to this problem**; for each one, state "what it is good for, what it is not good for, the preconditions". "Existing" means something that is already in the repository.

### A. Continuous parameter optimisation
| Method | Good for | Notes |
|---|---|---|
| **CMA-ES** | 10–50 dimensional continuous parameters, not much noise | Robust, almost no tuning; the first choice for replacing the self-written GA |
| **Bayesian optimisation** (GP, TuRBO) | Expensive evaluation (tens of seconds per MuJoCo run), few samples | Uses the uncertainty to decide what to try next |
| **Multi-fidelity BO / Hyperband / BOHB** | We **naturally have two fidelities** (the simplified model is cheap, MuJoCo is expensive) | The existing skeleton is already "screen with the simplified model, re-evaluate with MuJoCo" |
| **Gradient methods / differentiable simulation** | The simplified kinematics model (the circle intersections can be differentiated analytically, JAX automatic differentiation works); MJX/Warp is unsmooth at the contacts and needs smoothing | Gradients give the "sensitivity of the performance to the design" directly |

### B. Multi-objective
**NSGA-II/III, MOEA/D**; on the BO side ParEGO and qNEHVI; plus **preference learning** (the human picks from the Pareto front and the system learns their trade-offs). This is the output of the "intent compiler": a front, not a single solution.

### C. Diversity and open-ended evolution
**MAP-Elites / quality diversity (QD)**: the archive is split into cells by features (number of legs, stride, starting wind speed, weight, …) and each cell keeps the best — **the mathematical version of the genealogy tree**. Novelty search; **POET / open-ended co-evolution** (environment and design evolve together).
**The warning that must be remembered**: the search contains a series of works pointing out that **brain-body co-evolution often fails to select bodies with morphological potential**, because controller and body hold each other back ([evolutionary brain-body co-optimisation keeps failing](https://arxiv.org/pdf/2508.17464); [mitigation by controller distillation](https://arxiv.org/abs/2504.06523); [a taxonomy and challenges of embodied co-design](https://arxiv.org/pdf/2512.04770)). For us: when we evolve a pneumatic "brain" together with the body in the future, this has to be treated as a known difficulty from the start, not as something that will work by default.

### D. Mechanism synthesis and topology
- **Classical**: enumeration (Assur groups, graph isomorphism) plus optimisation.
- **Data-driven** (representative work from the search): [LINKS: a dataset of 100 million planar linkages](https://arxiv.org/pdf/2208.14567); [LInK: contrastive learning of joint representations of design and performance, retrieving among millions of mechanisms](https://arxiv.org/html/2405.20592v1); [deep generative models for four-bar linkages (cGAN, VAE)](https://arxiv.org/html/2402.14882v1); [MechaFormer: treating mechanism synthesis as sequence learning](https://arxiv.org/pdf/2508.09005); and work applying reinforcement learning to single-target-curve synthesis (I have not checked every paper individually).
- **What this means for us**: the goal of most of these works is **tracking one target path**; our goal is **gait quality + dynamics + manufacturability**. A usable idea is **"retrieve first, then fine-tune"**: start from a similar mechanism in a dataset and continue optimising with our own objective function. Note: these datasets are mostly four-bar or general planar linkages and do not contain the constraints "printability, layer allocation, sail".
- We already have one related multi-objective work as a reference point: [durability-aware multi-objective optimisation of the Jansen linkage](https://arxiv.org/pdf/2606.22129) (gait quality against joint wear).

### E. Reinforcement learning: where it fits (an honest assessment)
**Where it does not fit**: the Jansen leg itself is a **passive mechanism**, there is no controller to learn. Using RL to optimise "how the foot walks when the crank turns once" is meaningless.

**Where it fits**:
1. **A designer policy**: take the operations of the edit algebra as the actions, edit the design step by step, and let the reward be the simulation score. This is the same idea as the CAD-CAE reinforcement-learning environments found by the search. It is especially suited to the **combinatorial explosion** of topological editing and to **feasibility constraints** (the policy learns not to produce invalid designs).
2. **Controlled variants**: control policies for versions that have a drive (motor gear shifting, sail trimming, leg length adjustment), for example trimming the sail in a gust or pushing harder against an obstacle.
3. **Evolving pneumatic reflex controllers** (neuroevolution, evolution strategies, RL where needed).
4. **Robustness**: training policies or evaluating designs under **domain randomisation** of wind, terrain and friction.
5. **Post-training LLM agents**: using the simulation score as a verifiable reward.
**Cost and risks**: poor sample efficiency; single-threaded MuJoCo is only at the kHz level, so MJX/GPU or large-scale parallelism is needed; reward hacking.

### F. Surrogate models and neural operators
Gaussian processes, neural-network ensembles, graph neural networks for the mechanism graph; **active learning** decides the next batch of simulations; the uncertainty comes from deep ensembles or **conformal prediction**. The goal: while dragging a slider in the designer, predict the stride, the starting wind speed and the peak torque in **milliseconds**, and show the confidence interval and "how many similar designs has it seen".

### G. Calibration and inference (the group closest to the current bottleneck)
- **Bayesian calibration**: MCMC/HMC, ABC, **simulation-based inference (SBI, neural posterior estimation)**, ensemble Kalman inversion — giving a **posterior distribution** over the parameters instead of a point estimate.
- **Identifiability analysis** (Fisher information, profile likelihood): we have already seen that the contact stiffness, the friction and the leg mass can hide behind each other; the first question should be "can this data set separate them?", and only then do we fit.
- **Optimal experiment design**: which condition to measure next (speed, surface, wind speed) carries the most information.
- **Multi-fidelity calibration**: the simplified model as the prior mean, MuJoCo as the correction (a residual Gaussian process).

### H. Robustness and uncertainty
Domain randomisation, **CVaR optimisation** (optimise the worst 10 % of cases), **adversarial scenario search** (using evolution or optimisation to find the worst wind and terrain that make the design fail), reliability analysis (Monte Carlo). This is the other side of the same coin as the "stress tests" in section 4.7.

### I. Structure and materials
**Topology optimisation (SIMP)** lightens the links; beam/shell finite elements look at the pin-hole stresses; fatigue (the lesson of Suicideem); the anisotropy of FDM printing (strength between the layers).

### J. Constraints and feasibility
Feasibility classifiers, safe Bayesian optimisation, constrained CMA-ES; **layer allocation currently uses a greedy colouring, and can be replaced by an integer linear program for the minimum number of layers** (a ready-made small improvement, and it proves optimality).

### K. Automated science
- **Symbolic regression / SINDy**: discover empirical formulas from the simulation and the measurements ("starting wind speed = f(sail, gear ratio, mass)", the scaling laws of torque).
- **Program search / LLM-guided evolution** (FunSearch, AlphaEvolve and the like): what is searched is not the parameters but **the program that generates designs** or **the fitness function itself**.
- **Causal inference** (directly related to your background): we ran into a phenomenon: the heavier the leg, the larger the mean torque, but the total mass is fixed, and the reason was never understood. That is exactly a "correlation or causation" question. In the simulation we can do **intervention experiments** (`do(leg mass)`, everything else unchanged); in the real world only in a limited way. Turning "why" into a question that can be answered systematically.

### Priority recommendations (not aiming for everything)
1. **Replace the self-written GA with mature libraries**: pymoo, `cma`, BoTorch/Ax, pyribs (QD), `sbi`. The engineering principle: do not reinvent optimisers; put the effort into **the formulation of the problem, the evaluators and the anti-gaming**.
2. **Multi-fidelity screening + a quality-diversity archive** (this is the "genealogy").
3. **Bayesian calibration + identifiability analysis** (this addresses the biggest current bottleneck: how to give honest parameters from very little real data).
4. **BO for the small-sample optimisation of expensive simulations**.
5. Everything else (the RL designer, generative models, surrogate models, topology optimisation) starts as a small demo; do not let it jump ahead of the data and the editor.

---

## 6. Product forms (consolidated)

```
                    ┌──────────────────── Agents (MCP tool surface + benchmarks + guardrails) ─────────────────────┐
                    │                                                                                              │
 Intent ──► Editor ─┼─► Worlds ──► Simulation (glass box, multi-fidelity)──► Foundry                               │
(intent compilation)│   (scene library)     L0 replay … L3 realtime/fork     (printable / scaled-up cut list)      │
      + edit algebra)│                                                                                             │
                    └────────── Commons (design registry, genealogy, leaderboards with measured results) ──────────┘
                                         ▲
                       Lab (test rig, phone video, calibration, identifiability)──real data flows back
```

- **Studio / Editor**: section 3.
- **Worlds**: a library of scenarios (terrain, wind, weather replays, planets); sand needs care — first connect a resistance law and state the applicable range clearly.
- **Foundry**: printable export and **scaling-up tools** (given a design, output a cutting list, the joints and a structural check for a scaled-up PVC conduit version; Jansen himself switched to wood in the Lignatum era precisely because of large-size stiffness).
- **Brains & Ecology (further out)**: a library of pneumatic logic elements, co-evolution of morphology and brain, herds and beach ecologies (in the Tepideem era Jansen found that a herd can shield each other from the wind).
- **Planets (exploratory)**: sail torque is proportional to the air density, weight is proportional to gravity — which world is best for "walking on wind alone"? The scenario library already has approximate numbers for the Moon, Mars, Titan and Venus. On the small model, with 3 m/s of wind and the same sail, two full crank revolutions take about 4.2 s on Earth, 3.4 s on Venus (limited by the sail's own top speed) and 29 s on Mars; **these are model outputs, not prophecies**. On the Bruchum page Jansen half-jokingly says that NASA may yet take the caterpillars to Venus or Mars — this is a clean physics question, and it should always be labelled "exploratory, unverified".

---

## 7. Next steps (in dependency order)

| # | What to do | Why it is in this position | Validation gate |
|---|---|---|---|
| 1 | **Spec-driven-ness**: the viewer, the sliders, the genes and the 3D are all derived from `LinkageSpec`, and the hard-coded Jansen goes away | The precondition for the editor and for topological evolution; a small amount of work | Get a non-Jansen dyad-chain design through "design → simulate → export" |
| 2 | **Edit algebra v0 + operation log + undo + genealogy**, supporting `set_param`, `add_dyad` and `array_legs` first | The fulcrum of the whole design | The operations are reversible, and replaying the log yields the same design |
| 3 | **Glass box v1**: record contact forces, joint reaction forces, energy terms and events; footfall diagram, energy Sankey diagram, event timeline, A/B synchronised replay | It answers "we want to see the process of the simulation"; it is also the agent's "eyes" | The energy account closes (the script already exists: 97 % dissipated at the contacts) |
| 4 | **MCP tool surface v0**: `design.*`, `simulate.*` (including querying the replay by layer), `lab.*`; a first version of the agent benchmark; the simulator-sceptic agent | Where "AI-native" lands | The agent does not lose to the CMA-ES baseline on blind scenarios, and every change is auditable |
| 5 | **Optimisation toolbox**: swap in mature libraries; a quality-diversity archive; multi-fidelity screening | Drops the self-written GA, adds the genealogy | Reproduce the existing evolution results on the benchmark |
| 6 | **Bayesian calibration + identifiability** | It becomes usable as soon as the first real data arrives | Recover the known parameters and their posterior width on synthetic data |
| 7 | **Real-time / forkable simulation** (first assess the feasibility of MuJoCo WASM) | Glass box L3 | Latency and stability measured |

**Not in this table, but never forgotten**: the real measurements. They wait beside every single step.

## 8. Open questions
1. Do we support mechanisms beyond dyad chains (including sliders and multi-loop coupling), and when?
2. What form does the edit algebra take in practice: an event-sourcing log, or CRDT-based merging (several people or agents editing at the same time)?
3. Does real-time streaming simulation run on the back end or in the browser (WASM)? It depends on the performance measurements.
4. How do we keep the blind scenarios of the agent benchmark secret while they stay representative?
5. Sand: where do the constants of the resistance law come from (the literature, or our own measurements)?
