# 技术报告：只靠风，一只走兽要多少风？

# Technical Report: How Much Wind Does a Wind-Only Walker Need?

> **状态**：2026-10-28 发布版本的工作区修订稿（2026-11-04 核对）。正文实验数值保留各自的历史版本与适用范围；当前状态以本页更正、[ARCHITECTURE.md](ARCHITECTURE.md) 和 H 任务卡为准。更正尚未同步发布到博客；发布须用户确认。
> **Status**: local revision checked on 2026-11-04. Historical experiments retain their original scope and versions; the updates here and the architecture/task ledger describe current status. No corrections have been republished.

> **2026-11-04 软件补充**：校准已接入实际 MuJoCo 场景，完整测量出处、Profile 应用和中英文浏览器流程已打通；六组短时合成实验含无法辨识及代理模型失准的负结果，见 [EXPERIMENTS.md](EXPERIMENTS.md) §55。它们没有补上本文的实测证据缺口，本文原数值未据此改写。
> **Software update, 2026-11-04:** physical calibration and Profile application now use the actual MuJoCo scenario. Six short synthetic cases include unidentifiable parameters and the historical failed emulator check (§55); current-model refits are retained separately in §59; these do not establish physical validation or revise this report's historical numerical results.

> **当前审计**：用户接受 ADR-0012 后，§72将版本2审计接入原生API/Agent；对原192条结果重审为 **0通过、10失败、182未验证**，旧版 **10/3/3** 失败逐条保留。新参考须核对适用条件，缺少完整轨迹或独立对照不能通过；数值阈值和物理默认参数未改。此次重审没有重新运行192次动力学。旧风速阈值和优化排名仍待H2-02复核；气动闭环、真实风场/多人海滩、外部动力学验证及完整性能预算尚未验收。
> **Current audit:** accepted ADR-0012 is implemented in the native API/Agent audit policy. Re-auditing 192 saved results gives 0 passes, 10 failures and 182 unverified outcomes; every legacy finding (10/3/3 failed cases) is preserved. Missing applicability or independent evidence cannot pass. Numeric thresholds and physical defaults are unchanged; this is a posthoc audit, not 192 new dynamic runs. Physical validation, integration and performance work remain open.

> **§64补充**：有向步幅的理想几何诊断已统一到Rust，原64例的Python/WASM及三种分辨率对照通过；它未替换原验收参考，候选第61号仍与理想预测相差135.56%。/ The shared signed geometric diagnostic agrees across all 64 inputs, both bindings and three resolutions; it leaves the original audit intact, and candidate case 61 still differs from its ideal prediction by 135.56%.

> **§65–66补充**：16组接触敏感性实验仍未修复第61号，NoSlip使其停滞，未推广新默认值。另修复了独立气体网络中不同温度节点传输能量的错误、恒温一致性和泵反力方向；新增热/焓/功账不等于整机储气驱动已实现，更不构成实测验证。/ Sixteen contact trials did not resolve case 61; NoSlip stalled it and no default was promoted. Standalone gas-energy transport, isothermal consistency and pump-reaction signs are repaired. The new heat/enthalpy/work ledger does not establish integrated pneumatic walking or physical validation.

> **§68–69补充**：共享场景现可显式指定求解精度，396项JS/1058项常规Python及完整检查通过。另16组实验中，收紧求解精度不改变步幅，较硬约束使第61号恢复正向；原步幅审计仍失败，未推广默认值。曲柄完整论文核到惯量但原文单位有疑点，未产生实测校准结论。/ Solver precision is now explicit in Scenario; 396 JS and 1,058 regular Python tests and full checks pass. Sixteen additional trials isolate compliance effects; case 61 still fails the original stride audit. The crank paper supplies an inertia value with an unresolved printed unit, not an accepted calibration result.

> **§70–71补充**：32组步长/刚度细化确认数值稳定不等于模型准确，未推广默认值。公开曲柄数据已取得32份，作者代码补齐单位、力坐标和分组依据；16份独立留出总体误差下降94.7%，但两个中速工况仍失败，未作为走兽校准或实测验收。/ Thirty-two refinement trials preserve unresolved model/reference discrepancies. Thirty-two public crank records and pinned author code now support an independent 16-trial holdout. Pooled velocity error falls 94.7%, but medium-speed adequacy fails; no walker calibration or physical acceptance is claimed.

> **§73补充**：K2此前忽略场景时间步，并漏掉球足随所属杆件转动的接触速度；现已修复，原64样本4,096相位的接触运动核对通过。四个难例的最终能量残差仍为31.56%、101.61%、43.62%、13.38%，均超过2%门槛；不能接受为独立动力学验证。/ K2 now executes the recorded Scenario timestep and includes sphere-owner rotation in contact velocity. All 4,096 kinematic probes across the original 64 inputs pass, but all four dynamic diagnostic cases still fail the 2% energy audit. No independent dynamics acceptance follows.

> **§74补充**：K2离散驱动功、法向碰撞和切向冲量记账已修复。原64样本全量复跑无数值检查失败，最大能量残差0.458%；完整审计仍为0通过、0失败、64未验证。四个难例的运动轨迹未改变，第61号与理想参考的步幅差异仍为84.66%。积分误差单独记录，不抵消残差；完整惯性、接触机制与独立验证仍缺。/ K2 discrete work accounting is repaired. All original 64 cases complete without numeric-check failures (maximum energy residual 0.458%), but all remain unverified in audit v2. Motion is bitwise unchanged in the four paired diagnostics; case 61 still differs from the ideal stride by 84.66%. Integration error is diagnostic only; full inertia, contact adequacy and independent validation remain open.

> **§75补充**：K2已补齐逐杆惯性、重力和运动耦合，4,096次独立惯性组装及6,144次接触运动核对通过；六处初版插值失败保留。最终原64样本复跑无数值检查失败，最大能量残差0.769%；完整审计仍为64未验证。第61号理想步幅差异由84.66%降至33.36%，仍需接触模型核对与独立动力学证据。/ K2 now includes configuration-dependent rigid-body inertia, gravity and coupling. All 4,096 independent inertia-assembly probes and 6,144 contact-motion probes pass; six initial interpolation failures are retained. The final original 64-case run has no numerical-check failures (maximum energy residual 0.769%), but all cases remain unverified. Case 61's ideal-stride difference falls to 33.36%; contact adequacy and independent dynamics validation remain open.

> **证据边界**：**下文的走兽性能数值来自本仓库的仿真器（MuJoCo，以及独立实现的平面求解器 K2），没有来自实物走兽的验收结果。** §71另有公开曲柄实测对照，但工况失败和标定误差缺口仍在；项目验收通过的E3结果仍为空（见 [VALIDATION.md](VALIDATION.md) §2、§3）。下文按该文件的E0–E3给结论标等级。

**图例 / Legend**

| 标记 | 含义 |
|---|---|
| **模型内**（model against model） | 数字由本仓库的仿真器算出，最多与另一个模型或文献对照过；**没有实物** |
| **实测** | 数字来自可追溯的真实测量；已有公开曲柄对照，尚无验收通过的走兽实测结果 |
| **E0 / E1 / E2 / E3** | 证据等级，定义见 [VALIDATION.md](VALIDATION.md) §2 |
| **§N** | 数字的出处：[EXPERIMENTS.md](EXPERIMENTS.md) 的第 N 节（那是原始记录，本文是建立在它上面的论证） |
| **假设** / `[unverified]` | 这个值是猜的，来源已写明或标记为未核实 |

> **§76补充**：K2迭代预算和耦合接触求解已修复，64个最终冻结状态通过独立单步核对。原64样本审计为0通过、1失败、63未验证，最大能量残差0.768%。第16号支撑失败受日志采样影响（5.58%对逐步3.10%），原记录保留；第61号在0.025 ms诊断中未完成，不能宣称时间收敛或动力学验证通过。/ K2 now executes the recorded iteration budget and solves coupled contact modes; 64 final frozen states agree with independent mode enumeration. The original cohort remains 0 passed / 1 failed / 63 unverified. Case 16 reveals logging-cadence bias; its failure is preserved. Case 61 does not finish the 0.025 ms diagnostic, so dynamic convergence and validation remain open.

> **§77补充**：逐步支撑/峰值证据已贯通原生、浏览器、保存和重审，修复日志采样造成的判定差异。40次对照保留旧运动轨迹和全部失败，仍未取得完整64样本或独立动力学验收。/ All-step support and peak evidence now survives native/browser execution, storage and re-audit. Forty comparisons preserve prior motion and failures; full-cohort and independent dynamic acceptance remain unmet.

---

## 0. 摘要 / Abstract

### 0.1 中文摘要

**问题**（[WIND.md](WIND.md) §1）：一只**只靠风**的走兽——帆提供能量，重力可以帮忙，不用电，不用预先上紧的弹簧——**起步最少要多大的风？低于多大的尺寸它走不动？**

**为什么答案不显然**：风对帆的力正比于面积（L²），重量正比于体积（L³），销轴摩擦随法向力增长。**指数的符号决定一切**：大机体可以更有利，也可以更不利，所以这个问题不能靠直觉回答，只能靠仿真；而仿真的结论又会落在几个"没人测过"的假设参数上。

**做法**：一个证据分级的仿真平台。声明式连杆规格 → 解析运动学 → `PhysicsBackend` 边界下的两个物理后端（MuJoCo，以及一个**不共享任何接触或约束代码**的独立平面刚体求解器 K2）→ 场景文件（世界 + 实体）→ E0–E3 证据等级 → 每次运行留一份原始 JSON 的实验日志。旗舰实验在看到数据**之前**先写死了尺度的预测公式和指数符号（[EXPERIMENTS.md](EXPERIMENTS.md) §36 §3），之后跑了 30 个格子（含临界情形 p = 2，实测斜率 −0.033 对预注册的 0.000），并留了一条带日期的更正记录。

**头条答案（每条带证据等级）**

