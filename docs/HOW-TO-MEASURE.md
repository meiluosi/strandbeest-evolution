# 如何测一只走兽 · How to Measure a Strandbeest

> **一句话**：你有一台自己打印的走兽，想把它交给这个项目 —— 请按本文测几个量，写成一份 Measurement JSON，在本地跑一遍校验脚本，然后把 JSON 和原始数据一起提交。
> **In one line**: you built a Strandbeest and want to contribute it — measure a few quantities as described below, write one Measurement JSON, run the checker on it, and submit the JSON together with the raw data.

> **状态**：这份指南是任务卡 V-06 的产物，配套一个校验器 `packages/calib/src/strandbeest_calib/community.py` 和一个命令行入口 `scripts/validate_community_measurement.py`。仓库里**没有任何真实硬件实测数据**，所以本指南描述的是"应该怎么做"，不是"已经做成了"。
> **Status**: this guide belongs to task card V-06 (see `docs/ACTIONS.md`). It comes with a validator (`packages/calib/src/strandbeest_calib/community.py`) and a thin CLI (`scripts/validate_community_measurement.py`). **No real hardware measurement exists in this repository yet**, so this document says how a measurement should be made — not that one has been.

---

## 0. 这个项目现在缺什么 · What this project is missing

`docs/VALIDATION.md` §3 记录了"检验梯子"：每个量能拿到什么级别的证据。表里明确写着两行是**缺口**：

| 量 / quantity | 公开数据 / public data | 现状 |
|---|---|---|
| 扭矩、电流 / torque, current | 没找到 / none found | **缺口** |
| 起步风速 / start wind speed | 只有 Jansen 官网的陈述（Aurum 期约 15 km/h，体型未知），只能做数量级检查 | **缺口** |

`docs/VALIDATION.md` §3

这意味着两件事：

1. **我们做不出的数，正是你能提供的数。** 扭矩（负载扭矩曲线 T(θ)）和起步风速是这个项目最想要的两项实测数据，目前一条都没有。
2. **一份做得好的社区实测能直接到 E3。** 按 `docs/VALIDATION.md` §2，**E3 = 被可追溯的实测验证（自己或社区）**。这是本项目目前最高的证据等级，而且是**空的**。你的数据如果是第一次真实的扭矩曲线，它就是本项目第一条 E3 扭矩数据。

反过来说：**一个没有出处的数字到不了 E3**。它最多是 E0（只有一个模型算过）。差别不在数字大小，而在"能不能追溯到谁、用什么仪器、什么时候、怎么标定的、误差多少"。

**EN**

`docs/VALIDATION.md` §3 lists what public evidence exists for each quantity. Two rows are explicitly gaps: **torque/current** (nothing found) and **start wind speed** (only an artist statement of about 15 km/h for a machine of unknown size, which is no more than an order-of-magnitude check).

Two consequences. First, the numbers we cannot produce are exactly the numbers you can produce: a load-torque curve T(θ) and a start-wind speed are the two measurements this project wants most, and it has neither. Second, a well-made community measurement reaches **E3** — "verified by traceable physical measurement (own or community)" (`docs/VALIDATION.md` §2) — which is currently empty, the highest level the project defines. If yours is the first real torque curve, it is the project's first E3 torque data.

The other side of the same coin: **a number without provenance cannot reach E3**. It stays at E0 (single-model simulation). The difference is not how big the number is, but whether it can be traced to a person, an instrument, a date, a calibration and an error estimate.

---

## 1. 你要交什么 · What you submit

三样东西：

| # | 内容 | 说明 |
|---|---|---|
| 1 | **一份 Measurement JSON** | 契约是 `schemas/measurement.schema.json`；字段的逐项说明在 `docs/reference/measurement.md` |
| 2 | **原始数据文件** | 你实际记录的东西（CSV、视频、标定记录、笔记）。放在 `provenance.raw_file` 里点名它 |
| 3 | **实验笔记** | 用 `hardware/templates/lab-notebook.md` 的格式；或者至少把"当天发生了什么"写进 `build_note` 和 `provenance.notes` |

第 2 和第 3 项不是可选项：没有它们，你的数据到不了 E3（见 §7）。

