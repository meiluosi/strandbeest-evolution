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

## 6. MuJoCo simulator vs the reduced-order model (slow flat walk, first cross-check)

> **Superseded by section 9.** The numbers in this section and in section 8 were produced with a simulator bug (each foot had two coincident collision spheres that collided with each other) and, for section 8, with a mislabelled contact-stiffness unit. They are kept for the record; use section 9.

`packages/sim`, `python scripts/crosscheck.py '<overrides>' <tag>`. Planar model, 12 legs on one crankshaft, torso pitch locked, 50 kg total, tube 0.12 kg/m (assumption), crank driven at 0.6 rad/s (slow, so inertia should matter little) for 3 revolutions on flat ground, no drag. The reduced-order reference gets a leg-gravity term because MuJoCo's legs have mass. Reference stride: 2.665 m per revolution.

| contact setting | stride (m/rev) | mean crank torque (N·m) | torque peak-to-peak (N·m) | curve correlation with reference |
|---|---|---|---|---|
| default (contact time const 0.02 s, μ 1.5) | 2.73 | 3.2 | 4.8 | 0.30 |
| μ 0.6 | 2.83 | 2.5 | 4.7 | −0.01 |
| stiffer contact (0.005 s) | 2.83 | 4.0 | 5.4 | 0.08 |
| softer contact (0.05 s) | 2.33 | 9.1 | 9.9 | 0.52 |
| μ 3.0 | numerical blow-up (stride 8 m, torque 10⁵ N·m) | – | – | – |
| reference (reduced-order, + leg gravity) | 2.665 | 0.55 | 8.1 | – |

What this shows, and what it does not:
- **Stride agrees** to within about 3–6 % for default/stiffer contact (−13 % for very soft contact). Stride is kinematic, so this is the part the reduced-order model could be expected to get right.
- **The reduced-order torque curve is not reproduced.** Correlation is between −0.01 and 0.52 and the mean torque is 2.5–9 N·m above the reference. With many feet in contact at once, how the load is shared is statically indeterminate and set by contact compliance and foot slip, which the reduced-order model ignores. The extra mean torque is energy lost to that (about 15–55 J per revolution, i.e. roughly 6–20 N of equivalent drag at 50 kg).
- **The simulator's torque is not converged either:** it changes by a factor of ~3 across contact stiffness. Until that is understood (contact model, slip, foot geometry) neither number should be trusted for start wind or peak torque. The earlier start-wind and peak-torque results in sections 3–5 came from the reduced-order model and are therefore **not validated**.
- **Numerical limits found along the way:** bars lighter than roughly 0.1 kg/m blow up the loop constraints even at 0.5 ms; friction 3.0 blew up; the original all-free-bodies formulation was unstable and was replaced by hinge tree plus loop closures.

## 7. Calibration machinery on synthetic data (MVP check, not a result about real walkers)

`packages/calib`, test `test_synthetic_recovery.py` (marked slow, about 8 minutes). A Measurement was generated by the simulator with `contact_solref = 0.01` plus 2 % noise on the torque, for the small 6-leg design; the calibration started from 0.02 and ran Nelder–Mead on log-parameters for at most 25 simulator runs. It recovered the value to within the test's 35 % tolerance.

What this shows: the import → compare → fit → Profile path works and a single contact parameter is identifiable *when the data come from the same model*. What it does not show: that the same holds for real data (model error will be larger than noise), for several parameters at once (friction and contact stiffness were not fitted together), or that the fitted values mean anything physical. Section 6 suggests torque depends strongly on contact settings, which helps identifiability but also means a poor contact model will absorb error into the fitted values.

## 8. P1: which simulator outputs can be trusted? (numerical vs physical settings)

> **Superseded by section 9** (same study re-run after the foot-collision fix; conclusions changed in several places). The contact-stiffness values below are in mass-normalised units (1/s²), not N/m as written.

