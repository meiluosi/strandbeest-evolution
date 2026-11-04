# 契约语料库

放**所有对应实现都必须通过**的数据，包括运动学、资产/编辑/适应度、MJCF、运行、事件和金标。`kinematics/` 包含连杆设计、关节位置采样点和步态指标；`kernel-boundaries.json` 补充无效输入边界。
TypeScript 和 Python 运行器读同一批文件；正式运动学路径现已调用同一 Rust 内核，隔离的 reference 实现用于核对。这是跨端一致性与几何不变量证据，不能把两个绑定计作两个独立物理求解器。

- 期望值由 Python 求解器生成（`generate_kinematics.py`），再用**与实现无关的不变量**独立检验：每个关节到它两个圆心的距离等于给定的杆长。所以语料库不只是"两个实现互相一致"，而是"都满足几何定义"。
- 容差写在每个文件里（`tolerance`）。
- 为什么有它：ADR-0009 的边界和 reference 对照依靠它检查各端是否漂移；当前实施记录见该 ADR 的 H3-01 小节。

## sim-mjcf

`sim-mjcf/cases-contact-v3.json`：Python 的 MJCF builder 对一组设计和覆盖项生成的完整 MJCF 文本与建模事实（`generate_sim_mjcf.py` 生成）。`packages/sim-web` 必须逐字节复现。builder、`scenario_from_design`、地形或 `contracts/scenes.json` 有意改动后，运行 `.venv/bin/python contracts/generate_sim_mjcf.py` 重新生成，然后用 Biome 格式化产物。

`sim-run/cases.json`：Python 跑出的短运行（稳定期加零点几圈：平地、台阶、坡、软地面），含曲柄序列、回放帧（位姿、足端接触、受力、质心）、回放场景和步态指标，未取整。`packages/sim-web/src/run.test.ts` 在 MuJoCo WebAssembly（浏览器3.14.0；本轮Python3.17.0，版本差异仅在已跑语料范围内核对）上跑同样的场景，要求在回放取整精度内一致。用 `PYTHONPATH=packages/common/src:packages/sim/src python contracts/generate_sim_run.py` 重新生成（需要时指向对应工作区的源码）。

`sim-run/cases.json` 现在还含审计：事件、诊断、能量面板序列和全部指标（含能量账）；多了 4 个不带帧的审计用例（卡住的台阶、扭矩上限、软地面下陷、松弛环路）。`sim-events/cases.json`：18 个手工构造的运行结果，让 `events.py` 的每条规则都触发，包括风帆和阵风分支；用 `.venv/bin/python contracts/generate_sim_events.py` 生成。

`sim-run` 还含 4 个风帆用例（定常风、阵风、风突然停、微风起不来），它们同时检验 `drives.py` 的 SailDrive 和 `winds.py`。

### 当前使用的版本（2026-11-04）

上述 `sim-run/cases.json` 描述保留旧语料背景。当前测试读取 `sim-run/cases-contact-v3.json` 和 `sim-golden/runs-contact-v3.json`；能量/时间对齐修订见 EXPERIMENTS §48，接触阻尼修订见 §59。金标生成器逐一重放历史输入，不能用当前默认值重建设定。旧 JSON 保留审计，不覆盖为新结果。`duplicated-modules.json` 仍保留10个历史登记项，其中运动学/步态业务已转共享 Rust；条目数不代表仍有10套独立数值内核。

接触v3的38/13/10个语料前后差异与输入不变检查见 `experiments/hardening-contact-v3-contract-diff-2026-11-04.json`。停滞微小转角的跨端比例比较采用有单位的位移/功/角度界限；其余比较不变，具体界限、错误对照和初始失败见 EXPERIMENTS §59。

`sim-run/signed-energy-v3.json` 补充原G1第11号样本的真实原生/API记录：外力净功为负时仍计算能量守恒，保留功与比例的符号；只在净功绝对值接近零时不定义比例。该语料含原始输入、原生数组和API回放，WASM沿用原有误差界限对拍；仅开启帧记录，原有指标不变。生成入口为 `packages/sim/scripts/hardening_signed_energy_fixture.py`，拒绝覆盖文件。原38/13/10项语料未重写；说明及独立解析负功实验见 EXPERIMENTS §62。

`stride-reference/cases.json` 是独立的**理想几何诊断**语料：G1第20/53/56/61号的期望值来自共享Rust实现之前保存的Python端点/所属杆转角积分，输入的足端所属杆另与实际MJCF核对。Rust还有闭式椭圆积分、不相容支撑、零/极小步幅、角度展开及非有限数检查；Python/WASM读取这四例做绑定回归。完整64例、720/1440/2880分辨率对照由 `packages/sim/scripts/hardening_g1_kernel_reference.py` 驱动（调用 `scripts/compare-stride-kernel.ts`），拒绝覆盖输出。它不改原G1门槛，也不把共享内核的两个绑定当作独立物理求解器；结果与限制见 EXPERIMENTS §64。