**EN**

Three things: (1) one **Measurement JSON** whose contract is `schemas/measurement.schema.json` (field-by-field reference: `docs/reference/measurement.md`); (2) the **raw data** you actually recorded — a CSV, a video, the calibration sheet — named in `provenance.raw_file`; (3) a **lab note**, ideally following `hardware/templates/lab-notebook.md`, or at least the day-to-day story in `build_note` and `provenance.notes`.

Items 2 and 3 are not optional: without them the data cannot reach E3 (§7).

---

## 2. 要测哪几个量 · The quantities to measure

项目里真正被消费的量只有这些（`packages/calib/src/strandbeest_calib/compare.py` 对照的就是它们）：

| 量 / quantity | 写在哪 / written where | 单位 / unit | 建议样本数 / how many samples | 误差估计从哪来 / where the error comes from |
|---|---|---|---|---|
| 曲柄角 ψ(t) | `channels/psi` | `rad` | ≥ 3 圈（≥ 180 个点） | 视频帧间隔 ÷ 帧率；30 fps、2 rad/s 时约 ±0.02 rad |
| 曲柄转速 ω | `conditions/omega_rad_s` | `rad/s` | ≥ 3 圈 | 计时误差（±0.2 s）÷ 计时长度；圈数误差 ÷ 圈数 |
| 负载扭矩 τ(t) | `channels/torque` | `N*m` | 连续曲线 ≥ 3 圈；或静态取 12–36 个曲柄角 | 砝码分辨率 × 力臂；或电流法里 Kt 拟合的残差 |
| 机体位置 x(t)（步幅） | `channels/x` | `m` | ≥ 3 圈，每帧一个点 | 视频比例尺误差（目标 ≤ 2 %）+ 读数分辨率 |
| 风速（起步风速） | `conditions/wind_m_s` | `m/s` | 起步阈值至少夹 3 次 | 夹逼区间宽度 ÷ 2，加上风速仪本身的精度 |

另外两个量**不属于 Measurement**，属于**设计**：整机质量与连杆几何（§3.6）。它们写进你提交的设计文件，并写进 `build_note`。

**EN**

The project only consumes the quantities in this table (`packages/calib/src/strandbeest_calib/compare.py` compares exactly these). Two more quantities — mass and linkage geometry — belong to the **design**, not to the Measurement (§3.6); they go into the design file you submit and into `build_note`.

---

## 3. 怎么做 · How to measure

下面每一节都是"没有专用仪器也能做"的版本；仓库里更完整的测试台流程在 `hardware/README.md`（标定步骤与 E0–E4 实验），**先看那份**，能照做就照做。

### 3.1 曲柄角 ψ(t) 与转速 ω

**测什么**：曲柄沿**行走方向**转过的角（`docs/CONVENTIONS.md` §3：ψ 沿行走方向为正），以及平均转速。

**怎么做（最省事）**：手机或相机侧向拍，≥ 30 fps；数圈数 × 2π 就是 ψ，圈数除以秒数就是转速。

**怎么做（准一些）**：用 `hardware/README.md` 描述的测试台：电机轴上的编码器 + ESP32 固件，串口打印 `t_ms,enc,current_mA,load_raw,wind_pulses,pwm` 这几列；`packages/rig/src/strandbeest_rig/convert.py` 负责把它换算成 ψ。

**样本数**：至少 3 圈。第一圈是起动瞬态，惯例是丢掉（比较时用 `skip_rev` 跳过 0.5 圈）。

**误差**：视频法的主要误差是"帧率 × 相位"：30 fps、2 rad/s 时一帧对应 0.067 rad，读相位误差约 ±0.02 rad；转速误差 = 计时误差 ÷ 计时长度（数 6 圈用 19 s，±0.2 s 的反应误差 → 约 ±1 %）。编码器法可以做到好一个量级，但需要硬件。

**单位**：`rad`、`rad/s`。

### 3.2 负载扭矩 τ(t) —— 我们最缺的那一项

**测什么**：曲柄要克服机构内阻、连杆重力与足端推地反力所需要的力矩，随曲柄角变化，即 T(θ)。这正是 `docs/EXPERIMENTS.md` §32 里"虚拟测力计"在模型里画的那条曲线。

