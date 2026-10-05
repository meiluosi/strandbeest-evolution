# 架构决定记录（ADR）

每条记录一个**难以回头**的决定：背景、选项、推荐、后果、验证方法。状态：**提议** → **接受** / **否决** / **被取代**。
状态改变要在本表里更新，并在对应文件里写明日期和理由。总览见 [../ENGINE.md](../ENGINE.md)。

| 编号 | 决定 | 对应单向门 | 状态 |
|---|---|---|---|
| [0001](0001-asset-identity-and-references.md) | 资产身份与引用 | 单向门 #1 | 提议 |
| [0002](0002-units-and-coordinate-conventions.md) | 单位、坐标系与符号约定 | 单向门 #2 | 提议 |
| [0003](0003-edit-operations-as-source-of-truth.md) | 编辑操作日志作为设计的真相来源 | 单向门 #3 | 提议 |
| [0004](0004-determinism-snapshots-provenance-cache.md) | 确定性、状态快照、出处与缓存 | 单向门 #4、#10、#14 | 提议 |
| [0005](0005-world-entity-model-and-physics-backend.md) | 世界/实体模型与物理后端边界 | 单向门 #5、#6 | 提议 |
| [0006](0006-telemetry-and-geometry-formats.md) | 遥测与几何的数据格式 | 单向门 #7 | 提议 |
| [0007](0007-property-system-and-plugin-api.md) | 属性系统与扩展 API | 单向门 #8、#9 | 提议 |
| [0008](0008-project-format-and-i18n.md) | 项目文件格式与国际化 | 单向门 #11、#12 | 提议 |
| 0009 | 运动学的唯一真相来源（双实现、Rust/WASM 内核、Pyodide…） | #13 | **待写**（先保持双实现；触发线见 ENGINE.md §4.10） |

## 模板
```
# ADR-NNNN: 标题
状态：提议 | 接受 | 否决 | 被取代（日期、理由）
背景 / 选项 / 推荐 / 后果与迁移 / 验证
```
