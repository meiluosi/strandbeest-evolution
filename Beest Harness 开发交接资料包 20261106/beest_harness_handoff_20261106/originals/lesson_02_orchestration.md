# Lesson 02：实验编排与调度架构

> Beest Model Experiment Harness · Architecture Research · 2026-11-05  
> 前置课程：[Lesson 01：实验对象与数据模型](https://chatgpt.com/space/page_6aeca18f4df0819194d1c7c41a847ce7)

## 1. 本课目标

设计从研究实验协议到实际计算执行的中间层，回答：

1. Experiment Graph 如何编译为可执行 Job DAG？

2. Worker 如何统一承载仿真、数据处理、训练、评测和校准？

3. Scheduler 如何分配 CPU、GPU、内存、磁盘和预算？

4. Job 失败、进程重启或机器故障后如何安全恢复？

5. 如何处理并发、幂等、缓存、资源隔离与结果提交？

本课定义目标架构与契约，不代表这些功能已在仓库实现。

## 2. 核心判断：Experiment Graph 不等于 Job DAG

### 2.1 Experiment Graph：研究逻辑图

描述研究者想验证什么、需要哪些实验条件、对照与证据。它具有科学语义，长期保存、版本化、可审阅。

例：研究不同模型架构的长期动力学预测能力：

- 固定 Dataset Snapshot 与数据切分。

- 比较 MLP、GRU、Transformer 三种模型。

- 每种模型执行多个独立随机种子 Trial。

- 每个 Trial 训练后保存 Checkpoint。

- 所有 Checkpoint 使用同一 Evaluation Suite。

- 统计跨种子结果，分析长期 Rollout、OOD 和物理一致性。

Experiment Graph 描述“为什么做、比较什么、怎样才算完成”。

### 2.2 Job DAG：计算执行图

描述机器实际要执行的计算节点、依赖、资源和输入输出。它可由 Experiment Graph 编译产生，也可因缓存命中、失败重试、资源限制而发生执行层调整。

Job DAG 描述“具体执行什么、先后顺序、由谁运行、消耗多少资源”。

### 2.3 为什么必须分离

- 同一个 Experiment Graph 可在不同机器、不同 Scheduler 上执行。

- 相同研究计划可产生不同 Job DAG，例如缓存命中时跳过数据处理。

- Job DAG 可以因失败恢复而重排，但不应篡改研究假设。

- 科学条件变化应产生新的 Experiment/Condition 版本；单纯执行重试不应产生新的科学 Trial。

## 3. 目标执行架构

    Experiment Protocol (versioned)
              |
              v
    Experiment Planner / Compiler
              |
              v
    Job DAG (persistent, validated)
              |
              v
    Scheduler <---- Resource Manager / Budget Manager
              |
              v
    Worker Pool / Execution Runtimes
       |          |          |          |
       v          v          v          v
     Data      Training   Simulation  Evaluation
     Worker    Worker     Worker      Worker
       |          |          |          |
       +----------+----------+----------+
                         |
                         v
                Run / Artifact Commit
                         |
                         v
             Provenance + Event + Metrics

组件职责：

- Experiment Planner：把研究协议展开为 Conditions、Trials、任务模板和评测需求。

- DAG Compiler：解析依赖、插入共享数据准备、评测和汇总节点，检查循环与缺失输入。

- Scheduler：选择可运行 Job，检查资源、优先级、预算和并发限制。

- Worker Runtime：执行某种任务类型，报告进度、心跳、日志和产物。

- Artifact/Run Committer：验证产物完整性后原子登记结果与来源关系。

- Event Store：记录状态变更、调度决策、Attempt、资源消耗和异常。

## 4. DAG 编译示例

研究协议：

- Experiment：long-horizon dynamics prediction。

- Dataset Snapshot：ds-v3。

- Conditions：MLP-100K、GRU-100K、Transformer-100K。

- Trials：每个 Condition 使用 seeds 1、2、3。

- Evaluation Suite：rollout-v1。

执行图（简化）：

    Validate Dataset Snapshot
               |
    Prepare Shared Data Manifest
               |
       +-------+--------+
       |       |        |
    Train MLP Train GRU Train Transformer
       |       |        |
    Evaluate Evaluate  Evaluate
       |       |        |
       +-------+--------+
               |
       Aggregate Statistics
               |
         Research Report

实际 Job 粒度需要权衡：可将每个 seed 拆成独立 Job 以获得并行和失败隔离；也可将整组训练放在一个 Worker 内以减少启动开销。建议训练 Trial 独立调度，公共数据准备作为可缓存的共享依赖。

DAG 编译必须检查：

- 每个输入引用存在且版本固定。

- 无环，依赖关系完整。

- 评测节点绑定正确的 Dataset Split 与 Evaluation Suite。

- 不同 Trial 的随机种子和配置明确。

- 资源需求和预算可满足。

- 禁止训练阶段读取测试集标签或测试反馈。

## 5. Worker Protocol：统一接口，不统一内部框架

Worker 是执行任务的运行时插件。不同 Worker 可以用不同语言和依赖。

建议逻辑协议：

- describe()：声明 worker 类型、版本、能力、资源需求和输入输出 Schema。

- validate(input)：预检输入、依赖和环境。

- execute(context, input)：执行任务。

- report_progress(event)：报告阶段、step、指标和消息。

- checkpoint()：在支持的任务中保存恢复点。

- cancel()：响应取消并安全清理。

- finalize()：提交 Run、Artifact 和 Provenance。

- health()：心跳与健康状态。

Execution Context 应提供：

- Job ID、Attempt ID、Trial ID。

- 输入资产的只读引用和内容哈希。

- 输出目录与 Artifact 暂存区。

- 取消信号、超时和预算。

- 日志、指标、进度、心跳接口。

- 密钥与外部资源的受控访问。

首批 Worker：

1. DataProcessingWorker

2. TrainingWorker

3. SimulationWorker（适配现有 MuJoCo/K2）

4. EvaluationWorker

5. CalibrationWorker

6. OptimizationWorker

7. AnalysisWorker

Worker 不应自行修改 Experiment 协议，也不能绕过统一的产物提交与审计流程。

## 6. Scheduler 与资源管理

### 6.1 资源声明

Job 提交前声明资源需求：

| 资源 | 示例 |
|---|---|
| CPU | 4 cores |
| GPU | 1 张，指定显存下限或设备能力 |
| Memory | 12 GiB |
| GPU Memory | 10 GiB |
| Disk | 20 GiB 临时空间 |
| Wall Time | 2 小时 |
| Network | 是否需要外部数据访问 |

资源声明分为：

- Request：调度前要求可分配的资源。

- Limit：运行时不能超过的资源上限。

- Observed Usage：实际消耗，用于容量规划和成本分析。

CPU/GPU 不能只用一个抽象并发数表示。GPU 还涉及设备型号、显存、驱动/CUDA 兼容、共享策略和独占需求。

### 6.2 调度策略

第一阶段建议：

- 本机单用户：资源配额 + 有界 Worker Pool。

- CPU 任务与 GPU 任务分队列。

- 同一 GPU 的训练任务默认限制并发，避免显存超卖。

- Job 优先级分为交互、普通实验、批量后台。

- 采用公平性约束，避免一个大 sweep 占满所有资源。

- 预算在提交前预留，执行后按实际用量结算。

未来才考虑多机、Kubernetes、Slurm 或云端弹性资源；不在首版引入复杂集群依赖。

### 6.3 资源预留与释放

调度器必须保证：

- 只有资源预留成功才能将 Job 标记为 running。

- Worker 退出、崩溃或超时后，租约会过期并释放资源。

- Attempt 的资源使用有独立记录。

- 资源计数不能仅依赖内存变量，服务重启后要能重建。

- GPU 设备不可用或环境不兼容时，应在执行前失败，而不是运行到一半才发现。

## 7. Job 生命周期、Attempt 与幂等

Job 是逻辑任务，Attempt 是一次具体执行。

建议 Job 状态：
queued → dispatching → running → succeeded / failed / cancelled / blocked。

Attempt 状态：
created → leased → running → succeeded / failed / interrupted / cancelled / lost。

每次 Attempt 保存：

- attempt_number、worker_id、host/runtime identity。

- started_at、heartbeat_at、finished_at。

- exit code、错误分类、日志引用。

- 资源使用与预算消耗。

- checkpoint 输入/输出引用。

- 是否可重试及其依据。

### 7.1 幂等原则

任务可能出现“Worker 已完成产物写入，但提交响应丢失”的情况。不能简单重跑并产生重复结果。

建议：

- Job 有稳定逻辑 ID 与输入签名。

- Attempt 有唯一 ID。

- Artifact 使用内容哈希和不可变对象键。

- Run 提交使用幂等 commit key。

- 提交分为暂存、校验、登记、完成几个阶段。

- 只有完整校验的产物才标记为 available。

- 重复提交返回已提交结果，而不是生成重复 Run。

### 7.2 重试分类

| 失败类型 | 默认策略 |
|---|---|
| 网络瞬断、Worker 节点丢失 | 有上限的重试 |
| 可恢复的进程中断 | 从有效 Checkpoint 恢复 |
| OOM | 不盲目重试；降低 batch/资源或转人工 |
| 输入 Schema 错误 | 不重试，修复输入 |
| 模型 NaN/数值发散 | 保留失败证据，通常不自动重试 |
| 物理审计失败 | 结果记为失败或未验证，不用重试掩盖 |
| 预算耗尽 | 暂停或终止，需明确授权增加预算 |

失败原因必须分类，不能把所有异常都当作 transient error。

## 8. Checkpoint 与长任务恢复

训练任务的 Checkpoint 至少应考虑：

- 模型参数。

- Optimizer 状态。

- Scheduler 状态。

- AMP/GradScaler 状态（若使用）。

- 当前 global step / epoch。

- 随机数生成器状态（Python、NumPy、框架、设备）。

- 数据采样器与数据迭代位置。

- Gradient Accumulation 状态（若在 step 中间保存）。

- Training Config、Dataset Snapshot、代码和依赖身份。

恢复时校验：

1. Checkpoint 文件哈希与完整性。

2. 模型结构和配置兼容。

3. Dataset Snapshot 与数据顺序兼容。

4. 训练代码和依赖版本兼容。

5. 随机数与 sampler 状态可恢复。

6. 设备/精度变化是否影响恢复语义。

必须区分：

- Exact Resume：在声明的环境和兼容条件下尽可能连续恢复。

- Warm Start：只加载模型权重继续训练，不能声称是原训练过程的精确续跑。

Checkpoint 写入应采用临时文件/对象，完成校验后原子登记。不要覆盖最后一个已知有效 Checkpoint。

现有仿真 Session Snapshot 与训练 Checkpoint 是不同机制：前者保存物理模拟状态，后者保存训练过程状态，但可以复用统一的 Artifact 与 Provenance 基础设施。

## 9. 缓存与复用

缓存键不能只使用文件名或 Git commit 标签。

建议输入签名包含：

- Job 类型和协议版本。

- 所有输入资产内容哈希。

- 代码/实现身份。

- 依赖与运行时版本。

- 参数、随机种子。

- 相关硬件/数值环境（在结果语义受其影响时）。

缓存复用只适用于语义等价且可核验的任务。随机训练默认不应把不同 seed 合并；若明确要复用同一确定性结果，必须把 seed 和确定性约定纳入输入身份。

缓存是计算优化，不是证据升级。历史产物不得因新代码存在而被重新标记为当前实现结果。

## 10. 取消、超时与资源清理

取消是协作协议，不是强制杀进程一个动作：

- Scheduler 停止派发未开始的子任务。

- Worker 收到取消信号后在安全检查点停止。

- 正在写入的 Artifact 保持 staging，不标记 available。

- 已完成的独立子任务保留结果。

- DAG 的后续节点根据依赖策略标记 blocked/cancelled。

- 预算结算与资源释放必须执行。

- 用户可选择从有效 Checkpoint 重新提交。

## 11. 现有仓库映射与差距

已存在：

- packages/common/dag.py：内存 DAG 执行、依赖校验、线程/进程执行器、基础资源计数、Optimizer ask/tell 协议。

- apps/api/jobs.py：SQLite 持久化 Job、排队、进度、取消、失败记录；进程重启时将运行中的 Job 标记失败。

- apps/api/execution.py：实现身份检查和缓存保护的一部分。

- schemas/run.schema.json：SimulationRun 的 provenance、输入身份、证据字段。

- packages/agent：工具预算、权限和审计。

主要缺口：

- Experiment Graph 持久化与 DAG Compiler。

- Job 与 Job Attempt 分离。

- 持久化资源租约、GPU 感知调度、公平队列。

- Worker Protocol 与 Worker Registry。

- 长时训练 Checkpoint/Resume。

- Artifact staged commit 与幂等提交。

- 失败分类、重试策略与取消传播。

- 资源实际使用统计与成本归因。

- 可重启的 Scheduler 状态恢复。

## 12. 建议的实现边界

不要把所有调度逻辑塞进现有 apps/api/jobs.py。建议逐步抽出：

- ExperimentPlanner：研究协议展开。

- DagCompiler：构建与校验执行图。

- JobStore：逻辑 Job 与 Attempt 持久化。

- Scheduler：队列、资源、优先级和租约。

- WorkerRegistry：能力发现与版本兼容。

- WorkerRuntime：心跳、取消、日志、产物暂存。

- ArtifactCommitter：幂等提交与来源登记。

- CheckpointManager：检查点登记、校验、恢复选择。

首版可以仍然使用 SQLite + 单机 Worker Pool，但接口应避免与 SQLite 或单机进程绑定。

## 13. 本课验收标准

- 同一个 Experiment 能编译出多个 Condition/Trial 的 Job DAG。

- DAG 有环、缺输入、错误数据切分能在执行前被拒绝。

- 至少支持 SimulationWorker、DataProcessingWorker、TrainingWorker、EvaluationWorker 的统一注册与调用。

- CPU/GPU/内存/时间预算能在调度前检查并在运行后核算。

- Job 重试产生新 Attempt，不产生新的 Trial。

- Worker 中断后能识别有效 Checkpoint，并区分 Exact Resume 与 Warm Start。

- Artifact 提交幂等，重复提交不会生成重复 Run。

- 取消、失败和资源释放有可追溯事件。

- 从 Experiment 可以追溯到 Job、Attempt、Run 和 Artifact。

## 14. 待决策问题

1. Experiment Graph 使用声明式 JSON/YAML，还是 Python DSL？建议先声明式协议，必要时允许受控的参数化生成。

2. 首版 Worker 是否全部本机进程？建议 API + 独立 Worker 进程，避免训练任务阻塞 Web 服务。

3. Checkpoint 存储先用本地文件系统还是对象存储抽象？建议先本地文件系统，保留 Storage Adapter。

4. 资源调度首版是否支持 GPU？建议协议支持 GPU，实际调度先实现单机 GPU 独占/配额。

5. 是否采用 Celery/RQ/Prefect 等现成系统？暂不预设；先对照现有 SQLite JobStore 与 DAG，评估引入复杂度和恢复语义后再决定。

## 15. 本课结论

Experiment Graph 管研究逻辑，Job DAG 管计算依赖；Worker 负责执行，Scheduler 负责资源与派发；Job 表示逻辑任务，Attempt 表示执行尝试；Checkpoint 支持长任务恢复；Artifact Committer 保证产物完整与幂等。所有执行状态与产物必须可追溯，但执行成功不能替代科学证据。