**两种做法**（二选一，都要标定）：

* **电流法**：已知电机扭矩常数 Kt（N·m/A），记录电流 I，扭矩 = (I − I_idle) × Kt。**必须**先做悬挂砝码标定：在曲柄上装一个已知力臂的杠杆，挂已知质量的砝码，电机顶住不转，记下每个质量的电流，至少 4 个质量点。仓库的工具是 `strandbeest-rig torque-cal masses.csv --arm-m 0.05`（实现见 `packages/rig/src/strandbeest_rig/calibration.py`），它给出 Kt、空载电流和拟合残差。**残差就是这条标定链的误差下界**，把它写进误差估计。
* **称重传感器法（力臂）**：一个 HX711 + 小称重传感器（0.5 kg 级），力臂长度已知，力矩 = 质量读数 × g × 力臂。标定方式见 `hardware/README.md` 的 "Calibration" 第 4 步。

**测的时候**：慢速。准静态比较要求 ω ≤ 0.5 rad/s，这样 T(θ) 才是"这一角度需要多大扭矩"，而不是"这个速度下惯性占多少"。

**样本数**：连续曲线 ≥ 3 圈；或者静态地在 12–36 个曲柄角上读数（准静态更稳，也更容易用手工做到）。

**误差**：力臂法的分辨率 = 称重传感器最小刻度 × g × 力臂（1 g、50 mm 力臂 → 4.9e-4 N·m），再加上零点漂移；电流法的误差 = Kt 的相对误差 × 电流 + 电流采样误差。**误差必须是同一个量纲下的绝对值**（N·m），不是百分比。

**单位**：`N*m`。

**参考数字（模型内，不是实测）**：标准 6 腿小尺寸 Jansen 的峰值负载扭矩约 2.6 mN·m，死点角约 20°（`docs/EXPERIMENTS.md` §32）。你测出来的数如果和它差一个量级，先查单位。

### 3.3 步幅（机体位置 x(t)）

**测什么**：机体沿前进方向的位置随时间的变化；**步幅 = 每转一圈机体前进的距离**。

**怎么做**：侧向固定机位拍片，机身贴一个打印的 ArUco 标记（DICT_4X4_50，id 7）；`packages/rig/src/strandbeest_rig/video_track.py` 把它跟踪成 x(t)。没有标记就用网格纸 + 直尺。

**标定**：把尺子放在运动平面里一起入镜，得到"毫米每像素"；`hardware/README.md` 要求标定与实际比例一致到 **2 % 以内**。

**样本数**：≥ 3 圈，每帧一个点。

**误差**：比例尺误差（目标 ≤ 2 %）+ 透视误差（机位越正、镜头越长越好）+ 视频帧率给出的时间分辨率。

**单位**：`m`。

**注意**：步幅不可能大于腿的可达范围。校验器会拿你填的 `design_id` 去算那条腿的足端轨迹宽度，超了就报一条警告。参考设计（`schemas/examples/design-jansen-small-6leg.json`，unit_m = 0.002）的足端轨迹宽 0.136 m，平底行程 0.114 m。

### 3.4 起步风速 —— 我们第二缺的那一项

**测什么**：**定常风速从静止开始，曲柄能连续转完一整圈**的最小风速。定义必须和模型里一致（`docs/EXPERIMENTS.md` §28：从静止起，40 s 内转完一整圈的最小定常风速），否则两边没法比。

**怎么做**：

1. 装上你的帆，风速仪放在**帆的高度**上读数（不是地面高度）。
2. 从低风速开始，每档风速**保持 10 s**，记录"转完一整圈 / 没转完"。
3. 二分或逐步逼近，得到一个区间 (v_lo, v_hi]：低于 v_lo 不走，处于 v_hi 一定走。
4. **重复至少 3 次**：起步阈值强烈依赖曲柄的初始相位（死点约 20°），同一档风速有时起步、有时死在那里。

**误差**：报告区间的中点，误差取区间宽度的一半，再加风速仪本身的精度。例如区间 (0.85, 0.95] m/s → 记 0.90 ± 0.05 m/s。

