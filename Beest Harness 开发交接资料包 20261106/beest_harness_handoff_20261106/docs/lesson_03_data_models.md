# 03 Lesson 03 - Dataset 与 Model 生命周期

> 来源：[ChatGPT Space 原页](https://chatgpt.com/space/page_6aeca3d3ccec8191a6020c75d829be68) · 页面序列 0 · 导出日期 2026-11-06（Asia/Singapore）
> 本文件为阅读副本：正文保留，已知空间内链接改为本地文件。原始正文见 [originals](../originals/lesson_03_data_models.md)。

---

# Lesson 03：Dataset 与 Model 生命周期

> Beest Model Experiment Harness · Architecture Research · 2026-11-05  
> 前置课程：[Lesson 01：实验对象与数据模型](lesson_01_experiment_objects.md) · [Lesson 02：实验编排与调度架构](lesson_02_orchestration.md)

## 1. 本课目标

设计从原始数据到可训练 Dataset、从模型定义到可追溯 Checkpoint 的完整生命周期。

核心问题：

1. Raw Data、Measurement、Dataset、Dataset Version、Dataset Snapshot 有什么区别？

2. 数据清洗、特征构造、切窗、切分怎样形成可追溯的数据血缘？

3. 怎样避免时间序列、仿真场景和实体之间的数据泄漏？

4. Model Spec、Model Version、Training Run、Checkpoint、Release Model 如何区分？

5. 如何把数据、模型、训练代码、配置、权重和评测结果绑定？

6. 怎样兼容本地文件系统、对象存储和未来的大规模数据？

本课是目标架构设计，不代表所有能力已在仓库实现。

## 2. 核心判断：数据集不是一个文件，模型也不只是一个权重文件

一个 Parquet 文件可能只是某次导出的数据产物，不足以说明数据来源、处理代码、排除规则、切分方法、特征标签对齐、合成数据比例和版本身份。

同样，一个 .pt 文件也不足以说明模型结构、训练配置、数据版本、随机种子、训练过程和评测结论。

因此要把“内容文件”和“描述它的不可变资产元数据”分开管理。

## 3. 数据生命周期：从原始记录到 Dataset Snapshot

建议区分以下对象：

| 对象 | 定义 | 是否可变 |
|---|---|---|
| Raw Data | 原始视频、传感器记录、CSV、原始仿真遥测 | 原始内容不可覆盖 |
| Source Record | 数据来源、许可、采集条件、设备和出处 | 修订产生新版本 |
| Measurement / SimulationRun | 领域层的测量或仿真事实记录 | 已提交记录不可静默改写 |
| Processing Spec | 清洗、同步、筛选、特征构造、切窗的声明式配置 | 版本化 |
| Processing Run | 一次数据处理执行及日志、质量报告 | 不可变执行记录 |
| Dataset | 有稳定身份的数据集逻辑对象 | 可发布新版本 |
| Dataset Version | 一次数据集内容与处理定义的版本 | 不可变 |
| Dataset Snapshot | 供某次 Experiment 使用的精确数据内容、切分与清单 | 不可变 |

### 3.1 推荐数据血缘

    Raw Sources
       |
       v
    Ingestion + Source Validation
       |
       v
    Canonical Records
       |
       v
    Processing Spec (versioned)
       |
       v
    Processing Run
       |
       +---- quality report
       |
       v
    Dataset Version
       |
       v
    Dataset Snapshot
       |
       +---- train split
       +---- validation split
       +---- test split
       |
       v
    Experiment / Trial

数据处理不应覆盖 Raw Data。每一步生成新的派生产物，并保留输入引用、处理代码身份、参数、输出哈希和质量报告。

### 3.2 Dataset Version 与 Snapshot 的区别

Dataset Version 表示一个发布的数据集版本，例如 beest-dynamics-v3。

Dataset Snapshot 是某个 Experiment 实际使用的冻结视图，至少固定：

- Dataset Version；

- 样本清单或分片清单；

- split membership；

- 标签与特征定义；

- 预处理参数；

- 过滤规则；

- 数据来源；

- 内容哈希。

同一 Dataset Version 可以产生不同 Snapshot，例如不同的 train/validation/test 切分。已经用于实验的 Snapshot 不得原地修改。

## 4. Beest 场景的数据组织

本项目有两类重要数据来源：

### 4.1 仿真数据

来源包括现有 SimulationRun、Scenario、Design、后端身份、种子、实现哈希和遥测。

每段轨迹必须能够回答：

- 来自哪个 Design 与 Scenario？

- 使用 MuJoCo 还是 K2？具体版本与实现身份是什么？

- 时间步长、求解器参数、驱动与风场是什么？

- 随机种子是什么？

- 是否完成了适用的数值审计？

- 哪些指标是模型内计算，哪些经过独立核对？

仿真数据应明确标记为 synthetic/simulated，并携带仿真器身份。不同后端产生的数据不能在不记录来源的情况下混成一个无差别数据集。

### 4.2 真实测量数据

来源包括 Measurement、packages/rig 原始采集转换结果、视频追踪、设备标定与人工记录。

必须保留：

- 原始文件和内容哈希；

- 仪器、设备与固件身份；

- 采样频率、单位、时钟同步与校准；

- 测量条件；

- 数据质量警告；

- 许可与使用约束；

- synthetic=false 的来源证据。

现有 Measurement Schema 已包含 synthetic、conditions、channels、provenance、quality 等字段，应作为真实测量接入的领域基础，而不是另造一套重复格式。

### 4.3 仿真与实测的关系

建议 Dataset Snapshot 明确数据来源分层：

- simulated；

- measured；

- literature/public；

- derived/mixed（混合数据必须保留逐样本来源）。

可以训练混合数据模型，但必须能够单独评测仿真域和真实域。模型在模拟器数据上的表现不能自动升级为真实世界证据。

## 5. 时间序列数据切分：防止泄漏

风力兽动力学数据是时间序列，随机按窗口切分非常容易产生泄漏。

例如，同一条 10,000 帧轨迹切成大量重叠窗口，如果随机分到 train 和 test，测试窗口可能与训练窗口共享绝大部分时间点。此时测试误差会过于乐观。

### 5.1 推荐分组单位

依据泛化目标选择 Group：

- 同一条采集/仿真轨迹；

- 同一个随机种子；

- 同一个 Design；

- 同一个 Scenario；

- 同一实体或硬件实例；

- 同一实验批次或采集日期。

### 5.2 不同评测问题对应不同切分

| 想回答的问题 | 推荐切分 |
|---|---|
| 同分布预测能力 | 按完整轨迹或 episode 分组 |
| 新随机条件泛化 | 按随机种子或场景实例留出 |
| 新风场泛化 | 按风场类型/参数区域留出 |
| 新地形泛化 | 按地形类别或参数区域留出 |
| 新设计迁移 | 按 Design ID 留出 |
| 真实世界迁移 | 真实测量独立留出，且不参与调参 |
| 时间外推 | 按采集时间或实验批次留出 |

应同时记录 split strategy、group key、seed、时间边界和样本清单哈希。

### 5.3 预处理防泄漏

- 归一化均值/方差只在训练集拟合，再应用到验证与测试集。

- 特征选择、降维、缺失值填补等有拟合参数的处理，只能从训练集学习。

- 不得用测试集选择模型、超参数或停止轮数。

- 由未来状态计算的标签不能泄漏进当前时刻输入。

- 时间窗口必须检查输入区间与目标区间边界。

- 若同一轨迹存在重叠窗口，应先按轨迹分组再切分，而不是先切窗口再随机拆分。

- 测试集评估协议冻结，测试结果不作为 Research Agent 自动调参的反馈数据。

## 6. 数据样本契约：以风力兽动力学预测为例

建议先定义一个清晰的时序样本契约，而不是过早固定某一种存储格式。

一个监督样本可以抽象为：

    input:
      state[t - context : t]
      environment[t - context : t]
      design_parameters
      drive_or_external_conditions

    target:
      state[t + horizon]
      optional: trajectory[t + 1 : t + horizon]

候选状态字段：

- 机身位置、姿态、线速度和角速度；

- 曲柄角度与角速度；

- 足端位置、速度、接触状态；

- 关节或连杆状态（根据模型可观测性选择）；

- 风速、风向、湍流条件；

- 地形、摩擦和环境参数；

- 设计几何、质量与物理参数。

注意：

1. 不应把所有可用字段都默认塞进输入；要根据研究问题定义可观测量。

2. 如果真实传感器无法观测某个仿真内部状态，应区分 privileged state 与 deployable observation。

3. 单位、坐标系、时间基准、缺失值语义必须进入 Schema。

4. 预测目标必须明确是状态、增量、轨迹、分布还是潜变量。

5. 数据集应保留 episode/trajectory ID，使分组切分可执行。

## 7. Model 生命周期：从模型定义到可发布模型

建议区分：

| 对象 | 定义 | 示例 |
|---|---|---|
| Model Spec | 模型结构和输入输出契约 | GRU，输入状态序列，输出未来状态 |
| Model Version | 一个不可变模型定义版本 | gru-dynamics-v2 |
| Training Config | 优化器、学习率、batch、训练轮数等 | AdamW、lr=1e-3 |
| Training Run | 一次实际训练执行 | seed=42 的训练记录 |
| Checkpoint | 某个训练时刻的完整或部分状态快照 | step=20,000 |
| Model Artifact | 可加载推理的权重与配置包 | weights + config + manifest |
| Evaluation Record | 模型在指定评测协议上的结果 | rollout-v1 / test-snapshot |
| Model Release | 经过审核、可供下游使用的模型版本 | approved candidate |

Model Spec 与 Training Config 必须分开：前者描述“模型是什么”，后者描述“怎样训练它”。

### 7.1 Checkpoint 不等于 Release Model

Checkpoint 是训练过程中的恢复点或候选权重。它可能不完整、未评测、性能不稳定。

Release Model 是经过产物完整性检查、加载与推理测试、指定 Evaluation Suite、必要的泛化与安全评测，以及人工或策略审核之后批准给下游使用的版本。

不能因为训练完成就自动发布模型。

### 7.2 Model Manifest

每个模型制品建议有独立 manifest，记录：

- model_id / model_version；

- architecture / framework；

- input-output schema；

- weights artifact URI 与 hash；

- Model Spec 与 Training Config 引用；

- Training Run 与 Dataset Snapshot 引用；

- source code / dependency / runtime identity；

- normalization / tokenizer / feature transform 等前后处理资产；

- license / usage constraints；

- compatible evaluator versions；

- creation time 与 approval status。

对动力学模型而言，归一化参数和特征顺序属于模型语义的一部分，不能只保存权重。

## 8. Artifact Storage：元数据与大文件分离

### 8.1 Metadata Store

存储 Dataset、Model、Run、Checkpoint 元数据、版本和状态、输入输出引用、Provenance 边、哈希、索引和检索字段。

首版可沿用 SQLite，未来按并发和查询需求迁移关系数据库。

### 8.2 Artifact Store

存储原始视频与传感器文件、Parquet/Arrow 遥测、数据分片、Checkpoint 和模型权重、评测预测结果、图表、报告与回放文件。

建议定义 Storage Adapter：

- 本地文件系统先实现；

- 未来可支持 S3 兼容对象存储；

- 大型数据文件按内容哈希或不可变对象键保存；

- 元数据只保存 URI、大小、格式、哈希和校验状态。

不要把模型权重或大型数组直接存进 SQLite。也不要将易变的临时工作目录当成永久 Artifact URI。

## 9. 数据与模型的血缘关系

建议所有数据和模型产物形成有向来源图：

    Raw Measurement / SimulationRun
                |
                v
        Processing Run
                |
                v
        Dataset Version
                |
                v
        Dataset Snapshot
                |
                v
          Training Run
                |
                v
           Checkpoint
                |
                v
          Model Artifact
                |
                v
        Evaluation Record
                |
                v
          Model Release

血缘边需要说明关系类型，例如：

- derived_from

- processed_by

- split_from

- trained_on

- checkpoint_of

- exported_as

- evaluated_with

- approved_as

“文件存在”不等于“来源可信”。每条边必须引用真实存在的父对象，并且保留创建它的处理或执行记录。

## 10. 数据与模型版本策略

- 原始数据不可覆盖；更正通过新 Source Record 或新版本表达。

- Processing Spec 变化产生新的 Processing Run。

- Dataset Snapshot 内容不可变。

- split 规则变化产生新 Snapshot。

- Model Spec 变化产生新 Model Version。

- Training Config 变化必须能被独立识别。

- Checkpoint 不可覆盖已登记版本。

- 模型导出必须保留前后处理配置和来源。

- 历史实验始终引用当时的 Dataset Snapshot 与 Model Version，不得自动指向最新版本。

内容哈希用于确认内容身份；版本号用于表达有意义的语义变更。两者不能互相替代。

## 11. 现有仓库映射与主要缺口

已有基础：

- schemas/measurement.schema.json：真实/合成标记、条件、通道、出处与质量。

- schemas/run.schema.json：SimulationRun、遥测引用、输入身份与证据。

- schemas/profile.schema.json：校准参数、Measurement 来源、不确定度和映射版本。

- packages/rig：原始采集转换、质量报告和视频追踪。

- packages/calib：测量比较、参数拟合与校准档案。

- packages/common/hashing.py、implementation.py：哈希和实现身份。

- packages/common/dag.py：数据处理可使用的执行依赖基础。

- apps/api：文件资产和来源关系索引基础。

主要缺口：

1. Dataset / Dataset Version / Dataset Snapshot 的正式 Schema。

2. Processing Spec 与 Processing Run。

3. split manifest 和防泄漏检查。

4. Model Spec / Model Version / Training Config。

5. TrainingRun 与 Checkpoint Schema。

6. Model Manifest 和 Model Registry。

7. Artifact Storage Adapter 与生命周期策略。

8. Dataset/Model/Checkpoint/Evaluation 的统一 Lineage。

9. 对真实、仿真、公开和混合数据的逐样本来源标注。

## 12. 推荐的首版范围

首版不要做通用数据湖或大规模分布式存储。建议先跑通：

1. 从现有 SimulationRun 导出带来源的时序数据。

2. 构建 Dataset Version 与不可变 Snapshot。

3. 按 trajectory / Design / Scenario 做分组切分。

4. 用训练集拟合归一化参数。

5. 注册 MLP 或 GRU Model Spec。

6. Training Worker 产出 TrainingRun 和 Checkpoint。

7. 导出包含权重与前后处理配置的 Model Artifact。

8. Evaluation Worker 读取冻结 Snapshot 和 Model Artifact。

9. 从 Evaluation Record 反向追溯到数据、仿真和代码身份。

该流程首先验证平台的数据与模型资产链路，不以训练出高性能模型为第一目标。

## 13. 本课验收标准

- 原始数据不可覆盖，处理结果可追溯。

- Dataset Snapshot 固定内容、切分和处理身份。

- 能按轨迹、设计或场景分组切分，避免重叠窗口泄漏。

- 归一化等拟合变换只从训练集学习。

- 能区分 Model Spec、Model Version、Training Config、Training Run、Checkpoint 和 Release Model。

- Checkpoint 与 Dataset Snapshot、代码、配置和训练状态关联。

- Model Artifact 包含推理所需前后处理配置。

- 数据与模型文件通过 Artifact Store 管理，元数据与大文件分离。

- Evaluation Record 可追溯到确切模型与 Dataset Snapshot。

- 仿真数据与真实测量数据保持来源区分。

## 14. 待决策问题

1. Dataset Schema 是否采用 manifest + 分片文件，而非单一大文件？建议 manifest + Parquet/Arrow shards。

2. Dataset Snapshot 是否必须物化所有数据？建议支持 materialized snapshot 与 immutable manifest snapshot；两者都必须内容可核验。

3. 首版数据格式是否统一为 Parquet？建议时间序列优先 Parquet/Arrow，视频和大二进制单独存储。

4. 模型权重是否放在 Artifact Store？是；数据库仅存引用与元数据。

5. 首版是否支持外部 MLflow？先定义内部接口，后续通过 Adapter 评估集成，不把 MLflow 设为核心领域模型。

6. 真实与仿真数据是否允许混训？允许，但必须逐样本保留来源，并分别报告评测结果。

## 15. 本课结论

Dataset 是经过定义和管理的数据资产；Dataset Version 表示数据集发布版本；Snapshot 冻结某次实验使用的精确内容与切分。Model Spec 定义模型结构与 I/O，Training Config 定义训练方法，Training Run 记录一次训练，Checkpoint 保存训练状态，Model Release 表示经过审核的可用模型。所有数据、权重和评测结果都必须通过不可变引用与 Provenance 连接。