1. **运动学文献验证尚待补证（§30、§46）**：旧版 E2 结论撤回。用于对照的 24 点及精确步长/步高缺少可复核的原图、坐标标定和提取记录；保留历史数值，但不能据此宣称与发表实验一致。
2. **步幅站得住（E1，§31）**：两个**互相独立**的求解器在慢速平地步幅上差 **0.58 %**（MuJoCo 0.2760 m/rev，K2 0.2776 m/rev）；起步风速在 15 s 判据下差 4.4 %。但要当心：**"起步风速的量级"到 E1，"门限在 0.50 m/s"这句话不是 E1**（两个 5 % 区间在 L = 1 处完全分开）。
3. **旗舰结论是负面的（E0，§36）**：在同一台机器上，只把"每个销轴的摩擦"这个**没人测过的假设**从 0 改到 0.002 N·m，起步风速就变 **2.59 倍**（L = 1：0.50 → 1.30 m/s）。"低于某个尺寸走不动"这条边界**真实存在**，但它是**摩擦假设划出来的，不是尺度划出来的**：在该假设下最小可行尺度是 **L ∈ (0.03, 0.1]**（上下界都有），而在理想销轴下测到的最小尺度只要 0.80 m/s 就起步。
4. **尺度曲线是非单调的（E0，§36）**：质量指数 p = 3（实心体）时曲线是**非单调的 V 形**，最小值在 L ≈ 0.6（0.415 m/s）；p = 1（薄壁）时是"越大越省风"（L = 0.35 要 0.80 m/s，L = 3 只要 0.39 m/s）。这**否证**了 [WIND.md](WIND.md) §3 里"大机体对风更有利"的说法。
5. **E3 层是空的（§36 §11、§39 §7）**：本项目尚无通过验收的扭矩/起步实测验证。已取得公开四连杆原始电流/运动候选，另有走兽实验论文，但标定、误差或原始记录仍不齐，未完成独立留出比较，见 [RESEARCH-NOTES.md](RESEARCH-NOTES.md)。
6. **让帆参与优化没有带来好处（E0，§40）**：把帆面积与传动比做成基因之后，在同权重、同预算下**固定帆在起步风速、阵风稳健性、名义距离三项上全赢**自由帆（低 4.4 %、高 11.8 %、高 29.4 %）。而且这条排名只有一个求解器、一个种子、2 代预算，优化循环里用的廉价代理**把排名弄反了**（ρ = 0.303）——所以它连"排名结论"都算不上，只能算机制演示。

**当前判断**：运动学的外部验证尚待补证，慢速步幅有两个独立求解器的对照；**每一个关于"风要多大""走不走得动"的结论，目前都由我们自己设定的假设参数决定，而不是由现实决定**。这份报告的价值不在于结论有多漂亮，而在于它把每一个结论的承重墙标了出来。

### 0.2 English Abstract

**Question.** A Strandbeest that walks on wind alone — sail for energy, gravity for help, no electricity and no pre-tensioned springs — how much wind does it need to start, and below what size does it stop working? The answer is not obvious: the force on a sail scales with area (L²) while weight scales with volume (L³), and pin friction grows with the normal load, so the *sign* of the exponent decides everything.

**Approach.** An evidence-graded simulation platform. A declarative linkage spec feeds an analytic kinematics layer, which feeds two physics backends behind a `PhysicsBackend` boundary: MuJoCo, and K2, an independent planar rigid-body solver that shares no contact or constraint code with it. A scenario file (world + entities) drives the run; every result carries an E0–E3 evidence level; every run leaves a raw JSON file. The flagship experiment wrote down its scale prediction — formula and exponent sign — *before* looking at any data, then ran 30 cells (including the critical case p = 2, whose measured slope of −0.033 matches the pre-registered 0.000) and kept one dated correction in the record.

**Answers, with their evidence levels.**

1. *The literature kinematics claim is pending provenance verification (§30, §46).* The former E2 upgrade is withdrawn: the retained 24 points and precise gait metrics lack a reproducible source plot, axis calibration and extraction record. Historical numerical agreement does not establish external validation.
2. *The stride holds (E1, §31).* Two independent solvers agree on slow flat-ground stride to **0.58 %** (MuJoCo 0.2760 m/rev, K2 0.2776 m/rev) and on start wind to 4.4 % under a 15 s criterion. The careful part: the *magnitude* of the start wind is E1; the statement "the threshold is 0.50 m/s" is **not** — at L = 1 the two 5 % intervals do not overlap at all.
3. *The flagship result is a negative one (E0, §36).* On the same machine, changing one **untested** assumption — the Coulomb friction of each printed pin — from 0 to 0.002 N·m changes the start wind by a factor of **2.59** (L = 1: 0.50 → 1.30 m/s). A "below this size it cannot walk" boundary does exist, but it is drawn by that friction assumption, not by scale: under it the minimum viable scale is **L ∈ (0.03, 0.1]** (bounded on both sides), while with ideal pins the smallest scale tested starts at 0.80 m/s.
4. *The scale curve is not monotonic (E0, §36).* At mass exponent p = 3 (solid body) the curve is a **non-monotonic V**, minimised near L ≈ 0.6; at p = 1 (thin-walled) bigger is cheaper in wind (0.80 m/s at L = 0.35, 0.39 m/s at L = 3). This **refutes** the "big bodies are more favourable to the wind" claim in [WIND.md](WIND.md) §3.
5. *The E3 tier is empty (§36 §11, §39 §7).* Torque, current, start wind: **no measurement exists**. The community data intake (format, validator, guide) is open; the data has not arrived.
6. *Letting the sail into the optimisation bought nothing (E0, §40).* With the sail area and gear ratio turned into genes, the **fixed** sail beat the free one on all three measures at the same weight and budget (start wind 4.4 % lower, gust robustness 11.8 % higher, nominal distance 29.4 % higher). And that ranking rests on one solver, one seed and two generations, with a cheap proxy inside the search loop that **got the ranking backwards** (ρ = 0.303) — so it is not even a ranking conclusion, only a mechanism demonstration.

**Current assessment.** External kinematics validation remains unverified; slow-ground stride has a two-solver comparison, while every statement about *how much wind* and *whether it walks at all* currently rests on assumption parameters we set ourselves rather than on reality. The value of this report is not that the conclusions look impressive; it is that it names the load-bearing wall under each one.

---

## 1. 问题与约束

### 1.1 旗舰问题

[WIND.md](WIND.md) §1 写死了一个约束：产品结论里的走兽，**能量只来自风**（以及它充进气动储能的风能），可以再加重力（坡）；不用电，不用预先上紧的弹簧。由此得到一个别人没有系统回答过的问题：

> 一只只靠风的走兽，起步最少要多大的风？低于多大的尺寸它走不动？

"起步风速"被定义成：**从静止开始，曲柄在 40 s 仿真时间内转满一整圈所需的最小定常风速**（[WIND.md](WIND.md) §5；实现见 `packages/sim/src/strandbeest_sim/startwind.py`；搜索用 2 倍括号 + 几何二分，相对精度 5 %，结果总是一个区间 `(lo, hi]` 而不是裸数字，§28、§36 §1）。

### 1.2 为什么答案不明显

因为力的标度与重量的标度**方向相反**：

- 风对帆的力 ∝ 面积 ∝ **L²**；
- 重量 ∝ 体积 ∝ **L³**（实心体；真实机体是薄壁管，指数介于 L 与 L³ 之间）；
- 销轴摩擦的标度取决于实现：[WIND.md](WIND.md) §4 说"摩擦 ∝ 法向力 ∝ 重量"，而**代码里实现的是每个销轴的绝对库仑力矩**（MuJoCo `frictionloss`），不随重量增长（§36 §3 的模型 B′）。这两种写法给出**不同的指数**，而 [WIND.md](WIND.md) §3 自己写着"这是假设，没有被检验过"。

启动瞬间曲柄静止，帆力矩 ∝ L³ v²，负载力矩 ∝ L^(p+1)（模型 A）或 L⁰（模型 B′，绝对摩擦），所以 v(L) 的斜率可以是 −0.5、0、+0.5，也可以是 −1.5。**这就是为什么这个问题必须用实验回答。**

### 1.3 两个层次，不能混

| 层次 | 能量来源 | 在本报告里的地位 |
|---|---|---|
| **风驱动**（产品结论） | `wind` | 排行榜、优化目标、报告里的结论 |
| **测试台**（仪器） | `test_rig`（电机伺服恒速转曲柄） | 用来量负载扭矩曲线 T(θ)、做仿真核对；**不当作走兽的性能** |

规则来自 [WIND.md](WIND.md) §2：测试台结果可以用来**解释**风驱动（例如"T(θ) 的峰值决定起步风速"），但不能被当成走兽的性能。本报告里凡是电机驱动的数字，都标成"测试台"。

### 1.4 诚实规则

本项目在 [WIND.md](WIND.md) §6 定了五条规则，本报告逐条遵守：起步风速必须同时给出对假设参数的敏感性区间（§3.3）；假设值改动必须同步更新敏感性表；**"不走"也是结果，必须记数字**（§3.4）；Jansen 的"约 15 km/h"是艺术家的陈述、不是测量，只作数量级检查（§5）；没有出处的数字都标待核实。

---

## 2. 方法

### 2.1 管线

一次实验从一份 JSON 设计走到一个带证据等级的结论，路径是固定的：

| 步 | 做什么 | 在哪里 |
|---|---|---|
| 1 | **声明式连杆规格**：拓扑是数据，不是代码（关节、刚性三角、曲柄、腿数与相位） | `packages/core/`，schema 在 `schemas/` |
| 2 | **解析运动学**：装配检查、分支翻转检测、足端轨迹、步态指标（步长、步高、平底占空比） | `packages/core/`，Python 对照实现 `packages/common/` |
| 3 | **物理后端边界**：`PhysicsBackend` 协议（`build/step/snapshot/restore/contacts/forces/energies/set_param`），实现有 **MuJoCo** 与**独立求解器 K2** | `packages/sim/src/strandbeest_sim/backends/k2_backend.py`；契约套件 `packages/sim/src/strandbeest_sim/contract.py` |
| 4 | **场景文件**：世界（地形、大气、风场、重力）+ 实体（连杆、驱动、机身）；驱动类型决定能量来源（`sail` → wind，`motor` → test_rig），运行指标 `wind_only` 随之而来 | 场景 schema 在 `schemas/`；场景清单在 `contracts/scenes.json` |
| 5 | **证据等级**：每个结果带 E0–E3 与依据；等级跟着**结果**走，不跟着代码走 | [VALIDATION.md](VALIDATION.md) §2；任务卡 V-07 |
| 6 | **实验日志 + 原始数据**：每张卡写进 [EXPERIMENTS.md](EXPERIMENTS.md)，每次运行留一份 JSON | `experiments/` |

这一条管线的关键设计是**第 3 步**：不是"把 MuJoCo 调得更准"，而是"换一个不共享任何接触或约束代码的求解器再来一遍"。理由写在 [VALIDATION.md](VALIDATION.md) §4：风驱动的起步阈值正好落在低速粘滑区，MuJoCo 的软化摩擦在这里最不可信；两个**独立实现**一致，比反复调同一个引擎的参数更有说服力。

### 2.2 契约语料库：两套实现怎么互相盯着

本项目有 TypeScript 与 Python 两条业务路径。2026-11-03 后运动学/步态由共享 Rust 内核提供，reference 实现单独保留；编辑、构建与运行仍需跨端契约核对。下面的语料职责沿用，当前使用的能量版本见 [contracts/README.md](../contracts/README.md)：