**单位**：`m/s`，写在 `conditions.wind_m_s`，并把 `conditions.kind` 设成 `"fan"`。

**参考数字（模型内，不是实测）**：标准 6 腿小尺寸 Jansen 的模拟起步风速约 0.489 m/s（区间 0.479–0.500）；但只要每个关节有 0.5 mN·m 的销轴摩擦，就升到约 1.05 m/s（`docs/EXPERIMENTS.md` §28）。**销轴摩擦是这里最大的未知量**，也正是实测最值钱的地方。

### 3.5 质量

**测什么**：整机的总质量（最好分件称，再求和）。

**怎么做**：厨房秤（1 g 分辨率）逐件称；机身、每条腿、曲柄、帆分开称，求和。

**误差**：每件 ±1 g，加上打印件的一致性（同样长的杆，不同次打印差 1–2 %）。

**写在哪**：Measurement 里**没有质量字段**——质量属于设计，写进你提交的设计文件，同时在 `build_note` 里写一句"实测总质量 = X g"。

### 3.6 连杆几何

**测什么**：13 个长度 a…m（用设计文件里的"长度单位"）、`unit_m`（一个长度单位等于多少米）、销孔直径与装配间隙。

**怎么做**：卡尺量打印件（0.1 mm 分辨率）；或者直接量 STL。每根杆量两端销孔**中心距**，不要量杆的总长。

**误差**：±0.2 mm；相对误差 = 0.2 mm ÷ 杆长。以参考设计的 unit_m = 0.002 m、杆长 40 单位（80 mm）为例，相对误差约 0.25 %。

**写在哪**：设计文件 `linkage.params`（13 个数）与 `walker.unit_m`。**写进 `build_note`**：你改了哪几个长度、实测多少、和你参考的设计差多少。

**为什么重要**：足端轨迹是本项目已达 E2 的量（`docs/EXPERIMENTS.md` §30）。你的几何如果和参考设计不同，模拟器必须知道。

---

## 4. 你要写的那个文件 · The file you write

一份 Measurement JSON，契约是 `schemas/measurement.schema.json`。完整的示例：`schemas/examples/measurement-community-example.json`（**注意：那份示例里的数字是编出来的**，它只用来展示格式）。

```json
{
	"schema_version": 2,
	"id": "01KKNVH3SR58XMRQBEFY0938NK",
	"name": "my-walker-2026-03-14",
	"design_id": "0000000000YNGRWX0MDFYPZHXT",
	"design_name": "jansen-small-6leg",
	"synthetic": false,
	"build_note": "6 腿 Jansen，PLA，0.2 mm 层高，3 mm 销，间隙 0.3 mm；整机实测 96 g",
	"conditions": {
		"kind": "motor_no_wind",
		"omega_rad_s": 2.0,
		"surface": "glass sheet on a wooden table"
	},
	"channels": {
		"t": [0.0, 0.0333, "…"],
		"psi": [0.0, 0.0667, "…"],
		"torque": [0.0021, 0.0024, "…"],
		"x": [0.0, 0.0071, "…"]
	},
	"provenance": {
		"source": "manual",
		"rig_version": "hand-rig-1",
		"calibration": {
			"instrument": "…仪器、量程、分辨率…",
			"measured_on": "2026-03-14",
			"calibrated_on": "2026-03-10",
			"units": { "t": "s", "psi": "rad", "torque": "N*m", "x": "m", "omega_rad_s": "rad/s" },
			"uncertainty": { "psi": 0.02, "omega_rad_s": 0.02, "torque": 0.0005, "x": 0.003 },
			"licence": "CC0-1.0"
		},
		"raw_file": "walk-2026-03-14.csv",
		"notes": "当天做了什么、和标定有什么出入"
	}
}
```

逐项说明：

通道名本身就是单位契约：`t` 是秒、`psi` 是弧度、`torque` 是 N·m、`x` 是米、`wind` 是 m/s；条件字段 `omega_rad_s` 是 rad/s、`wind_m_s` 是 m/s。**校验器按这个契约检查你写的数**，写成别的单位会被拒。

