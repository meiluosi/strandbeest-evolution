# 来源索引与导出范围

导出日期：2026-11-06（Asia/Singapore）。来源：[Beest 空间](https://chatgpt.com/space/page_6aeca13ed9b08191baace0ffab03a6f1)。

本包包含导出时读取的 10 个页面正文：空间首页、目录、项目总览、六课与一个实施子页。每页保留原文副本和本地链接阅读副本。页面内容由 ChatGPT Space read_page 读取，不是依据聊天摘要替写的课程。

| 来源页面 | 本地阅读副本 | 原页 | 页面序列 | 来源更新时间 UTC |
|---|---|---|---|---|
| Beest Model Experiment Harness | [space_home.md](docs/space_home.md) | [来源](https://chatgpt.com/space/page_6aeca13ed9b08191baace0ffab03a6f1) | 1 | 2026-11-05T16:08:16.291633Z |
| 文档目录与研究导航 | [space_directory.md](docs/space_directory.md) | [来源](https://chatgpt.com/space/page_6aeca3efb2ac8191bd53aaf9156103c2) | 3 | 2026-11-05T17:24:02.721097Z |
| 00 项目总览与 Agent 交接上下文 | [project_overview.md](docs/project_overview.md) | [来源](https://chatgpt.com/space/page_6aeca182083c8191b4eeb85353d5dd6a) | 0 | 2026-11-05T15:32:20.873808Z |
| 01 Lesson 01 - 实验对象与数据模型 | [lesson_01_experiment_objects.md](docs/lesson_01_experiment_objects.md) | [来源](https://chatgpt.com/space/page_6aeca18f4df0819194d1c7c41a847ce7) | 0 | 2026-11-05T15:32:34.709375Z |
| 02 Lesson 02 - 实验编排与调度架构 | [lesson_02_orchestration.md](docs/lesson_02_orchestration.md) | [来源](https://chatgpt.com/space/page_6aeca1ebf67881918aca4942d04e0ee9) | 0 | 2026-11-05T15:34:07.176874Z |
| 03 Lesson 03 - Dataset 与 Model 生命周期 | [lesson_03_data_models.md](docs/lesson_03_data_models.md) | [来源](https://chatgpt.com/space/page_6aeca3d3ccec8191a6020c75d829be68) | 0 | 2026-11-05T15:42:14.419831Z |
| 04 Lesson 04 模型评测与证据体系 | [lesson_04_evaluation_evidence.md](docs/lesson_04_evaluation_evidence.md) | [来源](https://chatgpt.com/space/page_bc1e45d775408191b7328d225c816716) | 1 | 2026-11-05T16:07:23.362139Z |
| 05 Lesson 05 Research Agent 与自适应实验决策 | [lesson_05_research_agent.md](docs/lesson_05_research_agent.md) | [来源](https://chatgpt.com/space/page_50ad9569c65881919236d6d80d2ab5fd) | 1 | 2026-11-05T16:56:32.108951Z |
| 06 Lesson 06 整体系统架构与开发规格 | [lesson_06_system_architecture.md](docs/lesson_06_system_architecture.md) | [来源](https://chatgpt.com/space/page_bdeb810ef078819183a23a70d00b46a7) | 1 | 2026-11-05T17:23:42.274498Z |
| 实施交接规格 契约 接口 迁移与验收 | [implementation_handoff_spec.md](docs/implementation_handoff_spec.md) | [来源](https://chatgpt.com/space/page_89779898fc6c8191a40b24a0d0f87a90) | 0 | 2026-11-05T17:20:02.024618Z |

## 导出与派生规则

`originals/` 保存正文与原链接，统一 UTF-8/LF 和末尾换行；不是原生 CRDT、评论、权限、修订历史或二进制备份。`docs/` 加入标题与出处头，并仅将已纳入包内的空间页面链接改为本地相对链接；其余正文保留。

`ALL_IN_ONE.md` 合并全部正文并保留原始来源链接，适合单文件交接；不要求读取者能打开 Space 才能读取已经内嵌的正文。合订版无需与分篇版同时全读。

图与协议代码块直接提取；原文公式保留 math 围栏。外部论文和 GitHub 文件未下载入包，代码基线是课程历史记录而非本次 main 核查。新增导读与交接提示是导航材料，不改写来源页，也不使建议成为已验收实现。

没有单独导出的逐字聊天。已有上下文与决策摘要包含在项目总览、各课交接节和本包导读中。没有提供新增训练数据、模型权重或实际测试输出。
