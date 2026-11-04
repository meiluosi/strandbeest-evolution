# ADR-0005: 世界/实体模型与物理后端边界

**状态：接受（2026-10-06，按推荐方案）** · 单向门 #5、#6

**背景** 仿真器现在只会造一个躯干加若干腿，并直接调用 MuJoCo。要做兽群、风源、传感器、障碍、不同求解器，就必须有"世界里有哪些实体"的数据模型和后端的抽象边界。

**选项**
1. 现状：场景 = 单步行者 + 地形配置；MuJoCo 细节渗透到 runner、drives、terrains、scene。
2. **World**（地形、地表、大气、风场、重力）+ **Entity**（组件袋：Linkage、Drive、Body、Sensor、Brain…）；`PhysicsBackend` 协议；MuJoCo 是第一个实现。
3. 直接采用某个现成的实体组件系统：过重。

**推荐** 方案 2。步行者 N=1 只是特例；实体命名空间化（`walker/leg3/bar_K0`）以避免多实体名字冲突。

**PhysicsBackend 协议** `build(world)→handle`、`step(n)`、`snapshot/restore`、`contacts()/forces()/energies()`、`set_param(path, value)`。每个后端必须通过**契约测试**：能量守恒、镜像对称、单位缩放不变、已知解析解（单摆、斜面滑块）。

**后果** `packages/sim` 内部重构（被隔离在一个包里）；场景资产分成 World 与"放进世界的实体"；回放数据按实体组织。

**验证** 契约测试套件；两条腿的两个步行者同场景运行互不干扰；换成一个玩具后端仍能通过契约测试的子集。

**实施记录（E4-01…E4-03，2026-10-06）**
- **World + Entity**：`schemas/scenario.schema.json` 现在是 World（重力、大气、风场、地形）加实体（步行者 = `linkage` + `body` + `drive` 三个组件）加 solver/run。旧的扁平形状保留为 `scenario-v1.schema.json`，是仿真器内部的 `SimConfig`；`strandbeest_common.scenario.to_v2/flatten` 互为逆（在 10 条金标场景上验证），`load_scenario` 两种都收。一个世界里放多个步行者（E4-04）还没做，`flatten` 会明确拒绝。
- **PhysicsBackend**（`strandbeest_sim/backend.py`）：`build`、`build_reference`（契约测试用的标准系统）、`step`、`snapshot/restore`、`set_param`（`gravity`、`contact.softness`）、`contacts`（含世界系下的接触力）、`forces`、`energies`，以及驱动和回放需要的关节/物体读取和驱动量写入。地形变成与引擎无关的 `TerrainPlan`（障碍块、坡度、软硬）。**只有 `backends/mujoco_backend.py` 导入 mujoco**（测试里有检查）。
- **行为不变**：10 条金标运行（`contracts/sim-golden`）在重构前后逐项一致（rtol 1e-7，同平台），重构前还修了一个 bug（"软地面"一直没有效果，见 EXPERIMENTS §13）。快照只含引擎的积分状态，**不含**对模型参数的修改（例如已释放的驱动器）。
- **契约套件**（`strandbeest_sim/contract.py`，`packages/sim/tests/test_contract.py`）：能量守恒（摆，漂移 2e-7）、摆周期（相对误差 1.5e-4）、斜面加速度（1e-3）、重力方向、快照恢复、确定性、镜像对称（用 `mirror` 操作做出镜像设计）、长度单位缩放不变；另有 5 个故意写坏的后端（重力反向、能量漏掉势能、时钟快 10 %、恢复丢速度、质量按"每单位长度"算）都被抓到。
- 发现：`scenario_from_design` 的伺服增益正比于 `unit_m`，所以把同一个设计换一种长度单位写（`scale` + `keep_physical`）会换一套伺服，峰值力矩 14.7 → 8.5 mN·m（−42 %），平均力矩 −8 %，步幅不变；单位缩放契约在两侧用相同的物理驱动来比较。这是 `from_design` 的行为而非后端的，尚未改。

## 校准接入后端（2026-11-04，H1-03 / H3-03）

数字孪生的前向模型改为显式 Design/Scenario 的观测适配器：调用实际 MuJoCo 后端，读取指定足端和机体的世界系位置、曲柄角及扭矩；不再另造柔度、摩擦或沙地修正公式。观测坐标为足端中心相对机体中心的世界 x/z 分量，时间零点为沉降后的驱动开始。采样超出原生运行时域或比积分步长更细时拒绝外推。

拟合与应用 Profile 共用参数注册表。销轴摩擦为关节库仑摩擦力矩（N·m）；接触刚度和等效沙地刚度为 MuJoCo 的质量归一参数（1/s²），不是杆弹性或颗粒流。K2 的软接触刚度使用不同量纲，不能复用这些校准值；本轮物理映射仅承诺 MuJoCo。刚性后端没有杆柔性自由度，`bar_flexibility` 与旧玩具别名明确拒绝。

Profile 保存基准 Scenario、Design 内容哈希及 `beest-physical-v2` 映射版本；缺少映射的历史 Profile 仍可读取，但应用前须重新校准。正常曲线校准采用 Measurement 的电机转速、恒定风速和坡度；描述性地面文字不转换成猜测的材料系数。轨迹反演报告每次实际 Scenario/实现身份、独立参数点上的代理误差、未参与拟合的时间后段误差与原生灵敏度。单链后验和合成恢复不构成真实实验验证；见 EXPERIMENTS §55。

2026-11-04 接触阻尼修正：单兽、多兽和浏览器均按 MuJoCo 质量归一化公式 `2ζ√k` 换算阻尼，不乘估算支撑质量。Profile v1 保持可读但应用前须重新拟合；soft/sand 的直接参数覆盖不变。独立解析接触实验、跨端/金标差异及负结果见 EXPERIMENTS §59。

2026-11-04 气体基础修正（H3-02进行中）：独立`FluidNetwork`按实际流向传输上游焓，分别记录外部质量/焓、运动边界功、对流热、经验多变热和恒温器热；质量/能量差额保留积分误差。泵`reaction_torque`明确为气体作用在曲柄上的力矩，压缩行程取负，输入气体的机械功率取`-tau*omega`。这些量尚未接到`PhysicsBackend`、整机Run账或会话快照；壁面热储能仍未实现。未来集成必须将气体质量/能量、阀态、机械反力及外部热源同时纳入状态与能量边界，不能只显示瓶压或把放气当作免费驱动。解析回归、旧缺陷及数值限制见EXPERIMENTS §66。