| 字段 / field | 要求 |
|---|---|
| `channels.t` | 必填，秒，严格递增，所有通道和它等长 |
| `channels.psi` | 曲柄角，弧度，沿行走方向递增。**真实实测必须带这一条**：没有它就没法对齐曲柄相位 |
| `channels.torque` | 扭矩，N·m，正号表示驱动方向 |
| `channels.x` | 机体前进位置，米，原点任意（通常取第一帧） |
| `channels.wind` | 风速，m/s（可选；如果填了，风速仪读数最好也在 `conditions.wind_m_s` 里） |
| `conditions.kind` | `"motor_no_wind"` 或 `"fan"`；测风速就用 `"fan"` |
| `conditions.omega_rad_s` | 曲柄转速，rad/s |
| `conditions.surface` | 地面（"glass"、"sand"、"paper"…），写清楚 |
| `provenance.source` | `"rig"`（用仓库测试台）、`"manual"`（手工测量）或 `"simulator"` |
| `provenance.calibration` | **社区约定的出处块**，见下 |
| `provenance.raw_file` | 原始数据文件名 |
| `provenance.notes` | 自由文本：当天发生了什么 |

### 4.1 `provenance.calibration` 里的社区约定

Measurement 的 schema 没有"仪器 / 标定 / 不确定度 / 许可"这些字段，`provenance.calibration` 又是自由对象，所以本项目约定把下面这几个键放进去。**这不是 schema 的规定，是本指南的约定**；将来 schema 加了正式字段，就迁移过去。

| 键 / key | 内容 | 为什么 |
|---|---|---|
| `instrument` | 仪器、量程、分辨率 | 没有仪器就无法追溯 |
| `measured_on` | 测量日期 `YYYY-MM-DD` | 数据有时间才有意义 |
| `calibrated_on` | 仪器标定日期 `YYYY-MM-DD` | 误差估计要能对上标定记录 |
| `units` | 每个通道与条件量声明的单位 | 契约固定了单位；声明一遍可以当场发现写错 |
| `uncertainty` | 每个量的**绝对**误差估计 | E3 的必要条件 |
| `licence` | 你的数据许可意向，见 §8 | 提交前必须说清楚 |

`units` 的合法值（校验器只认这些）：`s`、`rad`、`N*m`、`m`、`m/s`、`rad/s`。写成别的（比如 `mN*m`）会被**拒绝**，因为契约把扭矩固定成 N·m。

`uncertainty` 的键和通道同名（`psi`、`torque`、`x`、`wind`、`omega_rad_s`、`wind_m_s`），值是绝对误差，且必须大于 0。**百分比误差要先换算成绝对值**：步幅 0.114 m、误差 3 % → 写 0.0034。

---

## 5. 先自己校验一遍 · Check it yourself

```bash
python scripts/validate_community_measurement.py my-measurement.json
```

它会打印一份报告（并在被拒绝时以非零状态退出）：

```
submission: my-measurement.json
verdict: ACCEPTED (0 error(s))
evidence level: E3 for crank angle psi(t), crank speed, crank torque tau(t), body position x(t) and the stride per revolution
quality: sample_rate_hz=30.03, duration_s=9.5, dropouts=0, revolutions=3.024, speed_mean_rad_s=1.9976, speed_cv=0.0012, torque_mean_nm=0.002014, torque_max_nm=0.003737, stride_m=0.1143
present:
  - crank angle psi(t) (channels/psi)
  ...
missing:
  - wind speed at the walker (conditions/wind_m_s)
```

加 `--json` 可以拿到机器可读的版本。脚本会自动按 `design_id` 在 `schemas/examples/` 和 `data/designs/` 里找设计，用来检查步幅有没有超出腿的可达范围；找不到就跳过这项检查。

如果你的环境还没装 Python 依赖：

```bash
./scripts/setup-python.sh && source .venv/bin/activate
```

**EN**

Run `python scripts/validate_community_measurement.py my-measurement.json`. It prints the report and exits non-zero when the submission is rejected; `--json` prints the machine-readable form. The script looks the design up by `design_id` in `schemas/examples/` and `data/designs/` so it can check the stride against the leg's reach. If you have not installed the Python dependencies yet: `./scripts/setup-python.sh && source .venv/bin/activate`.

---

## 6. 报告怎么读 · Reading the quality report

