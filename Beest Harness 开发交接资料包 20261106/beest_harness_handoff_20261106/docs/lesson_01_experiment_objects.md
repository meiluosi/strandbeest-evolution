# 01 Lesson 01 - 实验对象与数据模型

> 来源：[ChatGPT Space 原页](https://chatgpt.com/space/page_6aeca18f4df0819194d1c7c41a847ce7) · 页面序列 0 · 导出日期 2026-11-06（Asia/Singapore）
> 本文件为阅读副本：正文保留，已知空间内链接改为本地文件。原始正文见 [originals](../originals/lesson_01_experiment_objects.md)。

---

# Lesson 01：实验对象与数据模型

## 1. 课程目标

建立统一的实验对象模型，区分研究协议、实验条件、独立试验、计算任务、执行记录和产物，为六层 Model Experiment Harness 提供数据基础。

## 2. 核心对象

| 对象 | 定义 | 主要职责 |
|---|---|---|
| Experiment | 一个完整的研究实验及其版本化协议 | 问题、假设、目标、变量、预算、验收条件 |
| Condition | 一组明确的实验条件 | 模型、数据、训练配置、环境参数 |
| Trial | 某个 Condition 下的一次独立实验重复 | 随机种子、重复编号、实验结果 |
| Job | 一个可调度的计算任务 | 输入、依赖、资源、执行状态 |
| Job Attempt | Job 的一次实际执行尝试 | 日志、错误、重试、恢复 |
| Run | 一次有明确领域语义的执行记录 | 仿真、训练、评测、数据处理等 |
| Artifact | 执行过程中产生的文件或数据产物 | 权重、数据集、日志、报告、遥测 |

## 3. 对象关系

Experiment → Condition → Trial → Job → Job Attempt → Typed Run → Artifact。

关系允许一对多：Experiment 包含多个 Condition；Condition 包含多个 Trial；Trial 包含多个 Job；Job 可以有多次 Attempt；Job 可以产生多个 Run 和 Artifact。

## 4. Run 的类型设计

保留现有 SimulationRun，不改变 schemas/run.schema.json 的领域语义。

建议新增 TrainingRun、EvaluationRun、DataProcessingRun、CalibrationRun。各类型共享基础执行身份、输入引用、状态和来源信息，但保留独立领域 Schema。

## 5. 生命周期

Experiment：draft → approved → running → analyzing → completed / archived。

Trial：planned → ready → running → evaluating → completed / failed / cancelled。

Job：queued → running → succeeded / failed / cancelled / blocked。

Job Attempt：started → succeeded / failed / interrupted / cancelled。

不同层次的状态不得直接互相替代。

## 6. 关键设计约束

1. Job 成功不代表 Trial 成功。

2. Trial 成功不代表科学假设成立。

3. Job 重试不等于新的独立 Trial。

4. 领域 Run 必须保留独立 Schema。

5. Artifact 必须具备稳定身份、内容哈希和来源关系。

6. 所有实验结果必须能够追溯到数据、模型、配置、代码和执行环境。

## 7. 现有项目映射

保留 Design、Scenario、SimulationRun、Measurement、Profile、packages/common/dag.py、apps/api JobStore、证据等级 E0–E3、输入哈希与实现身份。

新增 Experiment、Condition、Trial、Job Attempt、TrainingRun、EvaluationRun 和统一 Artifact 元数据协议。

## 8. 待进一步设计

- Experiment 与 Trial 的版本化及不可变性。

- Job DAG 的持久化与恢复。

- 多个 Trial 共享 Dataset Snapshot 的机制。

- Checkpoint 与训练恢复协议。

- 跨类型 Run 的来源图。

- 统计分析与研究结论之间的证据约束。

## 9. 验收标准

- 描述完整的多模型、多随机种子实验。

- 区分 Experiment、Condition、Trial 和 Job。

- 表示 Job 重试而不产生虚假的实验重复。

- 表示一次 Job 产生多个不同类型的执行产物。

- 保留 SimulationRun 兼容性。

- 从最终报告回溯到原始数据与执行记录。

## 10. 课程结论

Experiment 是研究协议，Condition 是比较条件，Trial 是独立重复，Job 是调度单元，Attempt 是执行尝试，Run 是领域执行记录，Artifact 是产物。不得把它们压成一个万能 Run。
