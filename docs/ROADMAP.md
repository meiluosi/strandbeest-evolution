# Roadmap

## M0 — Scaffold
- [x] pnpm workspace, TypeScript, Biome, Vitest
- [x] `core/geometry`: circle intersection

## M1 — Kinematics (core)
- [ ] Declarative linkage spec (joints, rigid triangles, crank) so topology is data, not code
- [ ] Jansen linkage with the standard 13 lengths; verify foot path is D-shaped (flat stroke) via test
- [ ] Assemblability check across full crank rotation; detect branch flips
- [ ] Foot-trajectory metrics: stride length, lift height, flatness of ground stroke, duty cycle
- [ ] Multi-leg phase offsets (Strandbeest uses many legs on shared crankshaft)

## M2 — Evolution (core)
- [ ] Seeded RNG, genome = link lengths, GA (selection, crossover, mutation)
- [ ] Fitness v1: reproduce Jansen's "holy numbers" style objective (flat stroke, high lift)
- [ ] Experiment runner + reproducible result files (JSON)
- [ ] Fitness v2 variants: step height, efficiency, speed; compare against the original

## M3 — Web demo
- [ ] Canvas viewer: drag lengths, see foot path live
- [ ] In-browser GA with progress/visualization (Web Worker)
- [ ] Embed as Svelte component in the blog

## M4 — Dynamics
- [ ] Ground contact, friction, body mass; walk on flat / slope / sand-like friction
- [ ] Wind-driven torque model (sail → crank)
- [ ] Optional: pneumatic storage model (bottle + piston pump)

## M5 — Writing & outreach (in the blog repo)
- [ ] Series: evolution history / how the legs work / re-evolving it
- [ ] English translation, bilingual README, demo GIFs
- [ ] Research notes verified with primary sources (Jansen's site, talks, papers)