报告分五块，含义不同：

| 块 / block | 含义 | 要不要管 |
|---|---|---|
| **errors** | 硬失败，提交被拒 | 必须改 |
| **warnings** | 可疑但不一定错 | 读一遍，能解释就在笔记里写清楚 |
| **present** | 量到了，而且记录够完整 | 可以支撑证据等级 |
| **present but weak** | 量到了，但缺东西（没有误差估计、单位没声明……） | 补上就能升到 E3 |
| **missing** | 根本没测 | 这就是缺口 |

校验器会查的几类"可疑"（都用的是测试台那套词：`sample_rate_hz`、`duration_s`、`revolutions`、`speed_mean_rad_s`、`speed_cv`、`dropouts`、`warnings`）：

- 采样率太低（低于 10 Hz 报警）：曲柄相位分辨不出来。
- 圈数少于 3：第一圈是起动瞬态。
- 转速不稳（`speed_cv` 超过 15 %）：不是准静态，比较会失真。
- 实测转速与 `conditions.omega_rad_s` 差 15 % 以上。
- 扭矩一直不正：符号可能反了。
- 步幅超过腿的可达范围。
- 数值量级与契约单位明显不符：扭矩峰值超过 10 N·m（一台打印走兽不可能需要这么多），或者位置、时间的量级像是毫米、毫秒。

**EN**

The report has five parts with different meanings: **errors** (hard failures, the submission is rejected), **warnings** (suspicious but not necessarily wrong — read them and explain them in your notes), **present** (measured and documented well enough to support an evidence level), **present but weak** (measured but incomplete — no error estimate, no declared unit), and **missing** (never measured; that is the gap).

The checks use the rig's own vocabulary (`sample_rate_hz`, `duration_s`, `revolutions`, `speed_mean_rad_s`, `speed_cv`, `dropouts`, `warnings`): too low a sample rate (below 10 Hz), fewer than 3 revolutions, an unsteady crank speed (`speed_cv` above 15 %), a measured speed that differs from `conditions.omega_rad_s` by more than 15 %, a torque channel that is never positive, a stride longer than the leg's reach, and magnitudes that cannot be the unit the contract fixes (torque written in mN·m, for instance).

---

## 7. 证据等级：方法比数字重要 · Evidence level: the method matters more than the number

`docs/VALIDATION.md` §2 的四个等级里，**E0** 是"只有一个模型算过"，**E3** 是"被可追溯的实测验证"。社区实测要落到 E3，必须同时满足下面全部条件（校验器逐条检查）：

1. 量真的在文件里（对应通道或条件字段有值）；
2. 声明了单位（`provenance.calibration.units`）；
3. 记了**绝对**误差估计（`provenance.calibration.uncertainty`，且大于 0）；
4. `provenance.source` 说明数据从哪来（`rig` 或 `manual`）；
5. 写了仪器（`instrument`）、测量日期（`measured_on`）、标定日期（`calibrated_on`）；
6. 原始数据有出处（`raw_file`）；
7. 说了许可（`licence`）；
8. 文件本身不是 `synthetic`（模拟器生成的记录不算实测）。

八条齐了，报告里的 `evidence level` 会写"E3 for …"，并列出这份数据能支撑哪几个量。少任何一条，那个量就留在"present but weak"里，证据等级仍是 E0。

**校验器查不出"你是不是真的测了"** —— 它查的是格式和内部一致性。数据是不是真的、做得对不对，由人来看：这就是"证据审查"要干的活。

**EN**

Of the four levels in `docs/VALIDATION.md` §2, **E0** is "only one model has run this" and **E3** is "verified by traceable physical measurement". A community measurement reaches E3 only if all of the following hold (the validator checks each one): the quantity is really in the file; its unit is declared; an **absolute** error estimate is recorded; `provenance.source` says where the numbers came from; the instrument, the measurement date and the calibration date are recorded; the raw data is referenced; the licence is stated; and the document is not `synthetic`.

With all eight, the report prints "evidence level: E3 for …" and names the quantities the data can support. Miss one and that quantity stays "present but weak" at E0.

**The validator cannot tell whether you really measured it** — it checks form and internal consistency. Whether the measurement is real and done well is for a human to judge; that is what the evidence review is for.

