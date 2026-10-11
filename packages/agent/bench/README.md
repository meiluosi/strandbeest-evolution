# Design benchmark v0 (A-04)

An agent gets a **task** (intent, visible scenes, budget) through the tool surface (`strandbeest-mcp`, [../../../docs/AGENT-TOOLS.md](../../../docs/AGENT-TOOLS.md)), edits a design with operations, and may simulate only the visible scenes. When it stops, its design is scored on **blind scenes** (`blind-scenes.json`) that no tool, prompt or workspace file reveals.

Score = relative improvement of the blind metric over the starting design (capped at +2). It is **0** when the design is invalid (guard), outside the allowed envelope (leg count, topology, every length within 0.7-1.4x the original), or when the simulator skeptic distrusts any blind run (open loop, deep sinkage, energy that does not close, ...). The starting design scores exactly 0.

Anti-gaming checks (tests/test_bench.py): blind names appear nowhere an agent can read; non-visible scenes are refused; invalid or out-of-envelope designs score 0 without simulating; a distrusted run scores 0.

The budget is counted in simulation runs and operations only, never in wall-clock seconds (the tool surface's 600 s default is switched off here), so a score does not depend on how fast or how loaded the machine is.

Baselines (same tools, same budget of 6 simulations and 40 operations; `baselines.json`): random bounded edits, greedy hill climbing, CMA-ES on the free kinematic fitness then keep-if-not-worse. Regenerate with `python bench/run_baselines.py` (about 20 minutes on an idle machine at the old 0.2 ms time step, about an hour at the current 0.1 ms). The numbers and what they mean are in docs/EXPERIMENTS.md section 18.
