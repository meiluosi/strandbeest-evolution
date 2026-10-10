# 给智能体用的工具面与 MCP 服务器（A-01、A-02）

> 智能体是一等用户：它们通过**和人、遗传算法同一套**操作改设计（[EDITOR.md](EDITOR.md)），用同一个仿真器，读同一批"玻璃盒"数据。

## 启动

```bash
strandbeest-mcp --workspace ./agent-workspace --actor my-agent            # 只读+写设计+耗预算（默认）
strandbeest-mcp --workspace ./ws --allow read --actor reviewer             # 只读
strandbeest-mcp --workspace ./ws --allow read,write,budget,confirm --confirm  # 人已确认：允许导出制造文件
```
stdio 上的 JSON-RPC 2.0（MCP `2024-11-05`：`initialize`、`ping`、`tools/list`、`tools/call`）。用官方 MCP Python SDK 的客户端实测过握手、列工具、调用、错误返回；**没有**和任何具体的 agent 产品（Claude Desktop 等）联调过。

## 工具

| 组 | 工具 | 级别 |
|---|---|---|
| design | `list` `get` `history` `guard` `describe_ops` | read |
| design | `create`（从示例或文档，生成新资产，来源记为 parent）`undo` `redo` | write |
| design | **`set_param` `set_length` `set_property` `add_dyad` `remove_joint` `array_legs` `scale` `mirror` `set_material`** —— **由操作定义和 `ops.schema.json` 自动生成**，新增操作自动多一个工具 | write |
| simulate | `run`（场景：flat/slope/step/bumps/wind/gusts/mars/titan/venus/moon）| **budget** |
| simulate | `list_runs` `get_run` `query`（层：summary、diagnosis、events、energy、feet、series）| read |
| lab | `list_measurements` `compare` | read |
| notes | `add` | write |
| notes | `list` | read |
| fab | `export`（写出 STL、物料清单、装配说明）| **confirm** |

级别：`read` 无副作用；`write` 改设计或笔记；`budget` 消耗会话预算（运行次数、计算秒数）；`confirm` 需要会话被人确认过。越权返回 `permission_denied` / `needs_confirmation`，超预算返回 `budget_exceeded`，操作被守门拒绝返回 `rejected_by_guard`（附问题列表），都是 `isError` 结果，带稳定的 `code`。

## 日志

- 每个修改带**执行者**（`agent` + 你给的 `--actor`）和 `reason`，写入设计的操作日志 `oplogs/<id>.json`。
- 每次调用（含被拒绝的）追加到 `audit.jsonl`：时间、执行者、工具、参数摘要、结果、耗时。
- 实验笔记在 `notes.jsonl`，可关联设计和运行。

## 限制

- 预算按会话计，进程重启后重新计数。
- 一个工作区同时只应有一个服务器进程（文件日志没有并发保护）。
- 解释文字（诊断的措辞）目前是规则给的英文句子加证据数字；让模型改写措辞是之后的事。