| 语料库 | 放什么 | 谁必须通过 |
|---|---|---|
| `contracts/kinematics/` | 一批连杆设计（标准 Jansen、长曲柄、四连杆、六杆多二元组）、期望的关节位置采样点与步态指标（带容差） | TS 与 Python 各一个运行器；新增一个文件自动成为两边的测试 |
| `contracts/fitness/` | 适应度语料（含 3 个"装得上探测角但装不上全部采样点"的基因组） | 两个实现的适应度必须逐位一致（§26 修的就是这里） |
| `contracts/sim-mjcf/` | Python 的 MJCF builder 生成的完整 MJCF 文本（34 例） | `packages/sim-web/` 必须**逐字节**复现 |
| `contracts/sim-run/` | Python 跑出的短运行：曲柄序列、回放帧、审计序列、事件、诊断、全部指标 | 浏览器里的 MuJoCo WASM（3.14.0）必须一致（§24） |
| `contracts/sim-events/` | 18 个人工构造的运行，让 9 个诊断码与 8 类事件全部触发 | 事件与诊断规则的实现 |
| `contracts/sim-golden/` | 金标运行 | 故意改一个物理参数必须报错 |

期望值不只由"对方"生成，还用**与实现无关的不变量**独立检验（每个关节到它两个圆心的距离等于给定的杆长），所以语料库证明的是"两边都满足几何定义"，不只是"两边一样"（`contracts/README.md`）。

**历史登记与当前实现分开计数**：`contracts/duplicated-modules.json` 仍有10项、上限10，保留3 → 6 → 7 → 8 → 10的历史及旧事故计数。运动学/步态两项现在调用共享 Rust；登记项数不能解释为10个仍独立实现的数值内核。原生 Python 基准有收益，Web 固定预算 GA 的 WASM 路径反而更慢，见 [ADR-0009](adr/0009-single-source-of-kinematics.md) 和 EXPERIMENTS §49。触发线检查继续运行，但这份历史计数不是“从未发生分歧”的证明。

**这套机制真的抓到过东西**：§26 的 NaN 适应度角落，就是 TS 返回 `NaN`（0/0）而 Python 返回 −5.05 的分歧——因为任何与 NaN 的比较都是 false，TypeScript 的遗传算法对这类腿**任意排序**。修好之后（金标 GA 运行的最好适应度 0.6469557 → 0.6776223，§26），所有受影响的已提交实验都重跑并留痕。

**K2 的当前边界**：§75已将恒定对角质量矩阵替换为逐杆构型相关惯性，补齐重力、运动耦合与实际质心/位姿，并通过独立惯性组装核对。§76接触求解已执行记录的预算、加入耦合模式修正并在不收敛时拒绝推进；单步数值一致不证明整机时间收敛。单个摩擦系数、软地面单位/阻尼缺陷、零速销轴锁定及整机独立对照仍待处理。当前没有浏览器 K2 后端。历史步幅/起步对照仅支撑已测场景，不能由原方案文字推导更广的精度承诺，详见 [ADR-0010 的实施核对](adr/0010-k2-independent-solver.md)。

### 2.3 证据阶梯：核对 ≠ 验证

[VALIDATION.md](VALIDATION.md) §1 的区分贯穿全文：

- **核对（verification）**：代码是否正确实现了我们写下的模型。可以和别的求解器、文献里的方程对比。
- **验证（validation）**：模型是否符合真实世界。**需要实测。**

| 等级 | 含义 | 本报告里的例子 |
|---|---|---|
| **E0** | 只有一个模型算过 | 旗舰尺度表（23 个 MuJoCo 格子）、多保真度筛选的相关系数、稳健优化的排名 |
| **E1** | 至少两个**独立**求解器在约定容差内一致 | 慢速平地步幅（差 0.58 %，§31）；起步风速的**量级**（约定容差 25 %，实测 13.9 % / 4.2 %，§36 §7） |
| **E2** | 与**公开数据或文献**在不确定度内相符 | 当前无已复核的足端轨迹 E2；原§30已撤回（§46） |
| **E3** | 被**可追溯的实测**验证 | **暂无。一个都没有。** |

两条经常被忽略的规则：**等级跟着结果走，不跟着代码走**（同一个求解器，步幅可以是 E1，扭矩仍是 E0）；**优化器和智能体基准不信 E0 的排名**（要过排名稳定性检查，§33、§37）——这条正是 §4.2 那条负面结果的法律依据。

---

## 3. 结果

### 3.1 运动学：文献验证待补证（原 E2 撤回）