`packages/sim/scripts/p1_study.py`, raw: `experiments/p1-study.json`. Baseline: 12 legs, flat ground, 50 kg, tube 0.12 kg/m, crank 0.6 rad/s, 2.5 revolutions, **foot pad stiffness 1e5 N/m** (now expressed directly in N/m rather than as a mass-dependent time constant), μ 1.5, timestep 0.5 ms, metrics after the first revolution. One setting is changed at a time. Reference stride from the reduced-order model: 2.665 m/rev.

### Numerical settings (a trustworthy simulator should not depend on these)

| setting | stride (m/rev) | mean torque (N·m) | torque peak-to-peak (N·m) |
|---|---|---|---|
| timestep 1 / 0.5 / 0.25 / 0.125 ms | 2.808 / 2.808 / 2.808 / 2.808 | 13.46 / 13.47 / 13.47 / 13.46 | 19.9 / 14.2 / 12.3 / 11.5 |
| solver iterations 30 / 100 / 300 | 2.808 | 13.47 | 14.2 (identical) |
| loop stiffness (time const 4 / 2 / 1 ms) | 2.819 / 2.808 / 2.799 | 13.31 / 13.47 / 13.39 | 14.6 / 14.2 / 13.0 |
| loop impedance soft (0.9 0.95) vs stiff (0.99 0.999) | 2.871 vs 2.808 | **6.4 vs 13.5** | 17.7 vs 14.2 |
| friction cone pyramidal vs elliptic | 2.808 vs 2.812 | **13.5 vs 25.3** | 14.2 vs 27.3 |
| friction impedance ratio 1 vs 10 | 2.808 vs 2.834 | **13.5 vs 21.5** | 14.2 vs 73.6 |
| no-slip iterations 0 vs 10 | 2.808 vs 2.777 | **13.5 vs 15.3** | 14.2 vs 40.4 |

Reading:
- **Stride is robust** (within 2 % everywhere) and about 5 % above the reduced-order value.
- **Mean torque converges** with timestep, solver iterations and loop stiffness (changes under 1–2 %), **but it changes by up to a factor 1.9 with how friction is regularised** (cone type, impedance ratio, no-slip iterations) and by a factor 2 with soft loop constraints. Mean torque on flat ground is almost entirely energy dissipated by foot slip (82 J per revolution, equivalent to a 29 N drag, about 6 % of weight), so it inherits the uncertainty of the stick–slip model. **This is a limit of the simulator, not something more refinement removes.**
- **Peak-to-peak torque needs a timestep of 0.25 ms or smaller** (19.9 → 14.2 → 12.3 → 11.5 N·m); at 0.5 ms it is about 23 % high.

### Physical settings (to be fixed by measurement, not by tuning)

| setting | stride (m/rev) | mean torque (N·m) | torque peak-to-peak (N·m) |
|---|---|---|---|
| foot stiffness 1e4 / 3e4 / 1e5 / 3e5 / 1e6 N/m | 2.82 / 2.84 / 2.81 / 2.80 / 2.80 | 9.0 / 10.8 / 13.5 / 14.0 / 13.1 | 9.5 / 12.5 / 14.2 / 17.2 / 28.1 |
| friction μ 0.5 / 0.8 / 1.2 / 2.0 / 3.0 | 2.78 / 2.79 / 2.80 / 2.83 / 2.80 | 3.5 / 8.7 / 11.8 / 12.5 / 10.8 | 48.7 / 25.6 / 14.8 / 15.2 / 11.6 |
| foot radius 5 / 10 / 20 mm | 2.80 / 2.81 / 2.82 | 13.1 / 13.5 / 14.2 | 13.9 / 14.2 / 13.9 |
| tube mass 0.05 / 0.12 / 0.2 kg/m | 2.83 / 2.81 / 2.80 | **8.0 / 13.5 / 15.5** | 13.7 / 14.2 / 13.2 |

Reading:
- Mean torque plateaus for foot stiffness at or above 1e5 N/m, but peak-to-peak keeps growing (28 N·m at 1e6): the stiffer the pad, the spikier the load. **Pad stiffness is therefore a real, measurable parameter** that decides peak loads.
- Below μ about 1.2 the feet slip and stick–slip dominates (peak-to-peak 49 N·m at μ 0.5); above it the result is flat. Non-monotonic at μ 3.0 (10.8) was not investigated.
- **Leg mass matters strongly (8 → 15.5 N·m mean torque) and we do not yet understand why**: total mass is fixed, so heavier legs mean a lighter torso, yet torque rises. Treat as an open question.

