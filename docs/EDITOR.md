# 编辑代数与编辑器 v0（E3）

> 对应 [ADR-0003](adr/0003-edit-oplog-as-source-of-truth.md)、任务卡 E3-01…E3-04。**任何改设计的动作都是一个操作**：人、遗传算法、智能体、编辑器都不例外。

## 操作

`{id, type, args, actor{kind: human|algorithm|agent, id}, reason, time}`，定义在 [`schemas/ops.schema.json`](../schemas/ops.schema.json)（类型由它生成：`packages/common/.../models/ops.py`、`packages/core/src/generated/ops.ts`）。

| 类型 | 作用 |
|---|---|
| `set_param` | 设一个具名长度 |
| `set_length` | 按句柄设一个长度（具名长度，或写在规格里的数字：`crank.x`、`joint:ID.radii.N`） |
| `set_property` | 设设计里一个**已有**的可编辑属性（`/name`、`/notes`、`/walker/*`、`/drive/*`、`/manufacturing/*`）；类型必须和旧值一致，范围由 schema 检查 |
| `add_dyad` | 在两个圆的交点处加关节（可带新增的具名长度，可设为脚） |
| `remove_joint` | 删除没有别的关节建在其上的关节（删脚时要指定新脚） |
| `array_legs` / `scale` / `mirror` / `set_material` | 腿数 / 缩放（可保持实物尺寸）/ 左右镜像并反转曲柄 / 材料 |
| `patch` | 撤销的记录：把新设计变回旧设计的 JSON 补丁（也要过守门，不是后门） |

每个操作都有**精确的逆**：逆就是 `diff(新, 旧)` 这份 JSON 补丁，所以 `apply + undo` 恒等（属性测试里验证）。一组操作可以作为**一个撤销步**提交（拖动一个点会同时改两根杆的长度），全部成功或全部不改。

## 有效性守门

操作应用之后，守门检查新设计；**只拦新出现的错误**（已有的错误不挡路，所以坏设计可以一步步修好）。

| 检查 | 位置 | 说明 |
|---|---|---|
| `schema` | Python（jsonschema）与 TS（`schema-lite`） | 类型、范围、枚举、不许多余字段 |
| 静态结构 | `validity`（两侧） | 名字能解析、关节只用更早的点、杆长为正、脚存在 |
| `cannot_assemble` | `guard`（两侧） | 一整圈 72 个曲柄角里有解不出的 |
| `branch_flip` | `guard`（两侧） | 某点在采样间跳变：先按 16 倍细化，快但连续不算，细化后仍跳或窄窗口里不闭合才算 |
| `not_printable.*`（错误）、其余警告 | `strandbeest_fab.guard`（仅服务端） | 复用制造检查；弯杆之间的碰撞由 `plan_leg` 按扫过范围分层来避免，**不检查**腿与机架、机身、地面的间隙 |

自由度恒为 1：关节都由两个更早的点决定，结构检查拒绝破坏这一点的写法。

## 日志、撤销、持久化

`History`（TS 与 Python 各一份，由 `contracts/ops/cases.json` 约束）：日志是真相，设计是它的折叠；`undo/redo`；新提交清掉重做分支。浏览器里的日志存在 `localStorage`，刷新后重放；如果日后守门变严导致只能重放一部分，界面会提示保留了多少步。**新建文档**（打开文件、加载示例）开始一份新日志。

## 编辑器 v0（设计页）

- 拖长度滑块、拖图中的点（关节：两根杆的长度变成它到两个圆心的距离；曲柄尖：曲柄长；曲柄轴 P：x、y），松手时提交**一个撤销步**；拖动过程只是预览，不进日志。
- 改名、腿数、单位、间隙都是 `set_property`/`array_legs`。
- `⌘K`/`Ctrl+K` 命令面板：每个操作自动出现（名称、说明、参数表单来自 `ops.schema.json` 的 `x-doc`），带预填；也能撤销/重做、加载示例连杆。**用命令面板加二元组**：`加二元组` → 预填好的表单 → 应用。
- 编辑历史面板：谁、何时、做了什么、为什么；撤销/重做；下载整份操作日志（`OpLog`）。
- 遗传算法的最优解以 `algorithm` 身份、作为一个撤销步提交（E3-06 会把变异/交叉本身也做成操作）。

## 服务端

`POST /ops/apply`（设计 + 操作 → 新设计、逆、警告；被拒时 422 带问题列表）、`POST /ops/replay`（基础设计 + 日志 → 设计）、`POST /designs/guard`。智能体接口（A-01/A-02）由同一套操作定义生成。

## 已知限制

- `set_property` 只改**已有**属性，不能新增可选字段。
- 打印性和碰撞只在服务端检查；浏览器里只有 schema、结构、装配、分支翻转。
- 操作的实现在 TS 和 Python 各一份（ADR-0009 的触发线评估见该 ADR）。
- 守门的警告还没有在界面里显示。