---

## 8. 许可：默认 CC0 1.0（带可选署名） · Licensing: CC0 1.0 by default (with optional credit)

**本项目对实测数据默认采用 `CC0-1.0`（公有领域贡献，见 `LICENSE-DATA.md` 与 `docs/LICENSING.md`），同时保留科学出处与可选署名。**

在 `provenance.calibration.licence` 里填写你授予的许可，取值只能是下面四个之一：
  - `CC0-1.0`（**推荐/项目默认**）—— 放进公有领域，谁都能用，不用承担法律署名义务（我们仍会在实验记录中按科学出处致谢你）；
  - `CC-BY-4.0` —— 允许自由使用，但要求法律署名；
  - `all-rights-reserved` —— 保留所有权利，别人要用需先问过你；
  - `pending` —— 你还没决定，请项目方来问。
- 写了 `pending` 不会让提交作废，但报告会把它列成 E3 的一道缺口。

**EN**

**The project's default licence for contributed measurement data is `CC0-1.0` (see `LICENSE-DATA.md` and `docs/LICENSING.md`), while preserving scientific provenance and optional contributor credit.** State your chosen licence in `provenance.calibration.licence`, using one of `CC0-1.0` (recommended default), `CC-BY-4.0`, `all-rights-reserved`, or `pending`. `pending` does not invalidate the submission, but the report lists it as one gap towards E3.

---

## 9. 没有仪器怎么办 · If you have no instruments

**只需要一台手机（或者一个秒表）也能交一份有用的数据。** 这份"最小可行测量"能得到 **曲柄转速** 和 **步幅** 两个量：

1. 把走兽放在画了网格的纸上，机身起点对准一条线；侧向拍片（≥ 30 fps），或者用秒表数圈、用直尺量位移。
2. 数出 **n** 圈、用时 **T** 秒 → ω = 2πn/T。
3. 这 n 圈里机体前进 **D** → 步幅 = D/n。
4. 通道只写两个点：`t = [0, T]`、`psi = [0, 2πn]`、`x = [0, D]`。
5. 误差估计：ω 的相对误差 ≈ ΔT/T + 1/n（秒表反应 ±0.2 s）；步幅的误差 ≈ 两次读数各 ±2 mm 再除以 n。
6. **不要**省略 `provenance.calibration` 里的仪器、日期、单位、误差和许可——它们比曲线本身更决定这份数据能不能用。

这样的一份记录会得到一条"采样率太低"的警告（两个点算不出速率），但**步幅和曲柄转速仍然可以到 E3**，只要误差估计写了**、许可也写了**（写 `pending` 就还差一道，见 §8）。

**它做不到的两件事**：**扭矩**（需要电流表、称重传感器或者至少一台能当力矩用的秤 + 力臂）和**起步风速**（需要风速仪）。这两个正是我们最缺的（§0）。如果你手上有这两样东西，请优先做它们。

**EN**

A phone camera — or just a stopwatch — is enough for a useful submission. Count **n** revolutions over **T** seconds (ω = 2πn/T) and measure how far the body travelled **D** (stride = D/n); write two points per channel: `t = [0, T]`, `psi = [0, 2πn]`, `x = [0, D]`. Estimate the errors: for ω, roughly ΔT/T + 1/n with a ±0.2 s reaction error; for the stride, the two readings (±2 mm each) divided by n. Do not omit `provenance.calibration` — the instrument, the dates, the units, the uncertainties and the licence decide whether the record is usable, more than the curve does.

Such a record gets one warning (the sample rate is far too low for two points), but the **stride and the crank speed can still reach E3** as long as the error estimates are there **and the licence is stated** (`pending` leaves one gap open, see §8). What it cannot do is measure **torque** (needs a current meter, a load cell or at least a scale and an arm) or the **start wind** (needs an anemometer) — the two gaps we care most about (§0). If you have either, do that one.

---

## 10. 怎么提交 · Submitting

