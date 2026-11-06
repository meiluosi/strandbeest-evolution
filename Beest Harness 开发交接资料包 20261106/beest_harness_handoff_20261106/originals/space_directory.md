# Beest Model Experiment Harness：文档目录

## 项目定位

面向物理世界模型与具身智能研究的实验编排、模型训练、仿真验证和证据管理平台。以 strandbeest-evolution 为基础，保留风力兽设计、演化、仿真、制造与真实测量特色，补齐模型实验 Harness。

## 已确认架构原则

1. 研究问题优先于工具。

2. 实验结果可追溯、可复现。

3. AI 加速研究，人类把关证据。

## 六层架构

L1 Domain Engine；L2 Worker & Runtime；L3 Execution & Scheduling；L4 Model & Data Management；L5 Evaluation & Evidence；L6 Research Agent。

## 研究文档

- [项目总览与 Agent 交接上下文](https://chatgpt.com/space/page_6aeca182083c8191b4eeb85353d5dd6a)

- [Lesson 01：实验对象与数据模型](https://chatgpt.com/space/page_6aeca18f4df0819194d1c7c41a847ce7)

- [Lesson 02：实验编排与调度架构](https://chatgpt.com/space/page_6aeca1ebf67881918aca4942d04e0ee9)

- [Lesson 03：Dataset 与 Model 生命周期](https://chatgpt.com/space/page_6aeca3d3ccec8191a6020c75d829be68)

- [Lesson 04：模型评测与证据体系](https://chatgpt.com/space/page_bc1e45d775408191b7328d225c816716)

- [Lesson 05：Research Agent 与自适应实验决策](https://chatgpt.com/space/page_50ad9569c65881919236d6d80d2ab5fd)

- [Lesson 06：整体系统架构与开发规格](https://chatgpt.com/space/page_bdeb810ef078819183a23a70d00b46a7)

- [实施交接规格：契约、接口、迁移与验收](https://chatgpt.com/space/page_89779898fc6c8191a40b24a0d0f87a90)

首轮课程 01–06 的规划文档已归档。前五课分别定义实验对象、执行调度、数据与模型、评测证据及 Research Agent；第六课整合模块、进程、事务、迁移与界面设计，并配套 12 项不变条件、8 个工作包和 20 项故障与端到端验收。各课保留来源与交接要点；课程完成不代表六层系统已实现或科学实验已通过。

## 下一阶段实施

在用户授权的工作副本中，先完成 M0 基线与契约核对，再推进 M1 手动端到端实验：现有轨迹 → 冻结数据 → 小模型训练 → 评测与回放 → 有来源的限定结论。后续依次加固恢复与预算、接入受控研究循环。详细任务及依赖以实施交接规格为准；本轮只保存规划，未修改仓库或执行训练。

## 贯穿案例

从现有 SimulationRun 生成风力兽动力学数据，构建 Dataset Snapshot，训练 MLP/GRU 等学习模型，评测一步预测、长期 Rollout、跨设计/风场泛化和物理一致性。仿真器拟合不等于真实世界验证；真实验证必须依赖独立实测证据。

## Agent 交接要求

接手者先阅读项目总览和对应课程，再检查 GitHub 当前 main 分支。文档中的目标架构不代表代码已实现。未经用户明确授权，不修改仓库。所有实施均应有 Schema、迁移、契约测试、回归与证据记录。
