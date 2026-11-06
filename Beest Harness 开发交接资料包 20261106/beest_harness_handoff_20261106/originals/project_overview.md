# Beest Model Experiment Harness

## 项目定位

面向物理世界模型与具身智能研究的实验编排、模型训练、仿真验证和证据管理平台。

以现有开源仓库 [meiluosi/strandbeest-evolution](https://github.com/meiluosi/strandbeest-evolution) 为基础，在保留风力兽设计、演化、物理仿真、制造、测量和可视化特色的基础上，逐步补齐模型实验 Harness 能力。目标不是重写 Beest Engine，也不是另造通用 MLOps，而是在现有物理实验平台上建立可复现、可追溯、可评估、可迭代的研究闭环。

## 三个架构原则

1. **研究问题优先于工具**：所有模块服务于可检验的研究问题。

2. **实验结果可追溯、可复现**：结果关联数据、模型、配置、代码身份、环境、执行过程和来源。

3. **AI 加速研究，人类把关证据**：Agent 可以提出、规划、执行和分析实验，但不能自行宣布科学假设成立。

## 六层目标架构

1. **L1 Domain Engine**：Beest Core、MuJoCo、K2、Design、Scenario、Measurement。

2. **L2 Worker & Runtime**：Simulation、Data Processing、Training、Evaluation、Calibration、Optimization Workers。

3. **L3 Execution & Scheduling**：Experiment Graph、Job DAG、Scheduler、资源管理、恢复和预算。

4. **L4 Model & Data Management**：Dataset、Model、Checkpoint、Artifact、Lineage。

5. **L5 Evaluation & Evidence**：基线、多种子、泛化、鲁棒性、物理一致性、证据分级。

6. **L6 Research Agent**：假设生成、实验规划、失败分析、下一轮实验建议。

横向能力：Schema/Contract、Provenance、Observability、Budget、Permissions、Reproducibility。

## 研究课程

- Lesson 01：实验对象与数据模型。

- Lesson 02：实验编排与调度架构。

- Lesson 03：数据与模型生命周期。

- Lesson 04：模型评测与证据体系。

- Lesson 05：Research Agent。

- Lesson 06：整体系统架构与开发规格。

每课形成独立文档，最终汇总为可交给其他 Agent 实施的架构规划、Schema/API 契约、迁移路线与验收标准。

## 当前贯穿案例

研究问题：学习模型能否预测风力兽在不同状态、动作/驱动和环境条件下的未来运动？

以现有物理仿真器生成数据，训练 MLP、GRU 等时序模型，比较一步预测、长期 Rollout、跨设计/风场泛化与物理一致性。必须区分“拟合现有仿真器”与“验证真实物理世界”，不能把前者误称为后者。

## 现有仓库基础

已存在：

- Design、Scenario、Run、Measurement、Profile 等资产与 JSON Schema。

- packages/core：运动学、演化、编辑操作。

- packages/sim：MuJoCo、K2、场景、遥测、审计。

- packages/opt：CMA-ES、多保真、稳健优化、MAP-Elites。

- packages/calib、packages/rig：校准、测量导入与质量检查。

- packages/common：DAG、哈希、资产、证据、遥测。

- packages/agent：MCP、预算、权限、审计和 Agent Benchmark。

- apps/api：持久化 Job、取消、恢复处理、实验 API。

- apps/web-demo：设计、仿真、制造、实验室界面。

主要缺口：
Experiment/Condition/Trial 协议；通用 Dataset Snapshot；Model/TrainingRun/Checkpoint 生命周期；Training Worker；通用 EvaluationRun 与评测协议；长时任务 Checkpoint 恢复；Research Agent 研究闭环。

## Agent 交接规则

- 本 Space 是研究规划与架构文档的长期归档位置。

- GitHub 仓库是代码与现有项目事实的来源；不要仅凭规划文档假设功能已实现。

- 先读本总览和对应 Lesson，再检查仓库当前 main 分支及相关代码。

- 未经用户明确要求，不修改 GitHub 仓库、不提交、不发布。

- 每项规划区分：现有实现、建议设计、待验证假设、尚未实现。

- 变更现有 Schema 时必须考虑向后兼容、迁移、契约测试和历史数据。

- 保留负面结果、证据等级和未验证状态，不放宽阈值制造通过结果。

## 关键来源

- [GitHub 仓库](https://github.com/meiluosi/strandbeest-evolution)

- [当前架构](https://github.com/meiluosi/strandbeest-evolution/blob/main/docs/ARCHITECTURE.md)

- [平台设计](https://github.com/meiluosi/strandbeest-evolution/blob/main/docs/PLATFORM.md)

- [引擎蓝图](https://github.com/meiluosi/strandbeest-evolution/blob/main/docs/ENGINE.md)

- [验证与证据规则](https://github.com/meiluosi/strandbeest-evolution/blob/main/docs/VALIDATION.md)

- [实验记录](https://github.com/meiluosi/strandbeest-evolution/blob/main/docs/EXPERIMENTS.md)

版本说明：本总览记录 2026-11-05 的研究方向与课程进度。仓库实现状态以后续检查为准。
