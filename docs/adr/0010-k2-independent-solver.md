# ADR-0010: K2 独立平面刚体物理求解器设计 (K2 Independent Planar Rigid-Body Solver)

**状态：接受（2026-10-21，按推荐方案实现并通过全套契约与 MuJoCo 对照）** · 对应任务卡 V-02 · 证据等级梯子 E1

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
