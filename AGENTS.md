# Repository Guidelines

Strandbeest (Jansen linkage) evolution project: kinematics → dynamics → evolutionary optimization → interactive demos and writing. Primary audience is Chinese-speaking; code and docs are bilingual where it matters. See `docs/PLATFORM.md` for the overall vision, data contracts and phase plan, `docs/ROADMAP.md` for what to work on, and `docs/ARCHITECTURE.md` for what exists today.

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

## Cross-cutting rules (platform)

- The Design, Scenario and Run documents are the interfaces between components (`docs/PLATFORM.md` §3). Do not add a parameter to one component without putting it in the schema.
- Every physical parameter that is a guess is a named config field with an `assumption` default; never hard-code one in logic.
- Report negative and limiting results in `docs/EXPERIMENTS.md`, with numbers.

## Taking a task card
Tasks live in `docs/ACTIONS.md` (IDs like `E1-01`). Before starting: restate the acceptance criteria, and say so if the card does not match the code or its dependencies are unmet. A card is done only when its acceptance criteria have evidence and the Definition of Done in that file holds. Accepted architecture decisions are in `docs/adr/` (0001-0008: stable asset IDs, SI units and a frames convention, an edit-operation log as the source of truth, determinism/snapshots/provenance/cache, a world/entity model with a PhysicsBackend boundary, Arrow/Parquet + glTF data formats, JSON Schema `x-` annotations as the property system plus a versioned plugin API, text project folders and i18n). The engine is called Beest Engine.
- Anything user-visible goes through i18n message keys (`t("area.name", {params})`, catalogs in `apps/web-demo/src/i18n/{zh,en}.json`, ICU syntax, both languages in the same change). `scripts/check_no_hardcoded_cjk.py` fails CI on hard-coded CJK literals; for module-level label tables store the key and call `t()` in the template so the language switch is reactive.
- Never publish (npm, Pages, blog, print exports) without the user's confirmation.
