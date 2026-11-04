# 架构决定记录（ADR）

每条记录一个**难以回头**的决定：背景、选项、推荐、后果、验证方法。状态：**提议** → **接受** / **否决** / **被取代**。0001–0008 已于 2026-10-06 按推荐方案接受（资产用稳定 ID、现在做 i18n、属性注解放进 JSON Schema、引擎沿用名字 Beest Engine）。
状态改变要在本表里更新，并在对应文件里写明日期和理由。总览见 [../ENGINE.md](../ENGINE.md)。

“接受”表示设计决定获接受，不表示其每项能力已实现或得到实测验证。2026-11-04 的实际执行路径、各 H 卡证据和缺口见 [当前架构](../ARCHITECTURE.md)；历史决策正文保留，后续实施记录优先描述现状。

| 编号 | 决定 | 对应单向门 | 状态 |
|---|---|---|---|
| [0001](0001-asset-identity-and-references.md) | 资产身份与引用 | 单向门 #1 | 接受 |
| [0002](0002-units-and-coordinate-conventions.md) | 单位、坐标系与符号约定 | 单向门 #2 | 接受 |
| [0003](0003-edit-operations-as-source-of-truth.md) | 编辑操作日志作为设计的真相来源 | 单向门 #3 | 接受 |
| [0004](0004-determinism-snapshots-provenance-cache.md) | 确定性、状态快照、出处与缓存 | 单向门 #4、#10、#14 | 接受 |
| [0005](0005-world-entity-model-and-physics-backend.md) | 世界/实体模型与物理后端边界 | 单向门 #5、#6 | 接受 |
| [0006](0006-telemetry-and-geometry-formats.md) | 遥测与几何的数据格式 | 单向门 #7 | 接受 |
| [0007](0007-property-system-and-plugin-api.md) | 属性系统与扩展 API | 单向门 #8、#9 | 接受 |
| [0008](0008-project-format-and-i18n.md) | 项目文件格式与国际化 | 单向门 #11、#12 | 接受 |
| [0009](0009-single-source-of-kinematics.md) | 运动学的唯一真相来源（双实现、Rust/WASM 内核、Pyodide…） | #13 | 接受；Rust Python/WASM 已接入，TS/reference 保留核对 |
| [0010](0010-k2-independent-solver.md) | K2 独立平面刚体物理求解器设计 | V-02、单向门 #5 | 接受 |
| [0011](0011-licensing-for-code-designs-and-data.md) | 代码、设计库与实测数据的三类许可证方案 | R-06 | 接受 |
| [0012](0012-stride-audit-applicability.md) | 步幅审计的参考模型与适用条件 | H2-01 | 接受；用户批准，实施不等于验收 |

## 模板
```
# ADR-NNNN: 标题
状态：提议 | 接受 | 否决 | 被取代（日期、理由）
背景 / 选项 / 推荐 / 后果与迁移 / 验证
```
