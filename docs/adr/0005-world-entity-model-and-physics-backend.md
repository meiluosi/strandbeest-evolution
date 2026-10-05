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