2026-11-03 核对 [Pop, Dolga & Pop (2014) 的出版商页面](https://www.scientific.net/AMM.658.684)后，能确认 CCD 追踪的实物 Jansen 机构与 DC 电机，无法从已核对来源确认旧报告的 57.1 mm、22.5 mm、0.43，以及 24 个数字化坐标。仓库未保存原图、轴标定、像素坐标或误差推导；原来的“300 dpi、±0.8 mm”说明也缺可追溯依据。

旧数据及数值比对保留在 `experiments/literature-jansen-amm2014.json` 和 EXPERIMENTS §30，均标记 **[unverified]**。`scripts/verify_literature_kinematics.py` 默认拒绝验证；显式 `--unverified-preview` 只供审查历史数字。**撤回 E2 升级，不据此授予其他等级**；算法的几何不变量、跨实现测试与其他独立证据仍分别判断。完整更正见 EXPERIMENTS §46 与 [RESEARCH-NOTES.md](RESEARCH-NOTES.md)。

### 3.2 两个独立求解器：步幅一致（E1）

K2 的独立性是可核查的：零 MuJoCo 依赖（不 import 它的绑定、不共享约束或接触代码）、4 自由度约化坐标 + 解析二元组投影（**环路闭合误差按构造为零**）、Moreau 型速度级离散时间推进 + 真正的**不软化**库仑干摩擦（μ_s、μ_k）与单边 Signorini 支撑（§31；设计记录 `docs/adr/0010-k2-independent-solver.md`）。

**契约套件**（两个后端跑同一份检查）：无摩擦摆的能量漂移 < 0.01 %、小摆周期误差 MuJoCo < 0.02 % / K2 < 0.01 %、斜面滑块误差 MuJoCo < 0.5 % / K2 < 0.1 %、重力方向、快照/恢复逐位一致、重复运行逐位一致、镜像对称（MuJoCo < 2 % 跨度 / K2 < 1 %）、单位缩放 2× 不变（< 0.1 %）——**全部通过**，并且注入变体测试（故意破坏重力、丢掉势能、时间扭曲）能被抓到。

**慢速平地步幅对拍**（6 腿小 Jansen，位置伺服电机驱动，ω = 2.0 rad/s）：

| 量 | MuJoCo | K2 | 相对差 |
|---|---|---|---|
| 步幅 / 圈 | 0.2760 m | 0.2776 m | **+0.58 %** |
| 前进行走距离 | 0.1655 m | 0.1662 m | +0.42 % |
| 平均机体高度 | 0.1694 m | 0.1700 m | +0.35 % |
| 平均驱动扭矩 | 2.16 mN·m | 2.54 mN·m | **+17.6 %** |
| 环路约束违反 | 最大 0.12 mm | **0.00 mm（精确）** | – |

K2 略高的解释：它的落撑相有真正的非滑移静锁定，而 MuJoCo 的软摩擦正则化允许极微小的后向微滑。**步幅因此升到 E1；扭矩没有**（差 17.6 %，而且 §4.4 说明扭矩量级本身就依赖摩擦正则化）。

**起步风速对拍**（15 s 判据下，§31 §3）：MuJoCo `(0.6771, 0.7071] m/s`（估计 0.6920），K2 `(0.7071, 0.7384] m/s`（估计 0.7226），**差 4.4 %**。物理解释：临界附近曲柄必须越过最坏机械优势峰；MuJoCo 的软摩擦允许在亚微米速度下蠕动，K2 的静摩擦在帆力矩**严格超过**脱扣阈值之前保持刚性零速。**注意 15 s 判据与 §28/§36 的 40 s 判据不是同一个东西**，两组数字不能混用。

### 3.3 起步风速：数值、区间与摩擦带

**基线（§28，模型内）**：小 6 腿 Jansen 走兽（`schemas/examples/design-jansen-small-6leg.json`），帆驱动，平地，MuJoCo 时域仿真。

- 起步风速 = **(0.479, 0.500] m/s**，估计 **0.489 m/s**（6 次仿真）。
- §9 的帆驱动对照表记录"约 0.45 m/s"（0.4 m/s：40 s 内只走了 8 mm，没起步；0.5 m/s：37 s 转完一圈）。§28 指出：按严格的"40 s 内转满一圈"判据，0.45 m/s 略微不够，要 ~0.48–0.50 m/s。**两者不矛盾，是判据与取整的差别。**
- **"不走"也记了数字（§28）**：v = 0.25 m/s 时 40 s 内躯干只移动 1.4 mm、曲柄转角 < 0.05 rad，判为停转/未起步；v = 0.35 m/s 时 40 s 走了 4.7 mm，仍未转满一圈。

**单参数敏感性表（§28，模型内；一次只动一个假设）**：

| 参数 | 基线 | 低值 → 起步风速 | 高值 → 起步风速 | 敏感度 |
|---|---|---|---|---|
| `joint_friction`（销轴摩擦） | 0.0 N·m（理想） | 0.0005 N·m → **(1.02, 1.07] m/s** | 0.0020 N·m → **(1.27, 1.33] m/s** | **主导（+110 % ~ +160 %）** |
| `joint_damping` | 0.0 N·m·s/rad | 0.0002 → (0.534, 0.557] m/s | 0.0010 → (0.723, 0.755] m/s | 高（+10 % ~ +50 %） |
| `sail_area` | 0.03 m² | 0.015 → (0.663, 0.692] m/s | 0.060 → (0.361, 0.377] m/s | 高（∝ 1/√A） |
| `sail_drag_coeff` | 1.2 | 0.6 → (0.663, 0.692] m/s | 2.4 → (0.361, 0.377] m/s | 高（∝ 1/√Cd） |
| `sail_gear` | 10.0 | 5.0 → (0.608, 0.635] m/s | 20.0 → (0.430, 0.449] m/s | 中 |
| `crank_friction` | 0.002 N·m | 0.001 → (0.469, 0.489] m/s | 0.004 → (0.489, 0.511] m/s | 低（±4 %） |
| `crank_damping` | 0.001 N·m·s/rad | 0.0005 → (0.469, 0.489] m/s | 0.0020 → (0.489, 0.511] m/s | 低（±4 %） |
| `foot_friction` | 1.5 | 0.75 → (0.489, 0.511] m/s | 3.0 → (0.469, 0.489] m/s | 可忽略（±4 %） |
| `contact_stiffness` | 100000 1/s² | 50000 → (0.489, 0.511] m/s | 200000 → (0.489, 0.511] m/s | 可忽略（不变） |

三条读法：**(1)** 销轴摩擦是**唯一的主导项**，0.5 mN·m 的每关节摩擦就把起步风速翻了一倍以上；**(2)** 起步风速几乎精确地按 1/√(A·Cd) 缩放（帆面积翻倍：0.489 → 0.369 m/s，理论 0.489/√2 ≈ 0.346 m/s）；**(3)** 接触刚度与地面摩擦**不影响**起步风速——起步不靠脚不滑。

**虚拟测力计（§32，模型内）**：准静态机构静力学与慢速多体动力学（0.5 rad/s）对拍——峰值负载扭矩 2.58 mN·m vs 2.67 mN·m（差 +3.5 %），关键失速角 θ\* ≈ 20.0° vs 21.5°（差 1.5°），临界起步风速 0.685 vs 0.697 m/s（差 +1.8 %）。**死点被定位在 θ\* ≈ 20°**：风不够时走兽就停在这个角度附近，解释了真实风洞里"偶发起步失败"为什么与初始相位密切相关。

### 3.4 尺度曲线：非单调，最小可行尺寸

**预注册（§36 §3，先写后算）**。在除 L = 1 自检之外的任何测量之前写下并实现为带单元测试的函数：帆力矩 ∝ L³ v²；负载力矩 ∝ L^(p+1)（模型 A：重量提升）——于是 **v ∝ L^((p−2)/2)**，p = 1 → −0.5，p = 2 → 0，p = 3 → +0.5；模型 B′（代码里的绝对销轴摩擦）→ **−1.5**；判据项（40 s 内转一圈）额外要求 ω_req·gear·r ∝ L，斜率 +1。曲线形状预设为两段式 v(L) = A·L^((p−2)/2) + B·L，在 L = 1 归一到 0.489 m/s。

**这里有一处必须原样保留的更正**：模型 B′ 的指数初稿写成 **+1.5**，那是**符号错误**（正确是 −1.5）。它是在第一批数据格子出现之后才发现的。更正的动作是：改代码（`predicted_slope()` 返回 −1.5）、加单元测试钉住符号、在 §36 §3 留一条**带日期**的更正记录、并在对比表里同时给出原值与更正值。**更正并没有让预测更贴合数据**——实测小尺度段是 −0.450，两种符号下都不吻合。§36 §11 第 3 条写得很清楚："更正只是把算术改对，不是把预测改成数据。"

**协议**：25 格（MuJoCo 23 + K2 2，其中 1 格是 L = 1 的别名）；尺度 0.35、0.6、1.0、1.7、3.0，外加 0.02、0.03、0.1 三个探针；质量指数只跑 p = 1 与 p = 3（**p = 2 的列没跑**，预算被尺度点吃掉，§36 §4 削减说明第 2 条）；判据 40 s、`rel_tol` **5 % 没有放宽**；销轴摩擦三档 0 / 0.0005 / 0.002；曲柄摩擦、阻尼、转子惯量、销轴摩擦**不随 L 缩放**（绝对值）。**没有把曲线外插到没测的尺度。**

**主表（§36 §5，全部模型内，证据等级 E0）**：

| L | p | jf (N·m) | 区间 (lo, hi] m/s | 估计 m/s | 备注 |
|---|---|---|---|---|---|
| 0.02 | 1 | 0.002 | (30, **inf**] | — | **走不动**（30 m/s 以内转不满一圈） |
| 0.03 | 1 | 0.002 | (18.07, 18.74] | 18.4 | 能走，但远超 4.17 m/s 的现实上限 |
| 0.1 | 1 | 0.002 | (3.285, 3.431] | 3.357 | 上限内 |
| 0.35 | 1 | 0 | (0.7827, 0.8173] | 0.7998 | |
| 0.35 | 1 | 0.0005 | (1.375, 1.435] | 1.405 | 与 jf = 0.002 **逐位相同**（见下） |
| 0.35 | 1 | 0.002 | (1.375, 1.435] | 1.405 | |
| 0.35 | 3 | 0 | (0.5179, 0.5408] | 0.5292 | |
| 0.6 | 1 | 0 | (0.5937, 0.62] | 0.6067 | |
| 0.6 | 3 | 0 | (0.4064, 0.4244] | 0.4153 | **p = 3 的最低点** |
| 1 | 1 | 0 | (0.489, 0.5106] | 0.4997 | 自检格：4 次独立重跑逐位相同 |
| 1 | 1 | 0.0005 | (1.021, 1.067] | 1.044 | |
| 1 | 1 | 0.002 | (1.268, 1.324] | 1.296 | |
| 1.7 | 1 | 0 | (0.414, 0.4323] | 0.423 | |
| 1.7 | 3 | 0 | (0.6036, 0.6303] | 0.6168 | |
| 3 | 1 | 0 | (0.3805, 0.3973] | 0.3888 | |
| 3 | 3 | 0 | (0.8462, 0.8837] | 0.8647 | |
| 1 | 1 | 0 | (0.5569, 0.5815] | 0.5691 | **K2** |
| 1.7 | 1 | 0 | (0.3964, 0.414] | 0.4051 | **K2** |

每一格的区间宽度都在 5 % 以内——**这代表搜索分辨率，不代表物理不确定度**。所有格子的 `trusted` 都是"是"（每次仿真的环路开口都没超过 skeptic 上限）。

**曲线的形状（§36 §10）**：p = 1 逐段斜率 **−0.513**（0.35→0.6）、−0.380（0.6→1）、−0.314（1→1.7）、**−0.149**（1.7→3），全局 −0.337。小尺度端与预注册的 −0.5 几乎重合（差 0.013），**大尺度端对不上**：预注册形状在 L = 3 处应转向上升（0.587 m/s），实测是 0.389 m/s 且仍在下降，偏差 **−33.7 %**——40 s 判据项确实存在（斜率从 −0.51 变到 −0.15），但比预注册的弱得多。p = 3 是**非单调的 V 形**：0.529 → **0.415** → 0.500 → 0.617 → 0.865，最小值在 **L ≈ 0.6**；大尺度段斜率 **+0.595** 与预注册的 +0.5 相当接近（偏差 +16 % / +2 % / −10 % / −14 %），小尺度段 **−0.450** 与所有预注册模型都不符（偏差 +104 %），但"存在一个与尺度无关的地板"这个**定性**结构是对的，地板在本模型里唯一的候选是**不随 L 缩放的曲柄摩擦 0.002 N·m**——**这个机理本卡没有直接检验**（要检验得单独扫曲柄摩擦，超出预算），所以它是**假设**，不是结论。

**摩擦带（§36 §6）**：p = 1、MuJoCo，jf = 0 是下沿：

| L | jf = 0 | jf = 0.0005 | jf = 0.002 | 带宽 |
|---|---|---|---|---|
| 0.35 | (0.7827, 0.8173] | (1.375, 1.435] | (1.375, 1.435] | 1.76× |
| 0.6 | (0.5937, 0.62] | (1.24, 1.295] | (1.295, 1.352] | 2.18× |
| **1** | (0.489, 0.5106] | (1.021, 1.067] | (1.268, 1.324] | **2.59×** |
| 1.7 | (0.414, 0.4323] | (0.6962, 0.727] | (1.074, 1.121] | 2.59× |
| 3 | (0.3805, 0.3973] | (0.5619, 0.5868] | (0.7609, 0.7946] | 2.00× |

**最小可行尺寸（§36 §9，E0）**：参考上限取 15 km/h ≈ **4.17 m/s**——按 [WIND.md](WIND.md) §6 规则 4，这**只是数量级检查**。

| p | jf (N·m) | 4.17 m/s 上限内能起步的 L | 超出上限的 L | 结论形态 |
|---|---|---|---|---|
| 1 | 0 | 0.35, 0.6, 1, 1.7, 3 | （无） | 只有上界：**L_min ≤ 0.35**，下界没测到 |
| 1 | 0.0005 | 0.35, 0.6, 1, 1.7, 3 | （无） | 只有上界：**L_min ≤ 0.35** |
| **1** | **0.002** | 0.1, 0.35, 0.6, 1, 1.7, 3 | **0.02, 0.03** | **上下界都有：L ∈ (0.03, 0.1]** |
| 3 | 0 | 0.35, 0.6, 1, 1.7, 3 | （无） | 只有上界：**L_min ≤ 0.35** |

**K2 交叉验证（§36 §7）**：L = 1 处 K2 比 MuJoCo 高 **+13.9 %**，两个 5 % 区间**完全分开**（MuJoCo 上沿 0.5106 < K2 下沿 0.5569，差 0.046 m/s）；L = 1.7 处低 −4.2 %，两个区间**只共用一个端点**。分歧只发生在取点序列上最靠阈值的那个点：0.4139686946023734 m/s 上 K2 说能起步（35.42 s 转完一圈），MuJoCo 说不能。按本卡约定的容差（起步风速估计值相差 ≤ 25 %），两处都通过 ⇒ **"起步风速的量级"是 E1**；但**没有一个 5 % 区间重叠** ⇒ **"门限在 0.50 m/s"不是 E1**。主表 23 个 MuJoCo 格子**仍然是 E0**。

### 3.5 排名稳定性

12 个异质候选设计族（Jansen、长冲程、高抬腿、两种曲柄、宽/窄髋距等），7 个评估条件，测 Spearman 秩相关 ρ_s 与前 5 名重合度（§33，模型内；原始数据 `experiments/ranking_stability_v04.json`；测试耗时 127.5 s）：

| 条件对 | ρ_s | 前 5 名重合 |
|---|---|---|
| K2（μ=1.5）↔ MuJoCo（μ=1.5） | **0.8462** | **80 %** |
| K2 μ=0.5 / 1.5 / 2.5 三档之间 | **1.0000** | **100 %** |
| 纯运动学占空比打分 ↔ MuJoCo 动力学步幅 | **0.2448** | 60 % |
| 纯运动学占空比打分 ↔ K2 动力学步幅 | 0.4685 | 80 % |
| 纯运动学步长 ↔ MuJoCo 动力学步幅 | 0.4266 | 60 % |
| 起步风速 ↔ 动力学步幅 | 约 0.49–0.52 | 80 % |

读法：**(1)** 跨求解器的步幅排序相当稳（ρ_s = 0.8462）；**(2)** 平地上摩擦大小几乎不影响排序；**(3)** 纯运动学打分**不能**替代动力学做精细排序；**(4)** "走得快" ≠ "起得动"（步幅与起步风速的秩相关只有 0.49–0.52），风驱动走兽必须联合优化速度与起步风速。

### 3.6 风场与机体风阻：模型补齐了什么，又假设了什么

[WIND.md](WIND.md) §4 列出风驱动还缺什么。补上了两样（§34、§35），**两样都带假设**。

**风场 v2（§34，模型内）**：把自然风拆成三件事——边界层垂直风廓线、大气湍流谱、风与机体的航向夹角。湍流用 Ornstein–Uhlenbeck / Dryden 型的连续随机微分方程构造平稳高斯马尔可夫脉动（τ_u = L_u/v̄，σ_u = I_u·v̄），并注册了 `constant` / `gusts` / `lull` / `turbulent` / `shear` / `profile_turbulent` 六种风。**核对**（不是验证）：在 v̄ = 5.0 m/s、I_u = 0.15、L_u = 25.0 m、seed 42、采样 300 s 下，样本统计量与解析目标对得上——平均风速 4.928 m/s（目标 5.000，−1.4 %）、脉动标准差 0.732 m/s（目标 0.750，−2.4 %）；自相关 R(2.0 s) 0.6884（理论 0.6703，+0.0181）、R(5.0 s) 0.4625（理论 0.3679，+0.0946）、R(15.0 s) 0.0152（理论 0.0498，−0.0346）——**长时相关比理论衰减得快**，这一条说明这个湍流模型不是 Dryden 全谱。Python 与 TypeScript 两端同种子采样**逐位一致**到 6 位小数。垂直廓线用幂律（海滩开阔沙地**假设** α = 0.14）：桅杆高处 z = 2.0 m 风速高 10.2 %，贴地 z = 0.2 m 低 20.1 %——这解释了 Jansen 为什么把大帆架到机体上方。

**机体与管系风阻（§35，模型内）**：F_x = ½·ρ·C_d,body·A_body·|v_rel|·v_rel，新增两个带 `assumption` 标注的场景字段 `body_drag_area`（默认 0.0）与 `body_drag_coeff`（默认 1.1，柱状管束钝体的典型值）。解析极限检查（ρ = 1.2 kg/m³、C_d = 1.1、A = 0.05 m²，即 ½ρC_dA = 0.033 N/(m/s)²）：顺风 5 m/s 静止 **+0.825 N**（前推，帮助克服静摩擦）、逆风 −5 m/s **−0.825 N**、静风下 v_x = 2 m/s **−0.132 N**、超风速（风 2 m/s、行进 3 m/s）**−0.033 N**。两个后端的机体滑移自由度一致（|x_K2 − x_MuJoCo| < 0.03 m）。**代价与收益**：在临界起步风速附近（如 0.65 m/s）开启 A = 0.05 m² 的迎风面积，可把起步所需风速降低约 **4 %–8 %**。默认 A = 0 是为了让历史金标运行**逐位不变**——也就是说，**旗舰实验（§36）跑的时候机体风阻是关着的**，本报告的起步风速数字不含这项助力。

---

## 4. 负面结果与边界

这一节是本报告的主体。**下面每一条都是我们自己的结果，不是别人的失败。**

### 4.1 运动学粗筛与动力学排序**反相关**（§37）

两层筛选流水线：粗筛层只解足端轨迹（0.79 ms/候选），复核层跑一次真实动力学（4.2–26.6 s/候选）。

- 两层排名的整体一致性很弱：ρ_s = **0.4685**（对 K2）/ **0.2448**（对 MuJoCo），在 N = 12 下**不显著**（零假设标准误约 1/√(N−1) ≈ 0.30，即约 1.5σ 与 0.8σ）。
- **最硬的一条**：在粗筛选出的前 5 名**内部**，粗筛顺序与动力学顺序**强负相关**——ρ_s = **−0.8000**（K2）/ **−0.7000**（MuJoCo）。逐条看：粗筛第 1 名 `D05_wide_hip` 在动力学里排第 5；动力学冠军 `D10_stretched` 在粗筛里只排第 4；动力学第 3 名 `D06_narrow_hip` 被粗筛排到第 9，**永远进不了复核层**。
- 淘汰是有效的：保留 9/12（淘汰 25 %）可以保证动力学前 5 名一个不丢；保留 5/12（淘汰 58 %）在 K2 下保住 4/5、在 MuJoCo 下只保住 3/5。

**准则**：粗筛只准做**淘汰**，不准做**排序**、不准做早停判据、不准用来挑冠军。粗筛便宜 5000–33000 倍，这正是这条流水线值得做的唯一理由。

### 4.2 稳健优化的胜负**会翻面**（§38）

WIND.md §5 要求的"阵风稳健性"被实现成 CVaR（Rockafellar & Uryasev 2000 的下尾 expected shortfall 闭式解）+ 对抗场景搜索。

- 在 K2 主求解器下，**level A**（让名义最优设计失败的那个场景，constant@0.10 m/s + 60° 航向 + 8° 斜坡）：CVaR 设计赢名义最优 **+0.272780 m**；**level B**（名义最优还能勉强走的最难场景）：CVaR 设计赢 **+0.007819 m（+35.7 %）**，而最坏情形优化的设计**输了 −0.012441 m**。
- **换求解器（MuJoCo）level A 翻面**：CVaR 设计 **−0.579185 m** 输给名义最优的 −0.308338 m，差 **−0.270847 m**，与 K2 下的 +0.272780 m **方向相反**。名义场景上的优势也翻了（MuJoCo：+0.4998 vs +0.5030，几乎一样）。
- **换优化器种子 level B 翻面**：seed 2 下 level A 仍赢（+0.292492 m），但 level B 从 +0.007819 m 变成 **−0.023271 m**。这个优势比"走起来"的 0.01 m 阈值还小，本来就在噪声里。
- **换场景集 CVaR 的排序也翻**：seed 2 抽的 20 个场景里，名义最优的 CVaR 最高（+0.0532 > +0.0505）。
- **换摩擦是空检验**：K2 下 μ ∈ {0.3, 0.5, 1.5, 2.5} 与 `foot_friction` ∈ {0.5, 1.5, 2.5} 的结果**逐位相同**（+0.585833 m）——摩擦轴根本没接到结局上，不能算稳健性证据。
- 别的限制：K2 **不实现地形障碍物**（`bumps` 在主求解器下是惰性的，地形这一维只通过坡度起作用）；12 243 次物理评估里 **41 次** K2 抛 `TypeError`，被按"走不动"计入；逆风被有意排除；只搜了 13 个连杆长度里的 3 个；只做了 1 个优化器种子。

**结论**：任务卡 O-07 的条件一（找出一个使设计失败的场景）**PASS**，条件二（稳健设计在最坏场景下优于名义最优）**PARTIAL**。按 [VALIDATION.md](VALIDATION.md) §2，优化器与基准**不信 E0 的排名**——所以这条只能作为**机制演示**，**不能**作为排名结论。

### 4.3 起步风速由一个**没人测过**的假设决定（§36）

- 销轴摩擦从 0 改到 0.002 N·m，起步风速变 **2.59 倍**（L = 1）。任何只报一个数的起步风速都是误导。
- **"走不动"的边界是摩擦假设划出来的，不是尺度划出来的**：jf = 0.002 时 L = 0.02 连 30 m/s 都起不来（`hi = inf`）、L = 0.03 要 18.4 m/s（远超 4.17 m/s 上限）、L = 0.1 才回到上限内；而 jf = 0 时测到的最小尺度 L = 0.35 只要 0.80 m/s，离上限还有 5 倍余量。**所以 [WIND.md](WIND.md) §3 的"低于某个尺寸走不动"这句话，其成立与否取决于一个没人测过的假设参数。**
- **MuJoCo 里的销轴摩擦是"软"的，标称值不成比例地兑现**：L = 0.35 处 jf = 0.0005 与 jf = 0.002 给出**逐位相同**的区间（1.375, 1.435]，L = 0.6 才分开 4.4 %，L = 1 才分开 24 %）；曲柄摩擦标称 0.002 N·m，而 L = 0.35 起步风速处帆能给出的曲柄力矩只有 **2.1 × 10⁻⁴ N·m**——**比标称的曲柄摩擦小一个数量级，走兽却能起步**。这正是 [WIND.md](WIND.md) §4 点名的风险：起步阈值正好落在软化摩擦最失真的低速粘滑区。**所以这个带的上沿是求解器相关的，不能当成"销轴真有那么大摩擦时的真实起步风速"来引用。**

