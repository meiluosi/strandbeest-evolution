# Experiments

All runs are seeded and reproducible; raw results are in `experiments/*.json`.
Units: lengths use Jansen's numbers (no stated unit); "shape distance" is a symmetric mean nearest-point distance between two foot loops after normalising each to width 1 (0 = identical shape; orientation is not normalised).

## 1. Can evolution re-discover Jansen's leg from scratch?

`pnpm reproduce 20 500 150 default` — 20 seeds, population 150, 500 generations, **default GA settings** (mutation rate 0.25, scale 0.06, 2 elites). Every length starts uniform in [5, 80] (blind box: no knowledge of Jansen's values beyond order of magnitude). Infeasible legs get a graded penalty so the search has something to climb.
Raw: `experiments/reproduce-jansen-default-ga.json`.

**A. Inverse problem — fit the shape of Jansen's foot loop.**

| | result |
|---|---|
| median shape distance | 0.0155 |
| seeds with shape distance < 0.02 | 16 / 20 |
| seeds recovering the *lengths* (mean log error after rescaling < 0.1) | 0 / 20 |

Reading: the search reliably finds legs whose foot path looks like Jansen's, but **not his numbers**. Different length sets produce nearly the same loop (the mapping is many-to-one), so matching the shape does not pin down the lengths. We have not checked whether the found solutions are genuinely different mechanisms or the same one under a symmetry we did not normalise.

**B. Objective-driven — maximise our flat-stroke fitness (v1), then compare with Jansen.**

| | result |
|---|---|
| Jansen's own fitness | 0.481 |
| median best fitness over seeds | 0.370 |
| seeds that beat Jansen | 2 / 20 |
| median shape distance to Jansen's loop | 0.087 |
| seeds within 0.05 of Jansen's loop | 0 / 20 |

Reading: with default settings, blind search usually does **not** reach Jansen's score under our objective, and none of the runs lands on his loop shape. Two things are mixed together here: the optimiser gets stuck in local optima (a small sweep showed higher mutation helps; see run 1b), and our objective is a design choice that need not have Jansen's design as its optimum. Starting *from* Jansen's lengths, the same objective reaches 0.71 (`experiments/flat-seed1.json`), so Jansen's leg is not this objective's optimum.

**What this does and doesn't show.** It shows that a D-shaped, flat-stroke foot path is findable by blind evolutionary search in this parameterisation (the topology is fixed to Jansen's). It does not show that Jansen's numbers are recoverable, nor that our objective reproduces his; his actual objective and method are not documented in the sources we found.

### 1b. Tuned GA settings
`pnpm reproduce 20 500 150 tuned` (mutation rate 0.5, scale 0.15, 3 elites, chosen from a 6-seed sweep). Results to be added: `experiments/reproduce-jansen-tuned-ga.json`.

## 2. Objectives on top of Jansen's start (seed 1, 80 generations)

| objective | fitness: Jansen → evolved | evolved: stroke length / lift / duty |
|---|---|---|
| flat stroke (v1) | 0.48 → 0.71 | 54.6 / 10.8 / 0.60 |
| high step | 0.33 → 1.29 | 46.7 / 88.9 / 0.36 |

(Jansen's loop: stroke 57.1, lift 22.5, duty 0.43.) Lessons: without the "foot below the hip" and "real swing phase" constraints the GA exploits the metric (foot swings through the body; foot only slides). The thresholds that block this are our own design choices.

## 3. Wind and slope (quasi-static model, `pnpm dynamics`)

12 legs, 50 kg, 1 unit = 2 cm, rolling resistance 5 % of weight, illustrative sail (4 m², radius 0.5 m, 20:1 gearing). These are assumptions, so only the comparison between designs under identical assumptions means anything.

| design | slope | stride (m) | peak torque (N·m) | speed at 4 / 8 / 12 m/s wind (m/s) |
|---|---|---|---|---|
| Jansen | 0° | 2.67 | 14.7 | 0.14 / 0.31 / 0.48 |
| Jansen | 10° | 2.67 | 49.3 | 0.12 / 0.29 / 0.45 |
| evolved (flat v1) | 0° | 1.73 | 12.6 | 0.10 / 0.21 / 0.32 |
| evolved (flat v1) | 10° | 1.73 | 37.3 | 0.08 / 0.19 / 0.30 |
| evolved (high step) | 0° | 2.66 | 14.0 | 0.14 / 0.31 / 0.48 |
| evolved (high step) | 10° | 2.66 | 49.3 | 0.12 / 0.28 / 0.45 |

Reading: the kinematic objectives do not translate into big dynamic differences here; a shorter-stride leg needs less torque but also goes slower per crank turn. The quasi-static torque is set mostly by slope and drag times stride, so a design objective that actually targets torque (not implemented yet) is a more honest route to "better" legs.
