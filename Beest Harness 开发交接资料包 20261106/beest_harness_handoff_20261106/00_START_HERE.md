# Beest 模型实验 Harness 开发交接包

**先读本页，再读第六课和实施交接规格。不要把规划中的功能当作已完成代码。**

导出日期：2026-11-06（Asia/Singapore）。范围仅为 Beest Model Experiment Harness 空间；不包含另一条软件研发 Harness 项目。

## 最短阅读路径

1. [开发 Agent 交接提示](01_AGENT_HANDOFF.md)：本轮目标、工作边界和应交付内容。
2. [上下文与重要设计修订](02_CONTEXT_AND_DECISIONS.md)：避免按前期简化表述实施。
3. [第六课整体架构](docs/lesson_06_system_architecture.md) 与 [实施交接规格](docs/implementation_handoff_spec.md)：当前整合方案、接口、迁移、工作包与验收。
4. 按任务回查 [第一课](docs/lesson_01_experiment_objects.md)、[第二课](docs/lesson_02_orchestration.md)、[第三课](docs/lesson_03_data_models.md)、[第四课](docs/lesson_04_evaluation_evidence.md)、[第五课](docs/lesson_05_research_agent.md)。

阅读完整课程可按 01–06 顺序；开发启动优先读 06 和实施规格。原文的“下一课”“本轮未执行”等保留其写作时语境，不代表当前包缺课。

## 当前目标

在现有 `meiluosi/strandbeest-evolution` 上增量改造，保留风力兽设计、演化、仿真、制造、测量和可视化。首个开发阶段是 M0 基线核对与 M1 手动贯通：

```text
有来源的轨迹 → 冻结数据及分组切分 → 小模型与简单基线
    → 模型制品 → 一步和自由滚动评测 → 原有回放叠加预测
    → 可追溯、有限定范围的结论
```

M1 不依赖 LLM；之后再完成 M2 可靠性、M3 受控研究循环和 M4 发布候选。模型没有优于基线也可以形成有效实验结果。

## 包内文件

| 位置 | 用途 |
|---|---|
| `originals/` | 10 个来源页面的 Markdown 正文快照，保留原外部链接 |
| `docs/` | 对应的本地互链阅读副本，附原页与序列信息 |
| `ALL_IN_ONE.md` | 全部页面正文的单文件合订版，适合只接收一个文件的 Agent |
| `diagrams/` | 原文中提取的 Mermaid 源码，不是新增架构 |
| `templates/` | 原文 YAML 草案，不是已实现 API 的可运行配置 |
| `quick_reference/` | 12 项不变条件、8 个工作包、20 项验收的原文摘取 |
| `SOURCE_INDEX.md` | 页面标题、来源链接、文件映射与导出范围 |
| `metadata/` | 来源清单、摘要与包级完整性检查结果 |
| `SHA256SUMS`、`verify_package.py` | 文件传输完整性校验 |

## 范围与状态

本包是架构与开发规划资料，不是可运行的项目发行包。不含 GitHub 源码副本、训练数据、模型权重、依赖安装包或实际验收产物。源码需读取用户授权的项目工作副本。

会话上下文以项目总览和各课交接摘要保留；不包含逐字聊天、页面评论、修订历史和权限配置。Markdown 中的数学与 Mermaid 源码已保留，视觉渲染取决于阅读工具。外部论文、框架文档和 GitHub 链接保留为出处，本轮未重新验证这些外部来源。

历史代码基线为 `610dafc4f00de6e70b2807c07f3932f639c28a37`，来自第六课核查；本次打包没有重新核实当前 main，也没有执行仓库测试或改动源码。

包内新增的交接说明是对现有规划的导航与整理，不扩展开发 Agent 的工具权限。实际工作路径、付费预算、发布或实体设备权限，以用户给接手 Agent 的授权为准。

## 校验

解压后在包目录运行 `python3 verify_package.py`。脚本只核对文件摘要和相对链接，不联网、不安装依赖、不训练模型。摘要用于检查传输完整性，不是作者签名或科学结果认证。