### 4.4 扭矩的**量级**依赖摩擦怎么被数值化，所以报区间（§8、§9）

§8 的研究被 §9 取代（脚部碰撞球重叠的 bug + 接触刚度单位标错）。**更正后**仍然成立的部分（§9，同一基线：12 腿、平地、50 kg、μ 1.5、时间步 0.5 ms）：

| 改动 | 平均扭矩 | 倍数 |
|---|---|---|
| 基线 | 8.9 N·m | – |
| 摩擦锥：椭圆 vs 锥形 | 17.9 vs 8.9 | **×2.0** |
| 摩擦阻抗比 10 vs 1 | 21.7 vs 8.9 | **×2.4** |
| no-slip 迭代 10 vs 0 | 13.7 vs 8.9 | ×1.5 |
| 管质量 0.05 / 0.12 / 0.2 kg/m | 4.8 / 8.9 / 12.4 | 原记录原因不明；后续 S-01 已定位质量缩放约束正则化耦合（见下文更正） |
| 接触刚度 1e4 → 1e6 (1/s²) | 6.1 → 11.5，峰峰值 6.2 → 23.9 | 一直在涨，没有"平台" |

**步幅在所有设置下都在 3 % 以内**——步幅是运动学量，所以它稳；**扭矩不是**。诚实的说法是：把一个扭矩写成**跨摩擦正则化选择的区间**，在实测之前不要写成单值。

**2026-11-03 同步更正**：[EXPERIMENTS.md](EXPERIMENTS.md) §42（2026-10-28）已完成 S-01 的受控干预。冻结 MuJoCo 的逆惯量权重后，重腿平均扭矩从 12.434 N·m 回到 4.816 N·m，与轻腿一致，定位为质量缩放约束正则化的建模耦合。上述历史数字保留；“原因不明”不再是当前结论。这仍是模型内机制核对，没有新增实测证据。

**能量账解释了为什么（§9、§14）**：平地电机驱动时，接触耗散占输入功的绝大部分——§14 的表给 **96.5 %**（输入 4.06 mJ/圈），§9 的叙述给 **97 %**（输入 4.05 mJ/圈、接触 3.91 mJ）。两者是**同一族测量**（3.91/4.05 = 96.5 %，§9 的 97 % 是四舍五入），不是两个模型。能量账在所有场景下闭合到 0.4 % 以内（验收线 2 %）。**帆驱动时分配完全不同**：4 m/s 风下输入 47 mJ，**关节摩擦与阻尼吃掉 82 %**（接触只有 17 %）——而这两个值是**假设值**，所以风驱动的起步结论大半取决于猜测。

