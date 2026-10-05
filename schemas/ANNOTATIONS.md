# 属性注解规范（`x-` 扩展）

> 来源：ADR-0007。**属性系统 = JSON Schema + 这些注解**。同一份声明生成：编辑表单、API 校验、MCP 工具 schema、参考文档、缓存失效规则。
> 校验器：`scripts/check_schema_annotations.py`（默认只告警，`--strict` 时有缺失即失败）。

| 键 | 类型 | 必须吗 | 含义 |
|---|---|---|---|
| `x-unit` | string | **每个数值字段必须有** | 物理单位：`m`、`mm`、`kg`、`s`、`rad`、`rad/s`、`N`、`N·m`、`1/s²`（接触刚度）、`m/s`、`kg/m³`、`m²`、`1`（无量纲）、`count`（计数）、`unit_m`（连杆长度单位，换算见 `walker.unit_m`） |
| `x-range` | `[min, max]` | 建议 | 界面滑块/校验的合理范围（硬约束仍用 `minimum`/`maximum`） |
| `x-group` | string | 建议 | 界面里的分组名（消息键，如 `group.walker`） |
| `x-doc` | `{zh, en}` | 建议 | 一句话说明，中英文；也进参考文档 |
| `x-assumption` | bool | 猜测的参数必须为 `true` | 这个值是**假设**，不是测量或推导 |
| `x-source` | string | `x-assumption` 为真时必须有 | 假设的出处或理由（"N20 类电机堵转扭矩的量级"、"文献/数据表"、"我们的猜测，待测量"） |
| `x-calibratable` | bool | 可被校准的参数为 `true` | 校准工具可以拟合它 |
| `x-affects` | string[] | 建议 | 改它会使哪些派生数据失效：`sim`（仿真结果）、`fab`（制造导出）、`eval`（步态评估）、`view`（只影响显示） |
| `x-i18n` | string | 可选 | 字段标签的消息键，默认 `field.<路径>` |

## 规则
1. **数值字段没有 `x-unit` 就是缺陷**。`const`/`enum` 的数值不算。
2. `x-assumption: true` 的字段必须同时有 `x-source`。
3. `x-affects` 缺省按 `["sim", "fab", "eval"]` 处理（保守：任何改动都使缓存失效）。
4. 注解只描述，不改变校验语义；校验语义用标准关键字。

## 例
```json
"foot_friction": {
  "type": "number", "exclusiveMinimum": 0,
  "x-unit": "1", "x-range": [0.2, 3.0], "x-group": "group.contact",
  "x-assumption": true, "x-source": "光滑 PLA 对玻璃的摩擦系数量级，待测量",
  "x-calibratable": true, "x-affects": ["sim"],
  "x-doc": {"zh": "脚与地面的摩擦系数", "en": "Foot-ground friction coefficient"}
}
```
