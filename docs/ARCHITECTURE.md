# Architecture

> The **target** architecture and the full design-to-print pipeline are in [PLATFORM.md](PLATFORM.md). This file describes what exists today.

```
core (TS, pure)  ──►  web-demo (canvas UI, workers)  ──►  blog embeds component
       ▲
       └── sim-dynamics (physics; Python or TS) consumes core's linkage spec
```

- **Linkage spec** (M1): a plain JSON-serializable object: fixed pivots, crank, joints defined as circle-intersections of earlier points with a branch sign. The solver walks the list in order. This lets the GA mutate lengths and, later, topology.
- **Evolution** (M2): genome = array of lengths; fitness is a pure function `(lengths) => score` built on trajectory metrics. Seeded RNG for reproducibility.
- **Distribution**: `core` is consumed from the blog either by publishing to npm or via a git/workspace dependency; decide at M3.

## Today vs target
| piece | today | target (see PLATFORM.md) |
|---|---|---|
| `packages/core` (TS) | kinematics, GA, reduced-order dynamics | unchanged role: live feedback in the browser |
| `packages/sim` (Python/MuJoCo) | planar S1, motor drive, pydantic scenario | schema-first scenarios, sail/wind, sand, calibrated |
| `apps/web-demo` | linkage viewer, GA, wind panel | grows into `apps/web` (designer, viewer, fab, lab) |
| schemas, fab, calib, api, hardware | – | new packages per PLATFORM.md §7 |
