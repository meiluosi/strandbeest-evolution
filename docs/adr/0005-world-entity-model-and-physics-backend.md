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
- **契约套件**（`strandbeest_sim/contract.py`，`tests/test_contract.py`）：能量守恒（摆，漂移 2e-7）、摆周期（相对误差 1.5e-4）、斜面加速度（1e-3）、重力方向、快照恢复、确定性、镜像对称（用 `mirror` 操作做出镜像设计）、长度单位缩放不变；另有 5 个故意写坏的后端（重力反向、能量漏掉势能、时钟快 10 %、恢复丢速度、质量按"每单位长度"算）都被抓到。
- 发现：`scenario_from_design` 的伺服增益正比于 `unit_m`，所以把同一个设计换一种长度单位写（`scale` + `keep_physical`）会换一套伺服，峰值力矩 14.7 → 8.5 mN·m（−42 %），平均力矩 −8 %，步幅不变；单位缩放契约在两侧用相同的物理驱动来比较。这是 `from_design` 的行为而非后端的，尚未改。
