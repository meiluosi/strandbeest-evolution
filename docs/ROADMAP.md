# Roadmap

## MVP walking skeleton (done, thin)
- [x] `schemas/`: Design, Measurement, Profile, Run (JSON Schema, examples, TS + Python contract tests)
- [x] `packages/common`: Design model, linkage solver, gait metrics (Python port checked against core)
- [x] `packages/fab`: bars/crank/frame, layer assignment (collision-free over the crank cycle), printability checks, STL + BOM + assembly notes + zip
- [x] `packages/sim`: Design → scenario (printed-bar mass from material), small-walker settings
- [x] `packages/calib`: Measurement import, compare, fit, Profile; recovery tested on synthetic data
- [x] `apps/api`: validate / evaluate / export / run jobs / series; `strandbeest-pipeline` one-command CLI
- [x] `apps/web-demo`: Fabricate panel (evaluate, printability + download, simulate) wired to the API
- [x] Fab depth: gripping crank arms + phase jig, spacers/washers computed per axle, standoffs, motor bracket and shaft coupler (N20-class motor assumed), more checks
- [x] Front end: four tabs (design, fabrication, simulation, lab), design save/load/import/export, run history with overlay, part outlines, measurement import (CSV/JSON), measured-vs-simulated comparison, calibration from the UI; torque reported as a range
- [x] P4: SQLite job queue (persistent, progress, cancel, restart recovery), run index, parameter sweeps (grid up to 60 points, linked paths), STL endpoint, 3D assembly/part preview (three.js), UI refresh with design system, `docker compose` (see docs/DEPLOY.md)
- [x] P5 tooling: `hardware/` (rig design, calibration procedures, experiments E0–E4, lab notebook), ESP32 firmware (logic host-tested; Arduino glue NOT compiled or run on hardware), `packages/rig` (raw CSV → Measurement with quality report, ArUco video tracking, torque calibration, serial logger, virtual rig), `/rig/convert` API and Lab-tab import
- [x] Scenes and replay: terrains, environment (planets), winds, sail drive, motor torque limit, recorded frames, 3D replay player with synced charts and a progress-efficiency check; corrections to the simulator recorded in EXPERIMENTS §9
- [ ] First real measurements (needs a printed walker and the rig)
- [ ] Known thin spots: no auth; geometry for the motor/coupler is an unverified assumption until printed; torque is a range (EXPERIMENTS §8)

> **Task cards (what to do next, with acceptance criteria): [ACTIONS.md](ACTIONS.md).** Engine-style architecture blueprint (what to settle before building more) and the decision records: [ENGINE.md](ENGINE.md), [adr/](adr/). Longer-term product shapes and the design of the editor, glass-box simulation, AI-native layer and algorithm map: [VISION.md](VISION.md) (second version). Platform-level plan (phases P0–P7 with exit criteria): [PLATFORM.md §9](PLATFORM.md). The milestones below (M0–M5) are the research track and feed into those phases.

## 方向（2026-10-11 决定）：风驱动原教旨 + 证据优先的仿真

- **定位**：一个证据分级的 Strandbeest 仿真平台。能量只来自风（电机只作测试台），每个数字带证据等级 E0–E3。详见 [WIND.md](WIND.md)、[VALIDATION.md](VALIDATION.md)。
- **接受的现实**：没有 3D 打印设备，E3（自己的实测）暂时为空。检验靠独立求解器 K2、文献数据、公开视频、社区数据。制造（F 卡）冻结，只保留导出。
- **旗舰问题**：只靠风的走兽，起步最少要多大的风？低于多大的尺寸走不动？

### 总体目标（可检查）

| 目标 | 检查方式 | 阶段 |
|---|---|---|
| G1 仿真可信 | 随机走兽审计在 64 个样本上失败 0 个；基准基线在新时间步下重跑 | A |
| G2 有独立证据 | K2 与 MuJoCo 在慢速平地步幅一致到约定容差；Jansen 足端轨迹与已发表数据对照；每个旗舰结果带证据等级 | B |
| G3 风驱动结论带区间 | 起步风速给出对假设参数的敏感性区间；"起步风速随尺度"曲线含"走不动"的尺度 | B、C |
| G4 优化懂风 | 优化目标含起步风速和阵风稳健性；排名通过稳定性检查才被采信 | C |
| G5 能公开 | 静态网页带证据徽章；一篇方法与负面结果并重的技术报告（发布前须你确认） | D |