**2026-11-03 能量统计更正**：上段比例是历史运行记录。当前加固发现 `mj_step` 后积分态与缓存观测不在同一时刻，已重做能量记账及跨端对照；旧能量分配不能直接当作新口径结果，完整前后差异由 H2-01 记录。

另有一条容易被忽略的差别：**占空因子有两个数**。连杆足端轨迹在 43.3 % 的周期里是平的（运动学占空比 0.433），而在仿真里每只脚只有 **34.8 %** 的时间接触地面；差的那一段是足端"几乎离地"（垫片压缩 0.6 mm）。UI 两个数都显示。

### 4.5 "软地面"曾经**什么也没做**（§13）

在重构仿真器之前录了十次金标运行，它们当场抓到一件事：`soft` 地形**从来没有生效**——它的指标与平地**逐位相同到 16 位**。原因：两个 `solref` 为负（直接）的 geom 里 MuJoCo 取**更硬**的那个，而钩子只软化了脚。修好钩子（同时软化地形 geom 与脚）之后：刚度 4000 (1/s²) 时最大下沉 0.57 → 11.4 mm，每圈步长 0.276 → 0.177 m（**−36 %**），峰值扭矩 14.7 → 45 mN·m；刚度 400 时走兽下沉 69 mm、几乎不动（步长 0.004 m）。**"软地面"至今仍是个粗糙的替身，不是沙子。** 回归测试 `test_soft_ground_is_actually_softer_than_flat_ground` 守着这个行为。

同节还有一条**没修**的：伺服增益与 `unit_m` 成比例，所以**同一台物理机器**换个长度单位写，伺服就变了——峰值曲柄扭矩 14.7 → 8.5 mN·m（**−42 %**），步幅不变（0.2778 m）。步幅稳、扭矩不稳，另一个提醒。

### 4.6 闭环张开：修了什么、没修什么（§20、§27）

**问题**：小幅改动设计（把三个连杆长度改 2–3 个单位）就让仿真里出现 7 mm 的环路开口和 −74 % 的能量残差。机理在 §20 定位：不是软接触也不是猛烈冲击，而是**一条刚性约束链被单脚支撑硬推着走**（只着一只脚、曲柄扭矩已到电机上限、穿透只有 0.7 mm）。

**修好的**：时间步从 0.2 ms 降到 0.1 ms。16 个随机走兽的审计失败从 **9/16 变成 0/16**，最大开口中位数/最差从 5.0/9.7 mm 降到 0.7/4.4 mm，最差能量残差从 −304 % 降到 −2 %。代价是运行时间约 2.7 倍（默认 1.5 圈从约 5 s 变成约 15 s）。

**没修好的，而且 §20 的样本太小**：

- §20 的 16 个样本里还有两例开口 4.2 / 4.4 mm（在 5 mm 限内但很接近），"第二种机制"存在，当时没有继续查。
- **§27 用 64 个走兽重审（同一个生成器、种子 1）：失败率 19 %（12/64），不是 0。** 中位开口 1.00 mm，最差 13.19 mm；12 个走兽开口超过 3 mm，90 分位 4.35 mm。8 腿走兽 8/19（42 %）失败，4 腿 0/16；`bumps` 地形 6/15。腿数与地形在这批样本里**混在一起**，没有分开。
- **机理测试排除了时间步**（0.05 ms 毫无变化：9/12 → 9/12）、求解器迭代、接触刚度、电机扭矩上限（减半仍是 9/12，只把最差从 13.2 mm 降到 8.4 mm）；**指向两个旋钮**：环路约束的保持刚度（时间常数 0.5 ms：9/12 → 1/12）与曲柄转速（减半：9/12 → 3/12）。两者都符合"**动力学张开**"——链条被推得比软约束跟得上更快。**但这是从两个旋钮推出来的推断，不是对机理的测量。**
- **而且刚化不是到处都更好**：有案例从 1.3 mm 变成 2.6 mm、另一个从 0.6 mm 变成 1.9 mm；刚化后最差的一例是 4.63 mm，仍贴近 5 mm 限。
- **默认设置没有改**：刚化只在 12 个失败走兽上试过，**没有**在 64 个、金标运行或 §20 的 16 个上跑过（可能制造新失败）。所以它是一个**候选，不是一个修复**。

**2026-11-03 后续实验**：上述段落保留 §27 当时的调查范围。现已补做三组完整64样本，见 [EXPERIMENTS.md](EXPERIMENTS.md) §44：默认仍12失败；仅刚化增至28失败；刚化并减半步长后为7失败。候选确实制造了新的能量审计失败，尚未通过 G1，默认仍未改。

**2026-11-04 当前结论**：上段是修正观测时刻前的历史结果。§48 修正能量记账后，同三组完整样本分别 **10/4/4** 失败；候选中的旧能量报警消失，步幅失败仍在，默认还存在闭环失败。§54 的接触分解只诊断原因，没有降低门槛或把诊断重算当作独立验证。随后 §59 修正 MuJoCo 质量归一化接触阻尼，三组全64样本为 **10/3/3** 失败；独立接触实验已通过，但候选的20/56/61仍未通过原步幅门槛。默认参数值和原G1门槛未改，G1仍未通过。

### 4.7 E3 层是空的（§36 §11、§39 §7）

| 缺口 | 模型内（E0） | 实测（E3） | 现状 |
|---|---|---|---|
| 扭矩 / 电流 | 峰值 2.58–2.67 mN·m、死点角 ≈ 20°（§32） | **0 条**（未知） | 通道已开，数据未到 |
| 起步风速 | 0.489 m/s（0.479–0.500）；含 0.5 mN·m 关节摩擦则 1.02–1.07 m/s（§28） | **0 条**（未知） | 通道已开，数据未到 |
| 销轴摩擦 | 起步风速的主导项（+110 % ~ +160 %） | **0 条**（未知） | 随扭矩实测一起估 |

社区数据入口已经建好：《如何测一只走兽》指南（`docs/HOW-TO-MEASURE.md`，中英双语）、提交校验器（`packages/calib/src/strandbeest_calib/community.py`）、命令行入口 `scripts/validate_community_measurement.py`、一份格式示例、21 个测试。**E3 判据有八条**（量在文件里、单位已声明、绝对误差估计、`provenance.source` 有效、仪器/测量日期/标定日期齐全、原始数据有出处、许可已声明、文件非合成），八条齐了才写 "E3 for …"。

**必须讲清楚的两件事**（§39 §5）：**校验器查不出"你是不是真的测了"**——它查格式与内部一致性，真实性由人审；**E1/E2 不会由单份社区提交产生**——社区提交只能把某个量从 E0 抬到 E3。示例文件里的数字是**编出来的**（文件自己写明了），它只用来展示格式。**提交数据的许可方案已定案为默认 CC0 1.0（带可选科学署名，见 [LICENSING.md](LICENSING.md) 与 [ADR-0011](adr/0011-licensing-for-code-designs-and-data.md)）**。

**所以：本报告的每一个数字都是模型内的。** 这不是谦虚，这是事实陈述。

### 4.8 其它几条不软化的负面结果

- **NaN 适应度角落**（§26）：一个在 24 个探测角装得上、但在 90 个采样点里装不全的腿，TS 返回 `NaN`、Python 返回 −5.05。因为任何与 NaN 的比较都是 false，**TS 的遗传算法对这类腿任意排序**。修复后金标 GA 运行的最好适应度从 0.6469557 变成 0.6776223；`reproduce` 的 20 个种子从"2 个胜过 Jansen"变成"0 个"；风目标的 seed 1 从"没找到更好的"变成 0.228 → 0.286 m/s。**一个没人注意的 NaN 能把一个遗传算法带偏这么多。**
- **飞轮不能降低起步风速**（§5，降阶模型）：我们原本预期飞轮能把曲柄带过扭矩峰，**测试失败了**。原因是阻力帆的力矩在接近风速时趋零，曲柄在扭矩峰到来前根本转不快。这个结果来自降阶模型（§6 之后被判定为"未验证"），但机理是清楚的。
- **"粗糙地面"永远不结束**（§21）：只有帆场景设了 `run.max_time`，其它场景继承了 schema 默认的 600 仿真秒；被障碍卡住的走兽曲柄停住，`psi` 永远到不了目标，于是跑到 600 s（0.1 ms 下是 600 万步）——现场跑了 23 分钟以上。修法是给所有非帆场景加 40 s 上限。**同一类 bug 还留在别处**：从"仿真"页直接提交的模拟（不是场景）对非帆驱动仍用 600 s 默认值。
- **已提交的实验文件有过期**（§12）：`experiments/flat-seed1.json` 与 `highstep-seed1.json` 在 HEAD 上**不能复现**（fitness 0.7129 提交 vs 0.7446 现在），它们早于引入分级不可行惩罚的提交，从没重生成过。已重生成。
- **贝叶斯校准是诚实的，但不准确**（§19）：真值落在每个后验区间内，但点估计差得很远（接触刚度 8.9e5 vs 真值 2e5，摩擦 2.6 vs 1.2）——**点估计不可用，区间才是结果**。而且"不可辨识"部分意味着"用这个代理模型不可辨识"（腿质量在 K = 32 与 64 之间翻转），因为 RBF 代理的留一误差 1.7 mN·m 比数据噪声 0.007 mN·m 大三个数量级。
- **把帆放进基因空间，没有带来好处**（§40）：在同权重、同优化器、种子、预算与场景集下，**固定帆在三项上全赢**自由帆（起步风速低 4.4 %、CVaR 高 11.8 %、名义距离高 29.4 %）。稳健性确实有可测收益，但只在权重全压稳健、且接受起步风速变差 24 % 的前提下；而"稳健设计在最坏阵风序列上不输"这条验收条件在默认权重下**因为两个设计重合而根本无法检验**（差 +0.000000 m），换成真正不同的稳健设计后它在对抗搜出的最坏序列上**输了 0.009 m**。
- **便宜的代理跟不上昂贵的测量**（§40）：优化循环里用的测力计代理与真实起步风速搜索只有 ρ = 0.303，实测值是代理的 1.87 倍，**在要比较的那一对上把排名弄反了**。所以最终排名只能由真实搜索给出；代理不得当作排名引用。这与 §37 的教训是同一条：**粗筛只能淘汰，不能排序**。
- **两个求解器本来就有分歧**（§40、§31）：同一个参考设计，MuJoCo 给 (0.479, 0.500] m/s、K2 给 (0.545, 0.569] m/s，**区间不重叠**（K2 高 13.9 %）。这不是新引入的问题，但它说明**起步风速这个量对求解器敏感**——而 §40 没有预算做第二个求解器的交叉核对，所以那条排名不通过排名稳定性检查，只能当机制演示。

---

## 5. 什么还不能说