### Small printed walker (6 legs, 1 unit = 2 mm; `design-jansen-small-6leg`)
- Loop impedance must be soft (0.9 0.95) there: stiffer settings (0.95 0.99 and 0.99 0.999) blow up at every timestep tried (down to 0.1 ms) and at every pad stiffness tried. Cause not identified (a mass-ratio effect is suspected). With the soft setting results converge in timestep (stride 0.2565 / 0.2566 m at 0.2 / 0.1 ms).
- Pad stiffness changes the result a lot at this scale: stride 0.209 m at 3000 N/m versus 0.2565 m at 10 000 N/m, mean torque 4.6 versus 1.7 mN·m. **Pad stiffness has to be measured or calibrated** before small-walker torque or stride means anything.

### What changed in the simulator as a result
- Default timestep 0.25 ms; foot stiffness is a physical parameter in N/m (default 1e5, a calibration target) and is what `strandbeest-calib` now fits.
- Every run records the largest loop-constraint violation; a run with violation above 1 mm should be discarded.
- Convergence regression tests (slow): stride and mean torque independent of timestep and iterations, loops stay closed.

### Consequences for earlier results
Sections 3 to 5 (start wind, peak torque from the reduced-order model) remain unvalidated. This study also shows that even the better model has a torque *level* that depends on friction modelling choices by up to a factor 2; the honest way to state a torque is as a range across those choices until measured.

Update after P1: the calibration target is now the physical pad stiffness (`contact_stiffness`, N/m) instead of the mass-dependent contact time constant. Re-run on synthetic data (truth 8000 N/m, 2 % noise, start 3000 N/m, at most 25 runs): recovered within the test's 35 % tolerance, in about 66 s. The slow convergence tests of section 8 also pass.


## 9. Corrections, and the corrected results (2026-10-06)

### What was wrong
1. **Overlapping foot spheres.** Both bars that end at the foot carried a collision sphere, so every foot had two coincident spheres that collided with each other (contact distance about −2 × radius), and feet of the same walker were allowed to collide. This put spurious contacts and forces into every MuJoCo run of sections 6 to 8, the calibration tests and the small-walker numbers. Found while building the replay viewer (the recorded "feet in contact" flags were true at every frame). **Fixed:** one sphere per leg; feet collide only with terrain.
2. **Wrong unit for contact stiffness.** The parameter I called "foot stiffness in N/m" is MuJoCo's reference-acceleration stiffness, in **1/s²**, normalised by effective mass. A test (a sphere of 0.05, 0.5 and 5 kg on the same setting) sinks the same 0.637 mm at k = 1000 and 0.108 mm at k = 10 000 whatever its mass. A light foot carrying a heavy body therefore sinks far more than "k N/m" suggests: our small walker at the old default sank 8 to 21 mm. The physical pad stiffness is roughly k times the effective mass at the foot, so the fitted value is **not directly comparable with a pad stiffness measured in N/m**. Fixed in the config description, UI labels and calibration range (now 1e4 to 1e7, start 1e5); the small-walker default went from 1570 to 3e5.

### Corrected cross-check with the reduced-order model (section 6 redone)
12 legs, flat, crank 0.6 rad/s, 3 revolutions, no drag. Reference stride 2.665 m/rev, mean torque 0.55 N·m, peak-to-peak 8.1 N·m.

| setting | stride (m/rev) | mean torque (N·m) | torque peak-to-peak (N·m) | curve correlation |
|---|---|---|---|---|
| default (k 1e5, μ 1.5) | 2.83 | 8.8 | 7.7 | **0.59** |
| k 1e4 | 2.79 | 6.1 | 4.4 | −0.47 |
| k 1e6 | 2.79 | 11.5 | 7.5 | 0.59 |
| μ 0.6 | 2.77 | 6.2 | 8.3 | 0.10 |

