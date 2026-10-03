# Roadmap

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
- [ ] A torque-based objective using the M4 model

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
- [ ] Inertia (flywheel effect, start-up transients) — needs a time-domain simulation
- [ ] Optional: pneumatic storage model (bottle + piston pump)

## M5 — Writing & outreach (blog repo)
- [x] Series drafted (zh): evolution history / leg geometry / re-evolving it (blog drafts, `draft: true`)
- [x] English versions drafted
- [x] Bilingual README, demo GIFs
- [ ] Verify the evolution timeline against strandbeest.com (primary source)
- [ ] Publish: enable GitHub Pages (workflow `pages.yml` is manual), npm publish, flip `draft` to false
