# ADR-0011: 代码、设计库与实测数据的三类许可证方案

- **状态**：接受（2026-10-28）
- **对应任务卡**：R-06（关联 V-06、R-05、R-01）

## 背景

仓库包含三类性质截然不同的资产：
1. **代码**（`packages/*`、`apps/*`、`scripts/*`）：软件库与工具链。
2. **设计**（`schemas/examples/`、`data/designs/`、打印包）：连杆几何参数与整理成册的设计文档。
3. **数据**（`experiments/`、`data/measurements/`、社区提交的 `Measurement`）：仿真实验与物理实测数据。

单一许可证无法同时满足三类资产的传播与复用需求。详见 [`docs/LICENSING.md`](../LICENSING.md) 的完整对比。

## 决定

采用 **方案 A（带设计几何范围收窄与数据可选署名）**：

1. **代码：`MIT`**（见根目录 [`LICENSE`](../../LICENSE)）。
2. **设计库：`CC BY 4.0`（收窄范围）**（见 [`LICENSE-DESIGNS.md`](../../LICENSE-DESIGNS.md)）：
   - **设计集合/目录/文档说明**适用 CC BY 4.0（要求署名）；
   - **单个连杆几何数值本身**（如 `linkage.params` 中的 13 个杆长数值）视为事实性参数，不要求署名即可自由使用或打印。
3. **实测与实验数据：默认 `CC0 1.0` + 可选科学署名**（见 [`LICENSE-DATA.md`](../../LICENSE-DATA.md)）：
   - 法律上默认采用 CC0 1.0 放入公有领域，最大化降低社区征集与科研复用门槛；
   - 在提交表单与 `Measurement` 元数据中保留**可选署名字段**（科学溯源与致谢），同时允许贡献者按单次提交显式选择 `CC-BY-4.0`。

## 后果与验证

- 解除 R-06、V-06、R-05 的许可待定状态。
- `README.md`、`README.en.md`、`CONTRIBUTING.md`、`docs/PLATFORM.md`、`docs/HOW-TO-MEASURE.md` 及 `.github/ISSUE_TEMPLATE/data-contribution.yml` 同步更新。
- `./scripts/test-python.sh` 中的 `check_doc_refs.py` 校验新增许可证文件引用无误。
