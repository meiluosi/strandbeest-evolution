# Design benchmark v0 (A-04)

An agent gets a **task** (intent, visible scenes, budget) through the tool surface (`strandbeest-mcp`, [../../../docs/AGENT-TOOLS.md](../../../docs/AGENT-TOOLS.md)), edits a design with operations, and may simulate only the visible scenes. When it stops, its design is scored on **blind scenes** (`blind-scenes.json`) that no tool, prompt or workspace file reveals.

Score = relative improvement of the blind metric over the starting design (capped at +2). It is **0** when the design is invalid (guard), outside the allowed envelope (leg count, topology, every length within 0.7-1.4x the original), or when the simulator skeptic distrusts any blind run (open loop, deep sinkage, energy that does not close, ...). The starting design scores exactly 0.

Anti-gaming checks (tests/test_bench.py): blind names appear nowhere an agent can read; non-visible scenes are refused; invalid or out-of-envelope designs score 0 without simulating; a distrusted run scores 0.

Baselines (same tools, same budget of 6 simulations and 40 operations; `baselines.json`): random bounded edits, greedy hill climbing, CMA-ES on the free kinematic fitness then keep-if-not-worse. Regenerate with `python bench/run_baselines.py` (about 20 minutes). The numbers and what they mean are in docs/EXPERIMENTS.md section 18.
