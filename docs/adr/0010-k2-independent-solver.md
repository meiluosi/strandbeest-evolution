# ADR-0010: K2 独立平面刚体物理求解器设计 (K2 Independent Planar Rigid-Body Solver)

**状态：接受（2026-10-21，按推荐方案实现并通过全套契约与 MuJoCo 对照）** · 对应任务卡 V-02 · 证据等级梯子 E1

## 2026-11-04 实施核对与适用边界（H0-01）

上面的历史状态及下文数学方案不表示所有细节已经落地。以下区分当前 `K2Backend` 与原方案的差异，以及EXPERIMENTS §73–§76的实现修复；历史实验数值保留各自版本，不改写为新实现的结果。

- 四维状态 `X/Z/Phi/psi` 现使用逐杆质量和形状惯量投影得到的完整构型相关质量矩阵，包含平移、躯干与曲柄耦合、全部质心重力和速度偏置。§75替换了此前恒定对角阵及任意曲柄惯量；锁定俯仰时先限制允许坐标再求逆。惯性核对与整机动力学验收分开。
- 足端及惯性由2880点周期五次Hermite表获得，位置及一、二阶导数在接缝连续；插值速度是同一位置插值的导数。表中节点导数采用六阶周期差分。§75保留1440点版本的六处惯性核对失败，细化后在相同误差门槛下通过原4,096个惯性相位，并保留原接触相位扩充到6,144次核对。球足接触速度计入所属杆件和躯干转动。几何来自共同Rust内核与模型生成器；动力学/接触代码独立，不是两套独立运动学或几何声明。
- 接触现按`Scenario.solver.iterations`执行，并加入同时方程的接触模式修正；此前固定12轮、与保存输入100轮不符的错误在§76修复。投影残差需满足按各分量尺度计算的浮点舍入量级检查；预算内未收敛会报错，不推进位置和时间。只用一个`foot_friction`系数，未分别配置`mu_s` / `mu_k`；收敛只代表满足所声明的接触方程，不保证所有触点无滑移。销轴摩擦仍仅在非零转速按符号施加，不能承诺任意零速静摩擦锁定。
- 障碍物实体尚未进入这条接触路径。软地面仍有明确的未修复契约错误：共享`TerrainPlan.softness`声明质量归一化刚度1/s²和阻尼1/s，而K2仍按N/m解释刚度并忽略阻尼；不能用同数值直接声称两后端工况等价。0.15穿透稳定化及接触柔顺机制仍待验证和具名配置；§76没有调这些物理/稳定化输入。
- 当前只有 Python K2 后端；浏览器运行 MuJoCo WASM。原文“单步微秒级”的推测没有当前 H5-02 的固定设备/场景基准支持。

2026-11-04 补充：共享 Scenario 新增可空的 `solver.tolerance`，用于显式记录 MuJoCo 提前停止精度。K2 对显式数值（包括0）报错，避免假装执行不支持的选项；null 保持各后端已记录版本的默认行为。两版本迁移、原生/浏览器编译和 K2 拒绝路径均有回归，见 EXPERIMENTS §68。该选项没有使两种求解器的物理假设变得相同。

原契约和慢速步幅对照保留其明确场景范围。新排名仍须 H2-02 的多种子、同输入双后端复验；这份状态核对没有新增 E1/E2/E3 结果。

2026-11-04 执行修复（EXPERIMENTS §73）：K2此前忽略`Scenario.solver.timestep`，默认实际按0.5 ms执行，可能与保存场景中的0.1 ms不符；现在实际时间步以Scenario为准。显式构造器时间步与场景冲突会报错；优化调用已改为将时间步写入场景，MuJoCo与K2使用同一入口。另修复周期接缝、球足转动、初始高度、错误球足名称、重建后的接触软度残留、不可行质量被替换为0.1 kg及无限扭矩的null处理。原64样本4,096个相位的接触运动核对通过；首版插值的两处失败保留。

§73当时没有补齐独立动力学验收：四个固定难例的能量残差为31.56%、101.61%、43.62%、13.38%，均超过2%；第61号与有向理想参考相差84.66%。包括旧实现和中间版本的20次能量失败保留，不改写为后续实现的结果。

2026-11-04 离散功修复（EXPERIMENTS §74）：`StepWork`按实际力/冲量与步前、步后平均速度核算驱动功、法向/切向接触转移及实际施加的关节摩擦；静止接触后的零滑移不再被当作零能量损失。所有转移保留符号；穿透稳定化可能注入能量，不能裁为零。积分产生的有向机械能变化独立记录为`e_numerical`，不抵消2%审计残差。内部驱动对相对曲柄角做功，移除错误的额外广义躯干力矩；真实反向转动仍需完整耦合质量矩阵。原始K2内存快照升级为完整状态，包含外力、前步载荷、惯性配置与离散功；缺字段的旧原始快照明确拒绝，历史Run/轨迹继续可读。