With stiff contact the simulator now reproduces the reduced-order torque *shape* (correlation 0.59) and *amplitude* (peak-to-peak 7.5–7.7 vs 8.1), which it did not before (0.30 and 4.8). Stride is about 5–6 % above. **The mean torque is still about 8 N·m higher** than the reduced-order value: energy lost to foot slip, which the reduced-order model cannot see. Soft contact or low friction still destroys the agreement.

### Corrected P1 study (section 8 redone; raw: `experiments/p1-study.json`, old: `experiments/p1-study-before-foot-fix.json`)
Same baseline as section 8. What changed:

| quantity | before (buggy) | after |
|---|---|---|
| baseline mean torque | 13.5 N·m | **8.9 N·m** |
| timestep 1 / 0.5 / 0.25 / 0.125 ms, torque peak-to-peak | 19.9 / 14.2 / 12.3 / 11.5 | 13.1 / 10.9 / 10.5 / 10.4 (0.5 ms is already within 4 %) |
| cone elliptic vs pyramidal, mean torque | 25.3 vs 13.5 (×1.9) | 17.9 vs 8.9 (×2.0) |
| friction impedance ratio 10 vs 1 | 21.5 vs 13.5 (×1.6) | 21.7 vs 8.9 (**×2.4**) |
| no-slip iterations 10 vs 0 | 15.3 vs 13.5 (×1.1) | 13.7 vs 8.9 (×1.5) |
| soft vs stiff loop constraints, mean torque | 6.4 vs 13.5 | 8.7 vs 8.9 (no longer an effect; loop violation 1.4 mm) |
| contact stiffness 1e4 / 3e4 / 1e5 / 3e5 / 1e6 (1/s²), mean torque | 9.0 / 10.8 / 13.5 / 14.0 / 13.1 (plateau) | 6.1 / 6.8 / 8.9 / 10.2 / 11.5 (**keeps rising**), peak-to-peak 6.2 → 23.9 |
| friction 0.5 / 0.8 / 1.2 / 2.0 / 3.0, mean torque | 3.5 / 8.7 / 11.8 / 12.5 / 10.8 | 4.3 / 7.4 / 9.1 / 7.7 / 7.1 (non-monotonic) |
| tube mass 0.05 / 0.12 / 0.2 kg/m, mean torque | 8.0 / 13.5 / 15.5 | 4.8 / 8.9 / 12.4 (still rises with leg mass, still unexplained) |

Stride stays within 3 % everywhere. What survives: the torque *level* depends strongly on how stick–slip friction is treated numerically (up to ×2.4 now), stride is robust, and leg mass raises mean torque for a reason we do not understand. What does not survive: the "plateau above k = 1e5", the need for a 0.25 ms step, and the claim that soft loop constraints halve the torque.

### Small printed walker (6 legs, 1 unit = 2 mm), flat ground, corrected simulator and corrected metric
Kinematic stride from the reduced-order model: 0.2665 m/rev. 3 revolutions, statistics over revolutions 2 and 3 (see "Metric window" below).

| contact stiffness k (1/s²) | stride (m/rev) | mean torque (mN·m) | peak (mN·m) | peak-to-peak (mN·m) | deepest foot sinkage (mm) |
|---|---|---|---|---|---|
| 3e4 | 0.267 | 0.90 | 6.5 | 9.1 | 2.6 |
| 1e5 | 0.279 | 0.66 | 7.4 | 13.4 | 0.9 |
| 3e5 | 0.280 | 0.65 | 15.0 | 23.6 | 0.6 |
| 1e6 | 0.281 | 0.82 | 16.7 | 27.3 | 0.3 |

Stride converges (0.3 % to 5 % above kinematic). Mean torque is small and non-monotonic in k; peak torque grows with k (impact-like loads). About two of six feet are down at any moment, as 43 % duty implies. The earlier finding that "small-walker stride depends strongly on pad stiffness" was an artefact of the foot bug plus very soft contact. The stiff-loop instability at this scale (section 8) was not re-investigated.