### 阶段

| 阶段 | 内容 | 任务卡 | 出口 |
|---|---|---|---|
| **A 地基清理** | 查第二种闭环张开机制；重跑基准；修适应度 NaN 差异；能量来源声明；销轴摩擦命名参数 | S-07、Q-05、Q-06、W-01、W-02 | G1 |
| **B 证据层** | 证据等级字段；Jansen 几何对照；K2 独立求解器；起步风速查找器与敏感性；排名稳定性 | V-07、V-01、V-02、W-03、V-04 | G2、G3（部分） |
| **C 风驱动与优化** | 风场 v2；虚拟测力计；机体风阻；旗舰实验；帆参数进优化 | W-04、W-06、W-10、W-05、W-08 | G3、G4 |
| **D 公开** | 静态网页（R-02）、证据徽章、技术报告、社区数据入口 | R-02、V-06、R-03 | G5 |
| **E 条件项** | 沙地、气动储能、3D、柔性；有 E3 数据后再校准 | S-03、W-09、S-05、F-07 | 取决于数据 |

下面是更早的阶段表，保留作历史。

| phase | goal | status |
|---|---|---|
| P0 foundations | core, demo, sim S1, docs | mostly done |
| MVP walking skeleton | schemas, fab export, thin API, front end, calibration on synthetic data, one-command pipeline | **done (thin)**, see below |
| P1 trustworthy sim | contact study, timestep convergence | **done**: findings in EXPERIMENTS §8; torque level remains model-dependent |
| P2 front end + P3 fab depth | tabs, history, lab, outlines; crank arms, jig, spacers, motor bracket, coupler | **done (first version)**; P3 print feedback pending |
| P4 local backend deepening | persistent job queue, cancel, sweeps, docker compose | **done (first version)**, see docs/DEPLOY.md |
| P5 test rig + first data | hardware/, measurement tooling | **tooling done (first draft, untested on hardware)**; real data **pending your build** |
| P2 static viewer + design save/load | run viewer and designer without a backend | |
| P3 fab MVP | printable single leg, you print it | |
| P4 local backend | FastAPI + jobs + storage | |
| P5 test rig + first data | measurements | |
| P6 calibration + extended sim | calib, S2–S4, multi-fidelity evolution | |
| P7 public release | hosted/WASM, docs site, design library | |

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
- [x] Inertia (reduced-order 1-DOF time-domain model: start-up, ripple, coasting; no impact loss, no slip) — see docs/EXPERIMENTS.md §5
- [x] Torque-aware objective (`fitnessWindSpeed`) — see docs/EXPERIMENTS.md §4
- [ ] Optional: pneumatic storage model (bottle + piston pump)

## M4b — MuJoCo simulator (packages/sim, design in docs/SIM-DESIGN.md)
- [x] S1: planar builder, motor drive, flat/slope, metrics, CLI, cross-check script
- [x] Contact-model study and timestep convergence (EXPERIMENTS §8); torque level stays dependent on friction regularisation, report as a range until measured
- [ ] Explain why leg mass raises mean torque; fix the small walker's stiff-loop instability; torque range reporting in the API/UI
- [ ] S2 sail + wind; S3 leg mass/joint friction sweeps; S4 sand (RFT); S5 wind on tubes/body; S6 flexibility, 3D (see SIM-DESIGN.md)
- [ ] Measured data from a small physical model

## M5 — Writing & outreach (blog repo)
- [x] Series drafted (zh): evolution history / leg geometry / re-evolving it (blog drafts, `draft: true`)
- [x] English versions drafted
- [x] Bilingual README, demo GIFs
- [x] Verify the evolution timeline against strandbeest.com (done except Pregluton, whose page was empty)
- [ ] Publish: enable GitHub Pages (workflow `pages.yml` is manual), npm publish, flip `draft` to false
