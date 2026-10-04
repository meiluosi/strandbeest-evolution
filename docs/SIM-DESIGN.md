# Simulator design (packages/sim)

Goal: a configurable dynamics simulator for wind-driven Strandbeest-style walkers, built on MuJoCo, that can grow scenario by scenario without rewrites. The reduced-order model in `packages/core` stays as (a) the interactive demo and (b) a cross-check oracle.

## Principles
1. **Everything is a scenario file.** One YAML/JSON document (versioned schema) fully determines a run: walker, terrain, wind, drive, solver, outputs. Same file + same seed → same result.
2. **No hard-coded fidelity.** Effects are switchable and parameterised (leg mass, joint friction/damping, contact model, terrain model, aerodynamics). Turning an effect off recovers a simpler model; there is no separate "simple mode".
3. **Extension points are registries, not forks.** Terrain, wind, drive, metric, and (later) flexibility models are registered by name; a scenario refers to them by name + params.
4. **Assumptions are data.** Every physical parameter that is a guess (tube mass per metre, sail area, sand model constants) is a named config field with a `# assumption` default, and the run result records the full resolved config.
5. **Validate before trusting.** Each new capability ships with a cross-check: against the reduced-order model where it overlaps, against analytic limits, and (when we have it) against measured data.

## Layers
```
scenario.yaml ──► config (pydantic, schema-versioned)
                    │
LinkageSpec (JSON, from core) ──► builder ──► MJCF (planar or 3D)
                    │                              │
              registries: terrain · wind · drive · metric
                    │                              │
                  runner (stepping, per-step force hooks) ──► Result (arrays + metrics + resolved config)
                    │
        cli (run, sweep, compare)   notebooks / viewers (later)
```

## Model (builder)
- Each bar of the linkage is a rigid body with in-plane freedom (slide x, slide z, hinge y); every joint of the linkage is a `connect` equality between the bars meeting there; ground pivots connect to the torso; the crank is a hinge on the torso. Closed loops are therefore handled by the constraint solver, not by hand-derived equations.
- N legs share one crankshaft: crank i is tied to crank 0 by a joint equality (fixed phase offset).
- Torso: planar (x, z, pitch) in the first version; a 3D mode is a later builder option, not a rewrite.
- Feet: spheres; only feet collide with terrain (bars and torso do not), so legs may pass each other.

## Roadmap
| slice | content | validation |
|---|---|---|
| S1 (done, with caveats below) | planar builder, motor drive at fixed crank speed, flat and slope terrain, metrics, CLI | crank-torque curve and stride vs the quasi-static model in the slow-crank limit |
| S2 | sail rotor + wind (constant, gust profile), drag on sail | start wind and steady speed vs time-domain model (should agree where slip/leg mass are small) |
| S3 | leg mass, joint friction/damping, contact parameter sweeps | sensitivity study: which effects matter |
| S4 | sand: resistive-force-theory foot forces | published RFT results for simple intruders (to be located); then internal consistency |
| S5 | wind on tubes/body, turbulence | order-of-magnitude checks vs Jansen's stated 15 km/h start wind for Aurum-class animals |
| S6 | flexible links/joints, 3D mode, turning | measured data from a small physical model (needs hardware) |

## Open questions
- Sand: RFT constants for a Strandbeest foot are not known to us; need a source or measurement.
- Real data: none yet. Plan: a ~30 cm model driven by a fan with measured crank torque and speed.
- Performance: 12 legs × 10 bars is ~400 DOF; expect real-time-ish on a laptop, to be measured. Large sweeps may want MJX/GPU later.

## Status after S1
Works: builder, motor drive, flat/slope terrain, metrics, CLI, 5 tests. First cross-check (docs/EXPERIMENTS.md §6): stride agrees with the reduced-order model; **crank torque does not, and the simulator's own torque depends strongly on contact stiffness.** Next work before S2 is to make torque trustworthy: a contact-model study (stiffness, friction cone, foot geometry), slip diagnostics, and convergence with timestep. Known numerical limits: light bars (< ~0.1 kg/m) and high friction (≥ 3) are unstable.

## Status after P1
Numerical vs physical settings are now separated (docs/EXPERIMENTS.md §8). Robust: stride; mean torque against timestep/iterations/loop stiffness; peak torque needs dt <= 0.25 ms. Not robust: torque *level* against friction regularisation (cone, impedance ratio, no-slip) and soft loop constraints, because flat-ground torque is slip dissipation. Physical parameters that must come from measurement: pad stiffness, friction coefficient, leg mass effect (unexplained), joint friction/clearance. Open: stiff loop constraints blow up for the small printed walker.
