# Architecture

```
core (TS, pure)  ──►  web-demo (canvas UI, workers)  ──►  blog embeds component
       ▲
       └── sim-dynamics (physics; Python or TS) consumes core's linkage spec
```

- **Linkage spec** (M1): a plain JSON-serializable object: fixed pivots, crank, joints defined as circle-intersections of earlier points with a branch sign. The solver walks the list in order. This lets the GA mutate lengths and, later, topology.
- **Evolution** (M2): genome = array of lengths; fitness is a pure function `(lengths) => score` built on trajectory metrics. Seeded RNG for reproducibility.
- **Distribution**: `core` is consumed from the blog either by publishing to npm or via a git/workspace dependency; decide at M3.