1. 本地校验通过（§5）。
2. 把 Measurement JSON **和原始数据文件**一起提交：开一个 issue 或 pull request，把 JSON 贴进去或作为附件，并说明"这是实测"。也可以直接 POST 给本项目的 API（`apps/api` 的 `/measurements` 端点），但 issue/PR 才是给维护者看的地方。
3. 在 issue 里补一句：`docs/EXPERIMENTS.md` 里的结论要引用你的数据时，需要你确认口径。

**安全**：曲柄和腿之间会夹手；带电前先固定电源限流；不要在通电时伸手。详见 `hardware/README.md` 的 "Safety"。

**EN**

Validate locally (§5), then submit the Measurement JSON **together with the raw data file** — as an issue or pull request, with the JSON inline or attached, saying that it is a physical measurement. The API also accepts it (`POST /measurements` in `apps/api`), but an issue or PR is where the maintainers look. Say so in the issue if you want to be quoted when the results reach `docs/EXPERIMENTS.md`.

**Safety**: the crank and the legs are a pinch point; use a current-limited supply and keep your hands out while the motor is powered. See the "Safety" section of `hardware/README.md`.

---

## 11. 仓库里已经有的东西 · What the repository already has

别重复造轮子：这些是现成的，照做就行。

| 你要做的 | 现成的 |
|---|---|
| 完整的测试台接线、零件类别、安全 | `hardware/README.md` |
| 标定流程（编码器、空载电流、扭矩常数、力臂、风速仪、相机） | `hardware/README.md` 的 "Calibration" 六步 |
| 实验协议 E0–E4（手转一条腿 → 慢速行走 → 表面/速度变体 → 空载与堵转 → 风扇） | `hardware/README.md` 的 "Experiments" |
| 原始 CSV → Measurement + 质量报告 | `packages/rig/src/strandbeest_rig/convert.py` |
| 悬挂砝码 → 扭矩常数 | `packages/rig/src/strandbeest_rig/calibration.py` |
| 视频 → 机体位置 x(t) | `packages/rig/src/strandbeest_rig/video_track.py` |
| 命令行：转换、追踪、虚拟台、扭矩标定 | `packages/rig/src/strandbeest_rig/cli.py` |
| 实验笔记模板 | `hardware/templates/lab-notebook.md` |
| 标定文件模板 | `hardware/templates/rig-calibration.example.json` |
| 提交校验 + 质量报告 | `packages/calib/src/strandbeest_calib/community.py` |
| Measurement 与仿真的对照 | `packages/calib/src/strandbeest_calib/compare.py` |
| 字段的逐项说明 | `docs/reference/measurement.md` |
| 证据等级与缺口 | `docs/VALIDATION.md` |
| 坐标系、符号、单位 | `docs/CONVENTIONS.md` |

**EN**

Do not reinvent any of this: `hardware/README.md` (wiring, parts, the six-step calibration, the E0–E4 experiment protocols, safety), `packages/rig/src/strandbeest_rig/convert.py` (raw CSV → Measurement with a quality report), `packages/rig/src/strandbeest_rig/calibration.py` (hanging-mass torque calibration), `packages/rig/src/strandbeest_rig/video_track.py` (video → body position), `packages/rig/src/strandbeest_rig/cli.py` (the commands), `hardware/templates/lab-notebook.md` and `hardware/templates/rig-calibration.example.json` (templates), `packages/calib/src/strandbeest_calib/community.py` (this submission check), `packages/calib/src/strandbeest_calib/compare.py` (Measurement vs simulation), `docs/reference/measurement.md` (field reference), `docs/VALIDATION.md` (evidence levels and gaps) and `docs/CONVENTIONS.md` (frames, signs, units).

---

## 附录 A：完整示例 · Appendix A: the complete example

`schemas/examples/measurement-community-example.json` 是一份**格式完整**的社区提交：手机 30 fps 视频 + 力臂称重传感器测扭矩、玻璃台面、2.0 rad/s、3 圈。

**它的数字是编出来的**（文件里的 `build_note` 和 `notes` 都写明了这一点）——本仓库到今天为止没有任何真实硬件实测。它存在的意义是：给你看格式长什么样，也给校验器一个"干净的报告"长什么样。

**Its numbers are fabricated** (the file says so in `build_note` and `notes`): this repository still contains no real hardware measurement. It exists to show the format, and to show the validator what a clean report looks like.
