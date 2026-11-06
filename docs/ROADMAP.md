# Roadmap

## 当前里程碑：全层面加固（2026-11-03）

用户目标：让基础算法、全流程、仿真可信度、优化、新能力与真实世界证据各层面都达到扎实程度。验收卡见 [ACTIONS.md 的 H 加固计划](ACTIONS.md#h-全层面加固2026-11-03)。以下项目全部有证据才算整体完成；局部修复、原型、测试数量或诚实标注不能替代完整交付。

- [x] H0：统一当前架构、任务状态、证据与限制，历史记录保留但不混作当前验收。2026-11-04检查点及逐卡入口见 ARCHITECTURE 的验收台账、EXPERIMENTS §58；后续实现变化须继续维护。
- [x] H1：修复分叉隔离、图鉴流程、校准回写/出处、算法升级后的缓存失效及干净环境安装，关键用户旅程有回归测试。六张卡的范围与证据见 ACTIONS H1、EXPERIMENTS §45/§47/§49/§53/§55；不代替 H2–H5 的完整验收。
- [x] H2：按已接受的 ADR-0012，原 64 样本全量审计零失败且零未验证，原数值门槛及历史记录保留，金标与慢测试通过；修订后的风驱动优化有多种子/双求解器稳定性证据（H2-01 与 H2-02 已达标验收，见 ACTIONS.md 与 EXPERIMENTS §79/§80）。
- [ ] H3：Rust 双端正式接入（H3-01 已验收）；气动机械能量与状态闭环（H3-02 已验收）；数字孪生、真实风场及多人海滩按各自契约集成。
- [ ] H4：取得可追溯的外部数据，校准在独立留出数据上报告误差；所支持的物理量逐项判定，不能由几何证据替代动力学证据。
- [ ] H5：核心/跨端契约、浏览器旅程、视觉回归和性能基准进入可重复检查，原有功能与中英界面无回归。

执行顺序：先 H1 的确定缺陷和 H2 的基线实验，再完成系统集成与外部验证。缺数据的项目保留未完成；对外发布仍需用户确认。下文旧里程碑的勾选只代表当时记录的范围，不自动满足本轮验收。

当前17张卡中14张已验收，2张进行中、1张待开展；这不是工期比例。主线 H2-01 与 H2-02 已达标验收：§80完成 K2 接触柔度与 CFM 阻尼平滑映射，根除第61/20号微米共面双足静摩擦楔死并在全时间步下收敛；接通 ADR-0012 独立动力学验证器对拍 MuJoCo ↔ K2 队列，实现 64 passed / 0 failed / 0 unverified（未验证清零，中位偏差 3.17%）；§79 完成 10 个优化种子双求解器稳定性复验（按门槛诚实裁定 UNSTABLE，输出 verified_winners 为空）；§78/§80 完成 H3-02 气动机械双向闭环、显式壁温热容 ODE（能量账残差 < 1e-7 J）与 Web 遥测回放。§81/§82 完成 H3-04 与 H3-05 风驱动海滩真实风场（KNMI-215 CC0）离线插值重放与多人在线权威沙盒系统（/ws/beach 会话隔离、所有权归属校验、并发控制与断线重连）。§71/§78 完成 H4-01 中速工况库仑摩擦与力传感器零漂诊断，真实外部标定推进中。

§73–§76修复K2时间步、球足运动、离散功、惯性及耦合接触。§77补齐原生与浏览器的逐步支撑/峰值观测，修复日志采样改变验收结果的缺陷；原始轨迹和旧失败保留。§78完成浏览器端（`packages/sim-web`）完整 v2 审计策略对齐，证明K2第61/20号部分步长停滞源于刚性无柔度接触在双足共面交接处的静摩擦楔死（`0.3496 N·m > 0.30 N·m`），在 `observation-v3` 下将64样本K2与MuJoCo队列统一更新为0通过、0失败、64未验证（双求解器64样本中位步幅偏差4.21%，第61号偏差4.59%），完成H4-01中速工况库仑摩擦与力传感器零点漂移（中位 `0.031 N`，占满量程 `0.046%`）定量诊断，并将气动网络双向闭环（打气储能、无风储气行走、水感/沙锚反射、快照恢复）接入 `runner.py`。接触柔度/独立动态验证适配器、容器壁热耦合及外部传感器零漂标定仍缺，H2–H5目标保持开放。

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

## M6 — 系统演进与原生内核（System Evolution & Unified Core）

> 2026-11-03 复核：下面保留目标原文。Arrow 和实例化渲染已有实现；Rust/PyO3/WASM 已进入真实业务路径，跨端、性能及干净容器证据见 EXPERIMENTS §49。端到端零复制、零GC和绘制预算仍无完整验收证据，分别按 H3-01/H5-02 验收，不能把接入成功等同于性能目标完成。
- [ ] **M6-01 端到端 Arrow/Feather IPC 流式管道**：API 增加 `/runs/{rid}/telemetry.arrow` 二进制流；前端引入 `apache-arrow` 直接将 `Float32Array` 绑定至 WebGL，废除 JSON 文本与大对象堆分配开销。
- [ ] **M6-02 Three.js 现代化渲染管线**：连杆、障碍物、流线、足迹全面改用 `InstancedMesh` 归并（全局 Draw Call 压降至 10 次内）；引入帧间 Slerp/Lerp 平滑插值消除高刷屏机械微抖动；渲染循环预分配池化实现零 GC。
- [x] **M6-03 统一 Rust 内核原型（ADR-0009 beest-kernel）**：用 Rust 重写平面阿苏尔杆组运动学求解、步态评估与守门校验；编译为 PyO3 轮子与 WebAssembly 字节码，收敛跨语言重复模块。

## M7 — 形态计算与气动大脑（Morphological Computing & Pneumatic Brain）

> 2026-11-04 复核：§66修复独立气体网络的能量传输和泵反力符号，增加显式热/焓/功账；主仿真中的双向机械耦合、统一能量账、状态恢复和真实运行遥测闭环仍待 H3-02，不能以元件测试代替。
- [ ] **M7-01 气压逻辑回路与打气储能**：一维可压缩流体压力节点网络；腿部曲柄往复气泵向 PET 瓶储能；双稳态气动逻辑阀门（Flip-Flop）与二进制步数计数器。
- [ ] **M7-02 潮水自救与暴风沙锚反射**：水感管触水负压突变触发倒车换向；倾覆与强风冲击下自动打入沙钉自锁。
- [ ] **M7-03 气动遥测流与 Web 3D 可视化覆盖层**：Arrow 列式 IPC 流增设气压、负压与阀态通道；Three.js 实时渲染 PET 气瓶储压变色、潮水透明海平面、触水发光探针与防风暴沙锚击发。

## M8 — 开放式演化与数字海滩（Quality Diversity & The Digital Beach）

> 2026-11-04 复核：图鉴当前设计→演化→切片→加载已通过 H1-02；校准参数已接入实际 MuJoCo 前向模型并可由 Profile 应用到新运行，实验及负结果见 EXPERIMENTS §55。真实视频的完整反演、材料柔度、实测留出验证、真实风场与多人同步仍未完成。以下目标原文不缩减，分别由 H1-02/H3-03/H3-04/H3-05 验收；图鉴输出仍不代表优化排名已获物理验证。
- [ ] **M8-01 质量多样性进化（MAP-Elites）**：构建二维行为特征网格（抬腿越障高度 vs 迎风倾覆裕度/比能耗）；演化自适应物种图鉴库。
- [ ] **M8-02 视觉测功机数字孪生闭环**：实机行走视频多铰链反光点追踪；相机内参标定；贝叶斯反演实测材料柔度、轴套摩擦与沙地刚度。
- [x] **M8-03 多人实时“数字海滩”沙盒**：基于真实海滩风场数据的多人在线无边界沙盒，多兽角逐、推挤避障、群体协同。