这是 [VALIDATION.md](VALIDATION.md) §5"对外承诺"的反面。**下面每一条现在都不能说**，写在这里是为了防止它们被顺手说出去。

| 不能说的话 | 为什么 | 需要什么才能说 |
|---|---|---|
| "我们的仿真**验证**了走兽能靠风走" | [VALIDATION.md](VALIDATION.md) §1：核对 ≠ 验证。本仓库的检验**几乎全是核对** | E3：可追溯实测 |
| "这只走兽起步需要 X m/s 的风" | 单值是误导：销轴摩擦假设让同一个数变 **2.59 倍**（§36 §6） | 摩擦实测 + 敏感性区间一起给 |
| "低于 L = 0.1 的走兽走不动" | 这个边界**只在** jf = 0.002 N·m 的假设下成立；理想销轴下 L = 0.35 只要 0.80 m/s（§36 §8、§9） | 销轴摩擦实测（E3） |
| "Jansen 的走兽以约 15 km/h 前进" | 这是**艺术家的陈述，不是测量**，且**机体尺寸和重量未知**（[WIND.md](WIND.md) §6 规则 4、[VALIDATION.md](VALIDATION.md) §3）。本报告里 4.17 m/s 这个上限只作**数量级检查** | 公开视频测量（任务卡 V-05）或实测 |
| "CVaR 设计比名义最优设计更稳健" | 换求解器就翻面（§38 §7.4，−0.270847 m），换种子 level B 也翻 | 跨求解器通过排名稳定性检查 |
| "把帆参数做成基因能让走兽更好" | §40：固定帆在起步风速、CVaR、名义距离三项上**全赢**自由帆；而且那条排名只有一个求解器、一个种子、2 代预算，**不通过排名稳定性检查** | 跨求解器通过排名稳定性检查 |
| "运动学粗筛可以挑出最好的设计" | 在它自己筛出的集合内部，粗筛顺序与动力学顺序**强负相关**（ρ_s = −0.80，§37 §5） | 无——这条是**永久的操作准则**：只准淘汰 |
| "曲柄需要 8.9 N·m 的扭矩" | 摩擦正则化一变就差 2.0–2.4 倍（§9） | 扭矩实测（E3）；在此之前报区间 |
| "腿质量越高平均扭矩越高" | 数字确实如此（4.8 → 12.4 N·m，§9），但**原因不明**（任务卡 S-01 开放） | 干预实验（只改腿质量/只改质心/只改惯量） |
| "大机体对风更有利" | 被旗舰实验**否证**（p = 1 实测越大越省风；p = 3 是 V 形，最优在 L ≈ 0.6，§36 §11） | —— 这条是关于**我们**的断言 |
| "我们的仿真与实物一致" | 没有任何一个数字来自实物（§36 §11、§39 §7） | E3 |
| "起步风速已经算进了机体的气动助力" | 旗舰实验里 `body_drag_area` 默认为 **0**（为了金标运行逐位不变）；开启 A = 0.05 m² 后起步风速会再低 4 %–8 %（§35） | 机体迎风面积实测 |
| "仿真在 0.2 ms 时间步下与 0.1 ms 一致" | 0.2 ms 会在被扰动的设计上张开环路（§20） | —— 这是**用错**的设置，不是要吹的结论 |
| "起步风速的门限是 0.50 m/s" | 两个独立求解器的 5 % 区间在 L = 1 处**完全分开**（差 0.046 m/s）；只有**量级**（约定容差 25 %）是 E1（§36 §7） | 把容差与结论一起说 |

**还有一条关于数字本身的纪律**：§8 与 §9 给的是**同一研究的两个版本**，§8 的数值来自有 bug 的仿真器（脚部碰撞球重叠），已被 §9 取代；§6 同样被 §9 取代。**引用时只能用 §9 的数字。** 本报告里所有扭矩数字都取自 §9。

---

## 6. 历史建议与当前下一步

下表保留原报告的建议及当时状态。当前工作按 [ACTIONS.md](ACTIONS.md) H 卡推进：H2-01 的完整审计、H4-01 的可追溯公开数据仍是主要缺口；H3 系统集成和 H5-02 性能预算也在用户授权范围内。第6项已有三组全64样本及能量修正后的复验，第7项已由§42的受控干预定位模型内原因，第8项已筛到候选但未验收；不应再把它们描述为完全未开展。

按"对结论的影响"排序（排序依据是 §36 §11 给出的建议，加上各处留下的缺口）：

| # | 做什么 | 会改变什么 | 出处 |
|---|---|---|---|
| 1 | **把曲柄摩擦（`crank_friction`）当受控变量单独扫一遍**，同时记录 MuJoCo `frictionloss` 的正则化宽度 | p = 3 的小尺度段（实测斜率 −0.450，与所有预注册模型都不符）被归因于"与尺度无关的地板"，但地板**只是假设**。扫完才能说这条曲线的形状是物理还是数值 | §36 §11 第 1 条、§36 §10 |
| 2 | **把 40 s 判据的时间参数扫一遍** | 判据项 ∝ L 的强度完全由 T 决定；本卡只测了一个 T。T 变了，"越大越省风"的转折点就移动 | §36 §11 第 2 条 |
| 3 | **把 K2 交叉验证扩到整条曲线** | K2 每格只要 0.7–0.8 min（MuJoCo 3.5–31.9 min），**这是最划算的一步**。现在"量级 E1"只建立在两个尺度点上；铺开后要么升到 E1（区间也重叠）要么降级 | §36 §11 第 4 条、§36 §4 |
| 4 | **给 p = 2 补摩擦带与"走不动"探针** | p = 2 的列已经补上（实测斜率 −0.033，预注册 0.000），但**它没有摩擦带、也没有探针**，所以它的边界未知 | §36 §4、§40 |
| 5 | **用 K2（真库仑静摩擦）重测摩擦带的上沿** | 带的**上沿是求解器相关的**（§36 §6 第 3 条），K2 是唯一能查"销轴真有 0.002 N·m 摩擦时起步风速是多少"的通道 | §36 §6 |
| 6 | **在 64 个走兽 + 金标运行 + §20 的 16 个上验证环路约束刚化** | 现在它只是候选（12 例上试过），默认设置未改。验证失败就说明还有第三个机制 | §27 §"未做" |
| 7 | **解释腿质量为什么抬高平均扭矩**（干预实验：只改腿质量/只改质心/只改惯量） | 这条开放问题卡在任务卡 S-01；不解决，扭矩的物理部分就说不清 | §9、任务卡 S-01 |
| 8 | **公开视频测量（V-05）与社区实测（V-06 的实际数据）** | 这是把任何东西从 E0 抬到 E3 的唯一途径；社区入口已就位，**等数据** | 任务卡 V-05、V-06、§39 |
| 9 | **给帆基因的优化做第二个求解器的交叉核对，并把廉价代理换成可信的** | W-08 已经把帆做成基因，结论是**没好处**；但那条排名只有一个求解器、一个种子、2 代预算，而且循环里用的测力计代理**把排名弄反了**（ρ = 0.303）。换求解器后结论可能变——就像 §38 那样 | §40 §7.3 |

**历史范围的变更**：原报告把沙地/气动储能/3D/柔性列为条件项。2026-11-03 的全层面加固已把气动机械闭环、孪生及海滩集成纳入 H3；实现和核对可以推进，实测校准仍须对应数据。当前不能据此宣布全部功能或真实世界验证完成。

---

## 7. 复现

### 7.1 环境

- **Node ≥ 22**，pnpm 9.14.4（`package.json` 的 `engines` 与 `packageManager`）。
- **Python ≥ 3.10**，用 `./scripts/setup-python.sh` 建 `.venv`（脚本会按依赖顺序 editable 安装 `packages/common`、`packages/sim`、`packages/fab`、`packages/calib`、`packages/rig`、`packages/opt`、`apps/api`、`packages/agent`，再装 pytest 等）。
- 全部命令在仓库根目录执行；Python 命令用 `.venv/bin/python` 或先 `source .venv/bin/activate`。
- 全量自检：`pnpm check`（Biome + 类型 + TS 测试）与 `./scripts/test-python.sh`（含 `scripts/check_doc_refs.py` 与 `--strict` 两遍）。

### 7.2 命令与种子

| 复现什么 | 命令 | 种子 / 确定性 |
|---|---|---|
| **旗舰：起步风速随尺度**（§36） | `.venv/bin/python packages/sim/scripts/start_wind_scale.py experiments/start-wind-vs-scale.json 4 --scales 0.35,0.6,1.0,1.7,3.0 --mass-exponents 1,3 --friction-scales 0.35,0.6,1.0,1.7,3.0 --frictions 0,0.0005,0.002 --k2-scales 1.0,1.7 --probe-cells "0.02:1:0.002;0.03:1:0.002" --max-time 40` | 对同一输入确定性（计时字段除外）。已核对：L = 1 格跑 4 次逐位相同 `(0.489, 0.5106]`，L = 0.35 与 L = 0.02 各 2 次逐位相同 |
| 起步风速敏感性（§28） | `.venv/bin/python packages/sim/scripts/start_wind_sensitivity.py` | 一次只动一个参数 |
| 文献轨迹对照（§30） | `.venv/bin/python scripts/verify_literature_kinematics.py` | 无随机源 |
| 排名稳定性（§33） | `.venv/bin/python scripts/study_ranking_stability.py` | 候选集与 §37 脚本每次运行互相核对，漂移即报错 |
| 多保真度筛选（§37） | `.venv/bin/python packages/opt/scripts/multifidelity_run.py --seeds 3 --keep 5 --top-k 5 --verify` | `--verify` 重算 `deterministic_digest`（`154260cbb9e1e7eb…`）并打印 `determinism check: PASS` |
| 稳健优化（§38） | `.venv/bin/python packages/opt/scripts/robust_run.py --seed 1 --alpha 0.1 --scenarios 20 --evals 128 --popsize 12 --workers 8 --backend k2 --timestep 0.001 --window 2.5 --random-pool 16 --refine-budget 112 --out experiments/robust-optimization.json` | 场景采样、CMA-ES、对抗搜索全部用显式种子。已核对：缩小预算同一条命令跑两次，除墙钟字段外 JSON 逐字段相同 |
| 闭环张开审计（§27） | `.venv/bin/python packages/sim/scripts/fuzz_audit.py experiments/fuzz-audit-64.json 64 1 6` | 生成器种子 1（前 16 个就是 §20 的走兽） |
| 社区提交校验（§39） | `.venv/bin/python scripts/validate_community_measurement.py <file.json>` | 格式校验 |
| 文档引用一致性 | `.venv/bin/python scripts/check_doc_refs.py` | – |

