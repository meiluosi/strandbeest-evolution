# Harness 基线与接口差异（HF-00）

> 核对日期：2026-11-06。固定基线为 `refactor/harness-frontend` 的 `05ad213977f699b923b106eeb9c417c10913b401`（HF-03 检查点）。本文记录该时刻的真实能力与后续接口边界，不回退既有 H 卡或物理验收。

## 1. 环境与已有检查

- Node `v26.13.0`，pnpm `9.14.4`，Python `3.12.10`；Node 满足仓库 `>=22` 要求。依赖锁和既有工作区保持不变。
- HF-03 检查点的 `pnpm check` 通过：454 项 JS 测试（core 195、sim-web 198、web 61），Svelte 0 错误、0 警告；Web 生产构建和硬编码中文检查通过。
- 固定 Linux Chromium 完整矩阵共 124 项，94 项通过、30 项按 live/static 模式预期跳过；20 张新工作台基线及 6 张既有静态回放基线已审查。未验证 Firefox／WebKit。
- 两份真实制造下载各验证 18 个封闭网格和 3 个负向对照；这不是实体制造或物理验证。历史物理缺口仍以 `ARCHITECTURE.md`、`EXPERIMENTS.md` 和 H 卡为准。

## 2. Shell、深链与状态主权

| 区域 | 当前事实源 | 已验证行为 | 不能据此宣称 |
|---|---|---|---|
| Shell 与研究空态 | `App.svelte`、`ResearchTab.svelte` | 分组导航、真实空态、主题、语言、在线状态、命令面板 | 已选择或持久化 Experiment |
| 深链 | URL `tab` 与研究 `view` 查询参数 | 旧 `?tab=design|evolve|sim|fab|beach|lab` 和 `?tab=research&view=...` 可用 | 用 `latest` 恢复冻结科学输入 |
| Design | `editor.svelte.ts` 与 Operation 日志 | 预览、提交、撤销、分支和本地设计上下文 | 浏览器本地日志等于服务端实验修订 |
| GA／MAP-Elites | `Evolver.svelte`、Worker 与既有图鉴 API | 固定快照、固定 seed、停止清理、最佳回写 | GA 运行等于训练 Trial |
| Replay | `ScenePlayer.svelte` 与真实 Replay | 统一时钟、seek、A/B、取消和来源标签 | 静态烘焙等于新执行 |
| 制造／实验室 | 既有 FastAPI 与本地文件／SQLite | 真实检查、导出、测量和校准路径 | 导出成功等于实体制造验证 |
| 数字海滩 | `DigitalBeachSim` 独立规则模型 | 本地交互、生成、删除和播放控制 | 已接入 PhysicsBackend 或共享风场 |
| live/static | 构建模式和真实 API 可用性 | live 查询／执行与 static 只读能力有明确边界 | static 可保存、训练或审批 |

## 3. HN01–HN06 接口差异

| 工作包 | 已有可复用能力 | 缺失接口／对象 | 下一步边界 |
|---|---|---|---|
| HN01 基线与领域契约 | ULID、规范化 JSON／SHA-256、Design／Scenario／Run／Measurement／Profile Schema、旧资产内存迁移、旧 API；最小切片已有 `/api/harness/v1`、Experiment、不可变 ExperimentRevision、Condition／Trial、独立权威血缘 | 执行授权、Job／Attempt 和完整协议操作仍缺 | 当前仅创建／读取／修订和引用校验，不启动计算 |
| HN02 数据与资产链路 | Run 文件、NPZ／Parquet 遥测、Measurement、旧来源投影；最小切片已有 DatasetSnapshot、SplitManifest、泄漏与篡改检查 | Parquet 适配、训练拟合变换和通用 Artifact 提交仍缺 | 当前仅真实 NPZ，按 Run episode 和 design_id 分组；不是完整 HN02 验收 |
| HN03 最小执行与可靠性 | 旧 JobStore、线程池、取消、重启恢复 | Harness Job／Attempt、fencing、事务提交、预算、事件和恢复 | 不让旧 Worker 与 Harness 双头领取同一任务 |
| HN04 小模型训练 | 真实轨迹与数值工具 | ModelSpecRevision、TrainingConfig、CPU 训练器、Checkpoint、ModelArtifact | 依赖 HN02 快照和 HN03 最小执行，不产生占位指标 |
| HN05 评测与证据 | EvidenceBadge、旧 Run 审计和校准负结果 | EvaluationSuite／Run、一步／滚动评测、失败分母、Claim／Gate | 缺证据和负结果不得显示为科学通过 |
| HN06 Svelte 研究旅程 | HF-01～HF-03 Shell、设计系统、全部领域工作台 | HF-04 真实协议／血缘、HF-05 执行／预测、HF-06 证据和 HF-08 集成 | 只接真实服务端投影；HF-07 属于 M3 |

## 4. 存储与迁移决定

- 新 API 使用 `/api/harness/v1`，旧路由语义不变。
- 新权威表使用 `harness_` 前缀；不可变文档保留规范内容摘要。旧 `_reindex()` 可以重建旧 `runs`／`provenance_edges` 投影，但不得删除 Harness 权威关系。
- 旧资产按原 ID 和实际文件摘要引用；导入时间、当前实现或证据等级不得倒填成历史事实。
- 独立复验通过显式新 Trial 表达，不使用 Run 缓存代替新统计重复。执行、授权和预算不属于 HF-00 或最小 HN01／HN02 的完成范围。

## 5. HN01／HN02 最小接口现状（2026-11-06）

`apps/api/src/strandbeest_api/harness.py` 提供 `/api/harness/v1` 的实验列表／详情、实验创建、当前修订派生、修订读取／校验、NPZ 快照创建／读取／校验和直接血缘查询。新文档位于 `experiments/` 与 `dataset-snapshots/`，索引和权威边使用 `harness.db` 的 `harness_` 表；既有 `_reindex()` 不清理这些关系。

- `ExperimentRevision` 和 `DatasetSnapshot` Schema 位于 `schemas/`，摘要由 common 的规范化 JSON／SHA-256 计算。
- 修订派生必须引用当前 `base_id`；Condition／Trial 由服务端生成新 ULID，显式新 Trial 不被内容缓存去重。
- 快照核对 Run 文档摘要、NPZ 字节摘要、通道和样本长度，Split 必须完整覆盖且 train／test 至少各有一组。
- 校验接口只确认当前契约与来源一致，返回 `execution_authorized: false`；不会启动任务、产生授权或宣称科学结论。
- 定向 common／API 测试 25 项通过，common／API 回归 363 项通过（Windows、Python UTF-8 模式）。未进行浏览器矩阵，因为本切片没有前端变更。