§74当时，同输入的八次配对复跑在两种时间步下均保持14列非能量数据逐项完全一致；原64样本、seed=1、0.1 ms及600 s上限的全量复跑无数值检查失败，最大能量残差0.458%。这只证明当时恒定对角质量阵的离散能量账一致，v2仍为64未验证，第61号步幅差异未解决。历史数值、实际时间步与实现身份不能自动继承，不提高物理证据等级。

2026-11-04 完整惯性修复（EXPERIMENTS §75）：`WalkerInertia`逐项读取共享几何声明的箱体、胶囊及球形足质量和尺寸，独立计算平移/转动惯量、重力势能和运动耦合；不调用MuJoCo动力学算法。仅使用驱动显式配置的armature，不再添加虚构曲柄惯量。相对电机的反向躯干响应来自完整质量矩阵；黏性阻尼和有扭矩上限的速度伺服采用隐式冲量，功账仍使用实际力与平均速度。所有杆件位姿、旋转和整体质心由同一构型计算；销轴阻尼/非零速度摩擦投影各铰链的实际相对转速，零速摩擦限制保留。

数值能量诊断现包含质量矩阵变化、偏置/重力积分与势能更新误差，仍不抵消审计残差。独立核对通过原生MuJoCo的极大坐标质量矩阵与偏置、另行有限差分的坐标映射进行投影；它核实惯性组装，仍共享模型几何，不等于独立动态对照或实测。实现身份增加`k2-inertia-v1`；初版与细化版的内容指纹不同，旧缓存不复用。形状约定来源：[MuJoCo惯量推断](https://mujoco.readthedocs.io/en/stable/XMLreference.html#compiler-inertiafromgeom)、[已安装3.17.0版本的形状惯量实现](https://github.com/google-deepmind/mujoco/blob/3.17.0/src/user/user_objects.cc#L3963)。

2026-11-04 接触求解修复（EXPERIMENTS §76）：仅将逐点投影迭代从12轮改为记录的100轮仍不足，第20/61号分别有169/632个积分步骤的法向或切向投影残差超过1e−8 m/s；独立模式枚举给出可行解，旧解的曲柄速度最大相差1.55469 rad/s。现在逐点投影确定候选模式，再同时求解该模式的法向接触、库仑摩擦和受限电机方程；局部模式循环时探索相邻模式，每轮至多一次稠密修正，仍受场景预算限制。重复接触通过增量最小二乘保留当前零空间冲量。判断使用128倍机器epsilon及每个分量自身的计算尺度，不把m/s、rad/s与N·m·s混成一个绝对阈值；它是数值检查，不是严格误差界证明或独立物理验证。初版100轮记录和开发中未解出的状态保留，最终语义身份为`k2-contact-v4`。较粗0.5 ms下第20/61号即使每步收敛，也未在30 s诊断时限内完成预定转数，因此不能由单步收敛推出整机时间步已经收敛。

---

## 1. 背景与动机

在 Beest Engine 的仿真与验证体系中，现有动力学仿真完全依赖 MuJoCo（`strandbeest_sim/backends/mujoco_backend.py`）。然而，依赖单一第三方物理引擎存在根本性验证瓶颈：

1. **证据等级约束（[docs/VALIDATION.md](../VALIDATION.md)）**：
   - 证据等级 **E1** 的严格定义是：**"两个独立物理求解器对同一设计的行为在约定容差内一致"**。
   - 仅对 MuJoCo 重复微调求解器参数（如 `solref`、`solimp`、`impratio`）并不能消除引擎本身的系统性建模假设。
2. **低速粘滑与起步风速的不确定性（[docs/WIND.md](../WIND.md) §4）**：
   - MuJoCo 使用基于二次规划（PGS/Newton）的软化摩擦锥松弛模型。在速度接近零时，静摩擦被正则化为微小粘性滑移（`slip > 0`），导致在极低外力下产生微观蠕变。
   - 风驱动走兽的起步风速 $v_\text{start}$ 取决于静止状态下的真实库仑静摩擦阈值 $\mu_s N$ 与销轴静摩擦。必须有一个采用**真实无软化库仑静摩擦阈值**的独立求解器进行交叉比对。
3. **闭环约束刚度与张开问题（[docs/EXPERIMENTS.md](../EXPERIMENTS.md) §27）**：
   - MuJoCo 中闭环机构采用等式约束弹簧阻尼惩罚（`solref`），在高速或大负载下存在几毫米的弹性张开。
   - 独立求解器应提供结构性不张开的基准对比。

---

## 2. 方法选择与评估（Options Considered）

### 选项 1：极大坐标系（Maximal Coordinates）+ DAE + 互补性接触（LCP）
- **原理**：将躯干与每一根连杆视为独立的二维平面刚体，每个刚体拥有 3 个自由度 $(x, z, \theta)$。铰链以代数约束方程 $\Phi(q) = 0$ 表达，建立微分代数方程（DAE）并使用广义 Baumgarte 稳定化或投影法。
- **优点**：拓扑通用，可直接处理任意平面开环或闭环机构。
- **缺点**：自由度数大（每条腿 8 根杆 $\times 6$ 条腿 $= 48$ 个刚体，144 维状态）；闭环同样存在数值约束漂移；求解代数方程开销大。

### 选项 2：广义降维坐标系（Reduced Coordinates: 3-DOF 躯干 + 1-DOF 曲柄驱动）+ 运动学投影 + 脉冲接触
- **原理**：
  - 核心观察：Theo Jansen 走兽的所有腿部连杆被中心曲柄轴 $\psi \in \mathbb{S}^1$ 严格驱动，几何拓扑在设计上具备解析闭环解（`LinkageSpec` 封闭闭式解）。
  - 系统广义坐标仅为 4 维：躯干平面位姿 $[X, Z, \Phi]^T \in \mathbb{R}^3$ 与主动曲柄角 $\psi \in \mathbb{S}^1$（$q = [X, Z, \Phi, \psi]^T \in \mathbb{R}^4$）。
  - 连杆质量与转动惯量通过解析运动学雅可比矩阵 $J_k(\psi)$ 严格投影到曲柄自由度上，形成对称正定广义质量矩阵 $M(q) \in \mathbb{R}^{4 \times 4}$。
  - 闭环约束残差在数学上**恒等于 0**（由解析二元组几何严格保证，彻底免除闭环张开问题）。
  - 足端地面接触采用 Moreau 速度级时间步进法（Time-stepping / Velocity-level Complementarity）：
    - 法向非穿透单边条件：$v_{n,i}^+ \ge 0 \perp P_{n,i} \ge 0$。
    - 切向采用严格二维库仑摩擦定律（带离散静摩擦阈值 $\mu_s$ 与动摩擦 $\mu_k$）。
- **优点**：
  - 状态维度仅为 4，矩阵求逆为 $4 \times 4$，计算效率极高（单步微秒级）。
  - 绝对无闭环张开（zero loop-residual by construction）。
  - 静摩擦为严格零速度锁定（$v_{t,i}^+ = 0$ 当且仅当 $|P_{t,i}^\text{trial}| \le \mu_s P_{n,i}$），完美回应 WIND.md §4 的起步粘滑验证需求。
  - 架构完全独立于 MuJoCo，不引入任何 C 绑定，支持全平台与前端纯 TS 运行。
- **缺点**：仅适用于由主轴驱动的单自由度闭环连杆族（完全覆盖 Beest Engine 的当前设计模型）。

### 选项 3：事件驱动混合动力学系统（Event-Driven Hybrid Dynamics）
- **原理**：在足端着地、离地、静摩擦锁定、动摩擦滑移之间显式划分混合离散模式，在事件发生点进行精确零根搜索。
- **优点**：在单足阶段可达解析精度。
- **缺点**：6 足多触点碰撞时存在组合爆炸（$2^N$ 种接触模式切换），易陷入震荡（chattering / Zeno 现象）。

---

## 3. 架构决定与推荐方案

决定采纳 **选项 2（广义降维坐标系 + 离散脉冲互补接触）** 作为 K2 独立求解器的核心数学模型。

### 3.1 动力学方程
广义坐标：
$$q = \begin{bmatrix} X & Z & \Phi & \psi \end{bmatrix}^T \in \mathbb{R}^4$$

动力学方程：
$$M(q) \ddot{q} + C(q, \dot{q}) \dot{q} + G(q) = \tau_\text{ext} + \sum_{i \in \text{contacts}} J_{c,i}(q)^T \lambda_i$$

其中：
1. **广义质量矩阵 $M(q)$**：
   - 躯干部分：$M_\text{torso} = \operatorname{diag}(m_\text{torso}, m_\text{torso}, I_\text{torso}, 0)$。
   - 连杆等效惯量：曲柄轴角动量投影 $I_\text{eq}(\psi) = \sum_{k} \left( m_k \|J_{v,k}(\psi)\|^2 + I_k J_{\omega,k}(\psi)^2 \right)$。
2. **外力与驱动矩 $\tau_\text{ext}$**：
   - 风帆驱动矩 $\tau_\text{sail}(v_\text{wind}, \dot{\psi})$（同 `strandbeest_sim.drives.SailDrive` 物理公式）。
   - 驱动电机或速度伺服（$\tau = K_p (\psi_\text{target} - \psi) - K_v \dot{\psi}$）。
   - 销轴库仑摩擦阻力矩 $\tau_\text{pin} = - \tau_\text{friction} \operatorname{sgn}(\dot{\psi})$。
3. **接触约束雅可比 $J_{c,i}(q)$**：
   - 足端位置 $p_i(q) = \begin{bmatrix} X \\ Z \end{bmatrix} + R(\Phi) \left( p_\text{hip,i} + p_\text{foot,i}(\psi + \Delta \psi_i) \right)$。
   - 足端速度分解为法向 $v_{n,i}$ 与切向 $v_{t,i}$。

### 3.2 接触求解器（Projected Gauss-Seidel on Contact Impulses）
采用速度级离散脉冲时间步进（Moreau-type time-stepping）：
对于每一触地足端 $i$：
1. 预测未约束速度 $\tilde{v}^+ = \dot{q}^- + \Delta t M^{-1} (\tau_\text{ext} - C - G)$。
2. 计算接触空间 Delassus 矩阵 $W = J_c M^{-1} J_c^T$。
3. 法向冲量投影：$P_{n,i} = \max\left(0, P_{n,i} - \frac{v_{n,i}}{\Delta t W_{nn}}\right)$。
4. 真实库仑切向摩擦冲量投影：
   - 试探切向冲量：$P_{t,i}^\text{trial} = P_{t,i} - \frac{v_{t,i}}{\Delta t W_{tt}}$。
   - 静摩擦判断：若 $|P_{t,i}^\text{trial}| \le \mu_s P_{n,i}$，则 $P_{t,i} = P_{t,i}^\text{trial}$（足端相对地面速度严格归零，实现真实静止锁定）；
   - 动摩擦滑移：否则 $P_{t,i} = \mu_k P_{n,i} \operatorname{sgn}(P_{t,i}^\text{trial})$。

---

## 4. 接口与规范

K2 求解器将作为 `PhysicsBackend` 的第二个官方实现封装在：
- Python 端：`packages/sim/src/strandbeest_sim/backends/k2_backend.py`（类名 `K2Backend`）。
- 接口严格遵守 `strandbeest_sim/backend.py` 中的 `PhysicsBackend` Protocol：
  - `build(cfg: SimConfig, plan: TerrainPlan) -> BuildInfo`
  - `build_reference(kind: str, **params: float) -> None`（支持 `"pendulum"` 与 `"block"`）
  - `step(n: int = 1) -> None`
  - `snapshot() -> Snapshot` / `restore(snap: Snapshot) -> None`
  - `contacts()`, `forces()`, `energies()`, `foot_loads()`, `power_balance()`
  - `set_param(path: str, value: Any) -> None`

**独立性保证**：
- `k2_backend.py` 内部**禁止导入 mujoco**（由 CI 与单元测试自动静态扫描检查）。
- 与 MuJoCo 后端共享相同的输入（`SimConfig` + `TerrainPlan`）并输出标准 `Run` 格式。

---

## 5. 验收标准与验证方案（V-02）

1. **契约测试套件全绿**：
   - 运行 `strandbeest_sim/contract.py` 中全部 8 项契约检查：
     - `energy_conservation`（无摩擦单摆能量漂移 $< 1\%$）
     - `pendulum_period`（微小摆动周期相对误差 $< 0.5\%$）
     - `incline_acceleration`（斜面滑块加速度误差 $< 3\%$）
     - `gravity_direction`（重力方向）
     - `snapshot_restore`（状态快照逐 bit 恢复）
     - `determinism`（两次运行位姿完全一致）
     - `mirror_symmetry`（镜像设计走兽镜像对称步态）
     - `unit_scaling`（物理单位缩放不变性）
2. **突变体检查（Mutants Check）**：
   - 故意向 K2 注入 5 种 bug（重力反向、能量漏掉势能、时钟错误、快照丢失速度、惯量计算错误），确保套件全部能准确捕获报警。
3. **慢速平地步幅与 MuJoCo 对比**：
   - 运行标准 Jansen 6 足模型，在慢速定常驱动下对比每圈步幅（`stride_per_rev`），相对差异在约定容差（$< 5\%$）内。
4. **起步风速敏感性对照**：
   - 在相同摩擦参数下计算起步风速 $v_\text{start}$，客观记录两者差异，并在 `docs/EXPERIMENTS.md` §31 中诚实分析（对比 MuJoCo 软化蠕变 vs K2 真实静摩擦锁定）。
5. **证据等级晋升**：
   - 经 K2 交叉验证后的平地步幅结果晋升为 **E1（两个独立求解器一致）**。

§76完整结果进一步限制上述单步结论：原64样本为1失败/63未验证；第16号支撑率受日志采样影响（每20步5.58%，每步3.10%，原采样点逐位一致），峰值穿透也被漏采。原失败必须保留，逐步验收统计另行修复。第61号在0.025 ms下未完成30 s诊断，不能声称细化时间步已建立动力学收敛。
