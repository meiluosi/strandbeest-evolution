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

Reading: with default settings, blind search usually does **not** reach Jansen's score under our objective, and none of the runs lands on his loop shape. Two things are mixed together here: the optimiser may be getting stuck (raising mutation did not fix it, see 1b), and our objective is a design choice that need not have Jansen's design as its optimum; we have not separated them. Starting *from* Jansen's lengths, the same objective reaches 0.71 (`experiments/flat-seed1.json`), so Jansen's leg is not this objective's optimum.

**What this does and doesn't show.** It shows that a D-shaped, flat-stroke foot path is findable by blind evolutionary search in this parameterisation (the topology is fixed to Jansen's). It does not show that Jansen's numbers are recoverable, nor that our objective reproduces his; his actual objective and method are not documented in the sources we found.

### 1b. Tuned GA settings (negative result)
`pnpm reproduce 20 500 150 tuned`: same 20 seeds with mutation rate 0.5, scale 0.15, 3 elites (picked from a 6-seed sweep where it looked better). Raw: `experiments/reproduce-jansen-tuned-ga.json`.

| | default | tuned |
|---|---|---|
| A. median shape distance | 0.0155 | 0.0195 |
| A. seeds with distance < 0.02 | 16 / 20 | 11 / 20 |
| A. seeds recovering lengths | 0 / 20 | 0 / 20 |
| B. median best fitness (Jansen 0.481) | 0.370 | 0.337 |
| B. seeds beating Jansen | 2 / 20 | 0 / 20 |
| B. seeds within 0.05 of Jansen's loop | 0 / 20 | 0 / 20 |

Reading: tuning did **not** help. The earlier impression came from a 6-seed trial and was noise. So "premature convergence from too little mutation" is not established as the cause of B; the structure of the search space and our objective are both still candidates, and we have not separated them.

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

## 4. Evolving legs for wind speed (torque-aware objective)

`pnpm wind-objective 6 0 5` and `pnpm wind-objective 6 10 5`: GA started from Jansen's lengths (bounds ±50 %), fitness = steady body speed in a 6 m/s wind from the quasi-static model (`fitnessWindSpeed`), 12 legs, 50 kg, 5 % rolling resistance, illustrative sail; population 60, 60 generations, seeds 1–5. Raw: `experiments/wind-objective-w6-s{0,10}.json`. Legs must still be sensible walkers (flat stroke, real swing phase, ≥ 90 % stable support) and able to start in that wind.

Speeds in m/s. "At Jansen's size" rescales each evolved leg so its mean hip-to-foot distance equals Jansen's, to separate *bigger* from *better shaped*.

| | seed 1 | seed 2 | seed 3 | seed 4 | seed 5 |
|---|---|---|---|---|---|
| flat: evolved speed (Jansen 0.228) | 0.228 | 0.312 | 0.277 | 0.282 | 0.284 |
| flat: size vs Jansen | 1.00× | 1.18× | 1.13× | 1.12× | 1.12× |
| flat: at Jansen's size | 0.228 | 0.266 | 0.246 | 0.254 | 0.253 |
| 10°: evolved speed (Jansen 0.200) | 0.200 | 0.266 | 0.239 | 0.215 | 0.242 |
| 10°: at Jansen's size | 0.200 | 0.230 | 0.214 | 0.217 | 0.217 |

Reading, within the model's assumptions:
- Most of the raw gain is **size**: the GA makes the leg larger (longer stride per crank turn). At Jansen's size the gain is about +8 % to +17 % on flat ground and +7 % to +15 % on the slope.
- Seed 1 found nothing better than Jansen's own lengths.
- Peak torque rises with the larger legs (e.g. 14.7 → 16.9–20.2 N·m on flat ground), which is the price of the longer stride.
- None of this has been checked against a real walker or a time-domain simulation; the sail, gearing and resistance are assumptions. It shows that a torque-aware objective changes what evolution finds, not that these legs would beat Jansen's in the field.

## 5. What inertia changes (time-domain model)

`pnpm time-domain`. One-degree-of-freedom model (`simulateWalk`): crank angle is the only coordinate, kinetic energy `T = ½ J_eff(ψ) ω²` with `J_eff = J_rotor + m[(dX/dψ)² + (dH/dψ)²]`, torque balance per radian of crank rotation, no slip, massless legs, **no impact loss** when the set of feet in contact changes. Same assumed walker/sail/5 % resistance as section 3. Raw: `experiments/time-domain.json`.

| quantity | quasi-static | time-domain |
|---|---|---|
| start wind from rest (m/s) | 0.727 | 0.733, identical for rotor inertia 0.05 – 300 kg·m² |
| mean body speed at 6 m/s (m/s) | 0.228 | 0.228 |
| speed ripple within a revolution at 6 m/s (m/s) | – | 0.214–0.236 (J = 0.05); 0.217–0.233 (J = 300) |
| revolutions coasted after the wind drops to 0 | – | 0.02 (J = 0.05, 2); 0.14 (J = 60); 0.64 (J = 300) |

Reading:
- The quasi-static estimates of start wind and mean speed are confirmed by the time-domain model (within ~1 %), so that simplification is not hiding a big effect.
- A flywheel does **not** lower the wind needed to start. A drag sail's torque falls to zero as it approaches wind speed, so the crank can never be spinning fast enough to store useful energy before the torque peak arrives. We first expected a flywheel to carry the crank over the peak; the test for that failed, and the numbers above are why.
- Inertia mostly smooths the speed ripple slightly (about ±5 % → ±3.5 %) and lets the walker coast through a lull, but even a very heavy rotor (300 kg·m²) coasts only about two thirds of a revolution.
- Caveats: gearing, sail and inertia values are assumptions; no impact loss and no slip are modelled; legs are massless. Results are for comparing the model's own predictions, not a validation against a real walker.