**关于墙钟时间**：旗舰实验 25 格的单格墙钟 MuJoCo **3.5–31.9 min**（均值 11.7 min）、K2 **0.7–0.8 min**；主扫一遍 62.7 min（4 worker），所有格子的墙钟之和 259 min（≈ 4.3 CPU·小时）。**波动的主因是机器负载而不是模型**（本机 10 CPU 与别的 agent 共享，`load average` 冲到 152 时，同一格 L = 1 从 6.6 min 变成 16.9 min）。**读墙钟数字必须连同负载一起读。**

### 7.3 原始数据在哪

| 内容 | 文件 |
|---|---|
| 起步风速随尺度（25 格） | `experiments/start-wind-vs-scale.json` |
| 起步风速敏感性 | `experiments/start-wind-sensitivity.json` |
| 历史文献轨迹对照（来源未核实） | `experiments/literature-jansen-amm2014.json` |
| 排名稳定性（V-04） | `experiments/ranking_stability_v04.json` |
| 多保真度筛选 | `experiments/multifidelity-ranking.json` |
| 稳健优化（含抽样场景、逐场景结果、三个敏感性检查、MuJoCo 核对） | `experiments/robust-optimization.json` |
| 64 走兽审计 | `experiments/fuzz-audit-64.json` |
| 接触/摩擦参数研究（更正后） | `experiments/p1-study.json`（旧版 `experiments/p1-study-before-foot-fix.json`） |
| 每次运行的完整记录 | `experiments/` 下的 JSON，含解析后的完整配置、种子、能量账、事件、诊断 |

**原始记录在 [EXPERIMENTS.md](EXPERIMENTS.md)**：那是逐节的原始记录（每节有日期、任务卡、命令、原始数据路径与结论）；本报告是建立在它上面的论证，只引用数字并给出节号。**两者冲突时以 [EXPERIMENTS.md](EXPERIMENTS.md) 为准**，并且改动 [EXPERIMENTS.md](EXPERIMENTS.md) 需要按项目规则留更正记录。

---

## 8. 附录：本文引用的数字与出处

每个数字都标了出处节号、证据等级，以及"模型内 / 实测"。**没有实测。**

| 数字 | 含义 | 出处 | 等级 | 性质 |
|---|---|---|---|---|
| 0.033 % / 0.191 % | 历史数据中的步长 / 步高相对差，来源未核实 | §30、§46 | E2撤回 | 历史比对，不能作外部验证 |
| 0.0295 | 与来源未核实的24点的形状距离 | §30、§46 | E2撤回 | 历史比对，不能作外部验证 |
| ±0.80 mm | 数字化像素不确定度 | §30 | – | 文献自身的不确定度 |
| 0.2760 / 0.2776 m/rev | MuJoCo / K2 步幅 | §31 | E1 | 模型内（两解） |
| 0.58 % | 两解步幅差 | §31 | E1 | 模型内（两解） |
| +17.6 % | 两解平均扭矩差 | §31 | E0 | 模型内（两解） |
| 0.6920 / 0.7226 m/s | 15 s 判据下 MuJoCo / K2 起步风速 | §31 | E1 | 模型内（两解） |
| 4.4 % | 两解起步风速差 | §31 | E1 | 模型内（两解） |
| (0.479, 0.500] m/s | 起步风速基线区间 | §28 | E0 | 模型内 |
| 0.489 m/s | 起步风速基线估计 | §28 | E0 | 模型内 |
| 1.02–1.07 m/s | 含 0.5 mN·m 销轴摩擦时的起步风速 | §28 | E0 | 模型内（含**假设**） |
| 2.58 / 2.67 mN·m | 准静态 / 慢速动力学的峰值负载扭矩 | §32 | E0 | 模型内 |
| 20.0° / 21.5° | 失速角 θ\* | §32 | E0 | 模型内 |
| 0.685 / 0.697 m/s | 临界起步风速（静力学 / 慢速动力学） | §32 | E0 | 模型内 |
| 8.9 N·m | 更正后的基线平均扭矩 | §9 | E0 | 模型内 |
| ×2.0 / ×2.4 | 摩擦锥类型 / 阻抗比对平均扭矩的影响 | §9 | E0 | 模型内 |
| 4.8 → 12.4 N·m | 管质量对平均扭矩的影响 | §9 | E0 | 模型内（机理不明） |
| 96.5 % / 97 % | 平地电机驱动的接触耗散占比 | §14 / §9 | E0 | 模型内（同一族测量，§9 为四舍五入） |
| 82 % | 帆驱动时关节摩擦与阻尼占输入功的比例 | §14 | E0 | 模型内（含**假设**） |
| 0.433 / 34.8 % | 运动学占空比 / 仿真着地占比 | §14 | E0 | 模型内（两个不同的量） |
| 0.57 → 11.4 mm、0.276 → 0.177 m | 软地面修好后的下沉与步长 | §13 | E0 | 模型内 |
| 14.7 → 8.5 mN·m | 换长度单位后的峰值扭矩变化 | §13 | E0 | 模型内 |
| 9/16 → 0/16 | 时间步修复前后的审计失败数 | §20 | E0 | 模型内 |
| 12/64（19 %） | 64 走兽审计失败数 | §27 | E0 | 模型内 |
| 13.19 mm | 64 走兽里最大的环路开口 | §27 | E0 | 模型内 |
| 9/12 → 1/12 | 环路约束刚化对失败走兽数的影响 | §27 | E0 | 模型内（候选，非修复） |
| 0.6469557 → 0.6776223 | NaN 修复前后金标 GA 的最好适应度 | §26 | E0 | 模型内 |
| −0.8000 / −0.7000 | 粗筛前 5 名内部与动力学顺序的 ρ_s | §37 | E0 | 模型内 |
| 0.4685 / 0.2448 | 粗筛 ↔ 动力学排名的 ρ_s（K2 / MuJoCo） | §37 | E0 | 模型内 |
| 5/5（保留 9/12）、4/5 与 3/5（保留 5/12） | 粗筛淘汰后保住的前 5 名数 | §37 | E0 | 模型内 |
| 0.8462 / 1.0000 | 跨求解器 / 跨摩擦的 ρ_s | §33、§37 | E1 / E0 | 模型内 |
| +0.2728 m / −0.2708 m | 稳健设计在最坏场景的胜负（K2 / MuJoCo） | §38 | E0 | 模型内 |
| +0.007819 m / −0.023271 m | level B 的优势与其翻面 | §38 | E0 | 模型内 |
| −0.501965 m | 参考设计最坏场景的前向距离（沿坡后退） | §38 | E0 | 模型内 |
| 0.380170 m | 罗盘精修相对随机池的增益 | §38 | E0 | 模型内 |
| 12 243 次评估 / 34 min 7 s / 41 次 TypeError | 稳健优化的预算与失败次数 | §38 | – | 模型内 |
| L = 0.35 → 3：0.7998 → 0.3888 m/s | p = 1 的起步风速随尺度 | §36 | E0 | 模型内 |
| p = 3：0.5292 → 0.4153 → 0.4997 → 0.6168 → 0.8647 m/s | p = 3 的非单调 V 形 | §36 | E0 | 模型内 |
| −0.513 / −0.149（p = 1）；+0.595（p = 3） | 逐段 log-log 斜率 | §36 | E0 | 模型内 |
| 2.59× | 销轴摩擦假设造成的起步风速带宽（L = 1） | §36 | E0 | 模型内（含**假设**） |
| (30, inf] | "走不动"的一格（L = 0.02, jf = 0.002） | §36 | E0 | 模型内 |
| L ∈ (0.03, 0.1] | 最小可行尺度（仅在 jf = 0.002 列，上下界都有） | §36 | E0 | 模型内（含**假设**） |
| L_min ≤ 0.35 | 其它三列的最小可行尺度（只有上界） | §36 | E0 | 模型内（含**假设**） |
| +13.9 % / −4.2 % | K2 与 MuJoCo 起步风速之差 | §36 | E1（量级） | 模型内（两解） |
| 0.046 m/s | L = 1 处两个 5 % 区间之间的空隙 | §36 | E0 | 模型内 |
| 4.17 m/s | 15 km/h 的现实上限 | §36 | – | **艺术家的陈述**，只作数量级检查 |
| 0.79 ms / 4.2–26.6 s | 粗筛层 / 复核层的单次代价 | §37 | – | 墙钟（机器负载高，只信量级） |
| −0.033（p = 2 全局） | p = 2 的 log-log 斜率（预注册 0.000） | §36 | E0 | 模型内 |
| 0.4893 / 0.5109 m/s | 固定帆 / 自由帆设计的起步风速（同一权重下） | §40 | E0 | 模型内 |
| +0.0498 / +0.0439 m | 固定帆 / 自由帆的 CVaR（阵风稳健性） | §40 | E0 | 模型内 |
| +0.5815 / +0.4108 m | 固定帆 / 自由帆的名义前进距离 | §40 | E0 | 模型内 |
| −4.4 % / +11.8 % / +29.4 % | 固定帆相对自由帆的三项优势 | §40 | E0 | 模型内 |
| +0.000000 m | 最坏阵风序列上"稳健 vs 名义"的差（默认权重下两者是**同一个基因组**） | §40 | E0 | 模型内 |
| +0.090113 m / −0.009015 m | w = 1 的稳健设计在采样最坏 / 对抗最坏阵风序列上的差 | §40 | E0 | 模型内 |
| ρ = 0.303 / 1.87× | 测力计代理与真实起步风速搜索的一致性（实测 = 代理 × 1.87） | §40 | E0 | 模型内（核对，非验证） |
| 0.5572 m/s | K2 给参考设计的起步风速（与 §28 的 MuJoCo 区间不重叠） | §40 | E0 | 模型内（单解） |
| 4.928 m/s / 0.732 m/s / 0.6884 | 湍流样本的平均风速 / 标准差 / R(2 s) | §34 | E0 | 模型内（核对，非验证） |
| 10.2 % / −20.1 % | 风廓线在 z = 2.0 m / z = 0.2 m 的风速偏差（**假设** α = 0.14） | §34 | E0 | 模型内 |
| +0.825 N / −0.825 N | 顺风 / 逆风时的机体气动力 | §35 | E0 | 模型内 |
| 4 %–8 % | 开启机体迎风面积后起步风速的降低幅度 | §35 | E0 | 模型内（C_d = 1.1 为**假设**） |
| 10 个重复模块 / 上限 10 / 0 次分歧事故 | 跨语言重复实现的跟踪状态 | `contracts/duplicated-modules.json` | – | 仓库事实 |
| 0 条 | 扭矩、电流、起步风速的实测条数 | §39 §7 | – | **实测：空** |

---

*本报告引用的每一个数字都能在 [EXPERIMENTS.md](EXPERIMENTS.md) 找到对应节号；如果你发现某处对不上，以 [EXPERIMENTS.md](EXPERIMENTS.md) 为准，并且请按项目规则留更正记录。*
