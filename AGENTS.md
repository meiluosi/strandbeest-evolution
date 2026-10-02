# Repository Guidelines

Strandbeest (Jansen linkage) evolution project: kinematics → dynamics → evolutionary optimization → interactive demos and writing. Primary audience is Chinese-speaking; code and docs are bilingual where it matters. See `docs/ROADMAP.md` for what to work on and `docs/ARCHITECTURE.md` for the design.

## Layout

- `packages/core` — pure TypeScript, no DOM, no Node-only APIs. Linkage kinematics, evolution (GA). Must run in browser and Node.
- `packages/sim-dynamics` — (planned) physics layer; may use Python if needed, keep its interface documented.
- `apps/web-demo` — (planned) standalone interactive demo, deployable to GitHub Pages.
- `docs/` — roadmap, architecture, research notes (history of Theo Jansen's generations).

## Commands

Use `pnpm` (Node >= 22).

- `pnpm check` — Biome + type-check + tests. Run before every commit.
- `pnpm test` / `pnpm type-check` / `pnpm lint` / `pnpm format`

## Conventions

- Biome: tabs, double quotes. Strict TypeScript.
- `packages/core` is deterministic: any randomness takes a seeded RNG argument, never `Math.random()` directly.
- Every new function in `core` gets a test next to it (`foo.ts` → `foo.test.ts`). Prefer testing against known invariants (link lengths preserved, symmetry) over magic numbers.
- Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`). One concern per commit.
- Historical or numerical claims about Jansen's work must cite a source in `docs/RESEARCH-NOTES.md`. Mark unverified claims `[unverified]`; do not state them as fact in articles.
- Keep `core` free of UI dependencies so the blog (meiluosi.github.io) can import it.

## Agent workflow

- Work from `docs/ROADMAP.md`: pick the first unchecked item of the current milestone, update the checkbox when done.
- Small PR-sized steps; run `pnpm check` and report its output honestly.
- Do not add dependencies without a reason noted in the commit message.
