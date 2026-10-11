# 契约语料库

放**所有实现都必须通过**的数据。目前只有运动学（`kinematics/`）：一批连杆设计，加上期望的关节位置采样点和步态指标。
TS 实现（`packages/core`）和 Python 实现（`packages/common`）各有一个运行器，读同一批文件；**新增一个文件就自动成为两边的测试**。

- 期望值由 Python 求解器生成（`generate_kinematics.py`），再用**与实现无关的不变量**独立检验：每个关节到它两个圆心的距离等于给定的杆长。所以语料库不只是"两个实现互相一致"，而是"都满足几何定义"。
- 容差写在每个文件里（`tolerance`）。
- 为什么有它：ADR-0009 的触发线要靠它来检查两种实现是否漂移。

## sim-mjcf

`sim-mjcf/cases.json`：Python 的 MJCF builder 对一组设计和覆盖项生成的完整 MJCF 文本与建模事实（`generate_sim_mjcf.py` 生成）。`packages/sim-web` 必须逐字节复现。builder、`scenario_from_design`、地形或 `contracts/scenes.json` 有意改动后，运行 `.venv/bin/python contracts/generate_sim_mjcf.py` 重新生成。

`sim-run/cases.json`：Python 跑出的短运行（稳定期加零点几圈：平地、台阶、坡、软地面），含曲柄序列、回放帧（位姿、足端接触、受力、质心）、回放场景和步态指标，未取整。`packages/sim-web/src/run.test.ts` 在 MuJoCo WebAssembly（同为 3.14.0）上跑同样的场景，要求在回放取整精度内一致。用 `PYTHONPATH=packages/common/src:packages/sim/src python contracts/generate_sim_run.py` 重新生成（需要时指向对应工作区的源码）。

`sim-run/cases.json` 现在还含审计：事件、诊断、能量面板序列和全部指标（含能量账）；多了 4 个不带帧的审计用例（卡住的台阶、扭矩上限、软地面下陷、松弛环路）。`sim-events/cases.json`：18 个手工构造的运行结果，让 `events.py` 的每条规则都触发，包括风帆和阵风分支；用 `.venv/bin/python contracts/generate_sim_events.py` 生成。