### Metric window (a second bug found afterwards)
The gait metric averaged over a window that depended on the run length: runs of at most 1.5 revolutions included the start-up ramp (the small walker's mean torque read 1.3 mN·m instead of 0.65), and runs of 2.5 revolutions averaged 1.5 revolutions (a partial cycle, a few per cent off). Now the first revolution is skipped and the statistics cover the largest whole number of revolutions after it; runs shorter than two revolutions are marked `steady_window: 0`. Effect on the 12-leg P1 numbers: below 0.5 % (baseline mean torque 8.89 → 8.85 N·m; every conclusion above stands). The small-walker table above was recomputed. A regression test checks that the mean torque of a 2-revolution and a 3-revolution run agree within 5 %.

### Energy accounting: where does the work go? (`packages/sim/scripts/energy_account.py`)
Small walker, motor-driven, revolutions 2 and 3 averaged. Input work per revolution 4.05 mJ (equivalent mean crank torque 0.645 mN·m, which agrees with the metric above). Dissipated: **contacts 3.91 mJ (97 %)**, loop closures 0.13 mJ (3 %), joint friction 0, unexplained 0.008 mJ (0.2 %). The account closes. So on flat ground the mean torque is almost entirely energy lost at the feet (slip plus contact damping), which is why it is as sensitive to the friction treatment as section 9 shows, and why a model without that loss (the reduced-order one) predicts about zero. This was a hypothesis for a week; it is now measured (inside the simulator).

### Scenes, and a sail drive (new)
The simulator now has terrains (flat, slope, step, random bumps, a crude soft ground), an environment (gravity, air density), winds (constant, gusts, lull) and a **sail drive**: a drag sail turning the crank through a gear, no motor. The motor has a torque limit (0.3 N·m for the small walker, an assumption), otherwise a blocked foot forces the linkage open and the run blows up.

`packages/sim/scripts/sail_start.py`, raw `experiments/sail-start.json`. Small walker, sail 0.03 m², radius 0.08 m, gear 10, Cd 1.2, air 1.2 kg/m³ (all assumptions), one crank revolution, give-up after 10 s without moving:

| wind (m/s) | 0.4 | 0.5 | 0.6 | 0.7 | 0.8 | 0.9 | 1.0 | 1.2 |
|---|---|---|---|---|---|---|---|---|
| completes one revolution | no (8 mm in 40 s) | yes, 37 s | 21 s | 15 s | 12 s | 10 s | 8.7 s | 6.7 s |

The walker starts at about **0.45 m/s**. The start wind predicted from the motor-driven peak torque (14.8 mN·m at 2 rad/s, plus friction) is **0.99 m/s**, about twice as high: the motor-driven peak contains dynamic loads, so it overestimates the load a sail must beat at standstill. The same caution applies to the start-wind logic of the reduced-order model in sections 3 to 5 (which also uses the peak torque). All of this is model against model; nothing here is measured.

With 3 m/s wind and the same sail, two crank revolutions take about 4.2 s on Earth, 3.4 s with Venus-like air (65 kg/m³: the sail is limited by its own top speed), and 29 s with Mars-like air (0.02 kg/m³). Planet values are approximate (NASA fact sheets, Wikipedia: Venus 8.87 m/s² and ~65 kg/m³, Mars ~3.7 m/s² and ~0.02 kg/m³, Titan ~5.4 kg/m³); Titan's gravity is from memory and unchecked.

A 12 mm step blocks the small walker (it advances 12 % of the ideal distance); the player flags this as "almost no progress".


## 12. Reproducibility audit of the committed GA results (E3-01, 2026-10-06)

E3-01 moved the fitness functions and the genome from Jansen-only helpers to a `GenomeSpace` derived from any `LinkageSpec`. Before trusting that the move changed nothing, I re-ran fixed-seed experiments with the code from before the refactor and after it:

- `pnpm experiment flat 1 80`: output of the old code and the new code is **identical** (every field of `original`, `evolved`, `history`), so the refactor did not change behaviour. A golden test (`ga.test.ts`, seed 1, 80 x 25, best fitness 0.6469557486851051) now guards this.
- `pnpm reproduce 20 500 150 default` and `... tuned`: both reproduce the committed `experiments/reproduce-jansen-*-ga.json` exactly (same content). Their conclusions in section 2 stand.
- **Negative finding:** the committed `experiments/flat-seed1.json` and `highstep-seed1.json` did **not** reproduce with the code at HEAD (for `flat`: evolved fitness 0.7129 committed vs 0.7446 now; the GA history differs from generation 0). They predate the commit that introduced graded infeasibility penalties (a8127b1) and were never regenerated. They are demo inputs (`scripts/dynamics-demo.ts` reads the evolved lengths), no number in this document or the README cites them, and I regenerated both with the current code. Nothing else was found stale. Model-internal; nothing here is measured.


## 13. Golden runs, and a bug they found: "soft ground" did nothing (E4-01, 2026-10-06)

Before refactoring the simulator I recorded ten golden runs (`contracts/sim-golden/`: flat, slope, step, bumps, soft ground, sail in constant wind and gusts, Mars gravity, 4 legs with an elliptic cone, friction impratio 10). Recording them exposed that the `soft` terrain **never had any effect**: its metrics were identical to flat ground to 16 digits. The cause: for two geoms with direct (negative) `solref` MuJoCo uses the **stiffer** one; the hook softened the feet only, so the stiff ground always won. The hook now softens the terrain geoms and the feet. With stiffness 4000 (1/s^2) the max foot sinkage goes 0.57 mm -> 11.4 mm, stride per revolution 0.276 -> 0.177 m (-36 %), peak torque 14.7 -> 45 mN*m; at 400 the walker sinks 69 mm and barely moves (stride 0.004 m). Model against model: "soft ground" is still a crude stand-in, not sand. Earlier statements in this file and in SIM-DESIGN.md that the simulator "has a crude soft ground" were true of the code, false of its behaviour, until this fix; no result reported here depended on it. A regression test (`test_soft_ground_is_actually_softer_than_flat_ground`) now guards it.

**Unit-dependence of the servo (found by the unit-scaling contract, E4-03).** `scenario_from_design` makes the servo gains proportional to `unit_m` (a proxy for walker size). So the same physical walker written in other length units (`scale` x2 with `keep_physical`: unit 2 mm -> 1 mm, every length x2) runs with a different servo: peak crank torque 14.7 -> 8.5 mN*m (-42 %), mean torque -8 %, stride per revolution unchanged (0.2778 m). Stride is robust, torque is not: another reminder that torque levels here depend on numerical/servo choices (section 8). Not fixed; the contract compares both with the same physical drive. Model against model, nothing measured.


## 14. The energy account and foot loads inside every run (G-01, 2026-10-06)

Every run now records, at each sample, the normal and tangential load and the sliding speed of each foot, the kinetic and potential energy, and the cumulative energy account since the start of driving (input work by the drive, dissipation at the contacts, in the loop closures, and in joint friction/damping); `energy_*` metrics summarise the same whole-revolution window as the gait metrics. `scripts/energy_account.py` is superseded by this. Small 6-leg walker (docs/EXPERIMENTS.md section 8 settings), model against model:

| run (2 steady revolutions) | input per rev | contact | loops | joint friction + damping | residual (input - dissipation - change of K+U) |
|---|---|---|---|---|---|
| flat, motor | 4.06 mJ | **96.5 %** | 3.3 % | 0 | 0.2 % |
| 5 degree slope, motor | 119 mJ | 33 % | -0.4 % | 0 | -0.4 % (the rest is potential energy gained) |
| flat, sail in 4 m/s wind | 47 mJ | 17 % | 0.7 % | **82 %** | 0.02 % |

- The energy closes within 0.4 % everywhere (acceptance was < 2 %), and the flat-ground contact share reproduces the earlier "about 97 %".
- With a sail, 82 % of the input goes into the crank damping and Coulomb friction, which are **assumed** values (`drive.crank_damping`, `crank_friction`, section 11): the sail result depends mostly on a guess.
- The mean ground reaction over whole revolutions equals the weight within 5 % (test).
- **Stance fraction, a different number from the kinematic duty factor.** The linkage's foot path is flat for 43 % of a revolution (kinematic duty 0.433); in the simulation each foot is in contact for **34.8 %** of the time (all six feet within 0.1 %). The footfall diagram shows the simulated one and the UI lists both; the gap is the part of the "flat" path where the foot hovers a fraction of a millimetre above the ground (pad compression 0.6 mm).
- Diagnosis rules (events.py) and their thresholds: foot slip = tangential speed above 2 cm/s for at least 3 samples; torque limit = at least 98 % of the cap for at least 6 ms; loop open = more than 5 mm; weak sail = mean crank speed below 15 % of the unloaded sail speed. On the 12 mm step the walker advances 12 % of its ideal distance, the motor reaches its 0.3 N*m cap 13 times and a loop opens by 6.7 mm at t = 1.97 s (which also means that run's numbers after that are not trustworthy). On Mars (0.02 kg/m^3) a 2 m/s wind cannot start the sail (standstill torque 1.15 mN*m), 3 m/s turns the crank at 11 % of the unloaded speed. Thresholds are choices, not physics.

**What the replay shows (G-02…G-05, 2026-10-06; checked in the browser).** Contact-force arrows (3 cm per newton, at most 25 cm), red feet while slipping (> 2 cm/s), the centre of mass with the support polygon of the feet on the ground (red when the projection is outside), the footfall diagram, the phase ring, the energy Sankey, the invariants panel (loop opening, deepest penetration, energy residual; red past 5 mm / 5 mm / 2 %), the event timeline with click-to-jump, the diagnosis with its evidence numbers, and an A/B view that plays two runs on one clock, tabulates their metrics and marks the instant they differ most. Acceptance notes: on the 12 mm step the diagnosis is "blocked by the terrain + torque limit" and the invariants panel is red (loop opening 9.2 mm); the footfall diagram on flat ground reports **35 % simulated stance next to the 43 % kinematic duty factor** rather than 43 % (see section 14); the A/B pair flat vs step differs most at t = 7.98 s (mean body displacement 478 mm), which is the stuck walker against the walking one, not a subtle effect. Not tested: the support-polygon stability colouring on a case where the centre of mass really leaves the polygon, the slip overlay on the 3D feet beyond reading the code path, and the UI at phone width.


## 15. The simulator skeptic (A-03, 2026-10-06)

`strandbeest_sim/skeptic.py` audits a run against invariants (energy closure within 2 %, loops open less than 5 mm, penetration under 5 mm, stride within 15 % of the kinematic stride on flat ground, some foot always down), checks that no foot touches another foot, that metrics do not depend on the run length, and (through the contract suite) mirror symmetry and unit scaling.

- **It catches the two historical bugs when they are put back** (switches kept only for this test): the overlapping foot spheres (feet colliding with each other: reported) and the partial-window bias of the gait metrics (the same scenario at 3.0 and 3.5 revolutions gives different stride/torque/speed: reported, relative differences above 4 %).
- **A healthy run passes**, and the soft-ground and 12 mm step scenes are flagged (penetration; loop opening).
- **Negative finding from fuzzing:** 4 of 8 random walkers (Jansen's lengths with four of them changed by up to 8 % through the guarded `set_param` operation, 4/6/8 legs, flat / slope / bumps) break an invariant: in 3 of those 4 a loop opens by 7-8 mm and the energy residual then reaches -304 %, -84 % and -2.9 % (the account is meaningless once the model has come apart); the fourth has a residual of -4.4 % with no open loop. The default solver settings are therefore **not robust to small design changes**: the optimiser and the agents can propose designs whose simulation looks fine and is not trustworthy. The skeptic is exposed to agents as `simulate.audit` so they can ask. The cause is not investigated (candidates: loop-constraint impedance, the contact softness, the leg count). Model against model; nothing measured.
