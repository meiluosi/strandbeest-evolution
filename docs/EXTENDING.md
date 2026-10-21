# 扩展指南：加一个地形（或其他插件）

> 简体中文 · [English](#english--extending)
>
> 这份文档带一个**完整可跑的范例**：加一个叫 `ramp` 的地形（一个斜放的平台）。照着做完，你的地形在 Python 仿真器、浏览器仿真器、场景预设、参考文档里都能用，而且测试全绿。
>
> 范例的每一步都在这个仓库里验证过。

---

## 0. 扩展点在哪

四个注册表在 [`packages/sim/src/strandbeest_sim/registry.py`](../packages/sim/src/strandbeest_sim/registry.py)：

| 注册表 | 场景里写的名字 | 实现位置 |
|---|---|---|
| `terrains` | `terrain.kind` | `packages/sim/src/strandbeest_sim/terrains.py` |
| `winds` | `wind.kind` | `packages/sim/src/strandbeest_sim/winds.py` |
| `drives` | `drive.kind` | `packages/sim/src/strandbeest_sim/drives.py` |
| `metrics` | 指标名 | `packages/sim/src/strandbeest_sim/metrics_builtin.py` |

**场景文件只写名字字符串**，不是函数。注册表是运行时的唯一真相来源。

驱动注册比地形多一层：`drives` 有 `required_meta=("energy_source",)`，注册时**必须声明能量来源**（`wind` / `gravity` / `test_rig`），否则注册直接报错。这是 [`docs/WIND.md`](WIND.md) §2 的规则：电机驱动只能是测试台，不能伪装成风驱动。

---

## 1. 范例：加一个 `ramp` 地形

**目标**：一个从 x=0.3 m 开始、高 3 cm 的斜平台（不是台阶那样竖直的墙），用来测走兽能不能爬上缓坡。

### 1.1 Python 侧：注册实现

打开 `packages/sim/src/strandbeest_sim/terrains.py`，在文件末尾加：

```python
@terrains.register("ramp")
def ramp(sc: SimConfig) -> TerrainPlan:
    """A short inclined platform the feet must climb (not a vertical step).

    The ramp is a single box rotated by `angle_deg` about the y axis, starting at `start` metres.
    The angle and the height are assumptions: a printed ramp is not a wedge unless you model it.
    """
    p = sc.terrain.params
    start = float(p.get("start", 0.3))
    height = float(p.get("height", 0.03))
    length = float(p.get("length", 0.25))
    angle = float(p.get("angle_deg", 20.0))
    # A box tilted about y: its half extents are (length/2, 5, height/2); the centre sits at the
    # ramp's midpoint, raised by half the height and shifted so the near edge starts at `start`.
    mid = start + length / 2
    z = height / 2 + (length / 2) * math.sin(math.radians(angle))
    return TerrainPlan(obstacles=(Box("ramp", (mid, 0, z), (length / 2, 5, height / 2), sc.terrain.friction),))
```

要点：

- **参数全部从 `sc.terrain.params` 读，并且都有默认值**。`params` 是场景里的自由字典，你在 `x-doc` 里说明每个参数的单位与含义。
- **默认值就是"假设"**。这里 `angle_deg=20` 和 `height=0.03` 是猜的——把它们写进 schema 的 `x-doc` 的中英文说明里，并在 `docs/RESEARCH-NOTES.md` 记一句出处或标 `[unverified]`。
- `math` 已经在文件顶部导入了，`Box` 和 `TerrainPlan` 也在。
- **坡度角目前只在几何上体现，没有真的倾斜地面**（`TerrainPlan.slope_deg` 才是"倾斜重力"那条路）。坡道是一个斜放的方块，和 `slope` 地形不是一回事，文档里要说清楚。

### 1.2 浏览器侧：加平行的实现

**这一步不能省。** `packages/sim-web/src/terrains.ts` 是 Python 侧的平行实现（同一个 MJCF 构建逻辑有两份，见 `contracts/duplicated-modules.json`）。

在 `terrainPlan()` 的 `switch` 里加一个分支：

```ts
case "ramp": {
	const start = num(p.start, 0.3);
	const height = num(p.height, 0.03);
	const length = num(p.length, 0.25);
	const angle = num(p.angle_deg, 20.0);
	const mid = start + length / 2;
	const z = height / 2 + (length / 2) * Math.sin((angle * Math.PI) / 180);
	return plan({
		obstacles: [
			{
				name: "ramp",
				pos: [mid, 0, z],
				size: [length / 2, 5, height / 2],
				friction: t.friction,
				intSlots: true,
			},
		],
	});
}
```

注意 `intSlots: true`——Python 侧 y 槽写的是整数 `0` 和 `5`，打印时不能带 `.0`，否则 MJCF 文本对不上，契约测试会失败。

**数字必须逐位一致**：同样的默认值、同样的运算顺序。Python 的 `math.sin(math.radians(a))` 对应 TS 的 `Math.sin(a * Math.PI / 180)`——两者对同一个角度的舍入可能差最后一位，所以下面 §1.5 的字节级契约测试就是用来抓这个的。

### 1.3 Schema：说明这个地形

`schemas/scenario.schema.json` 里，`terrain.kind` 字段的 `x-doc` 列出了已知的地形名：

```json
"x-doc": {
  "zh": "地形类型：flat、slope、step、bumps……",
  "en": "Terrain kind: flat, slope, step, bumps, ..."
}
```

把 `ramp` 加进去（中英文都要改），并为你在 `params` 里用到的每个参数补 `x-unit` 与 `x-doc`：

```json
"params": {
  "type": "object",
  "x-doc": {
    "zh": "地形参数，含义取决于 kind。ramp 用 start（m）、height（m）、length（m）、angle_deg（度）。",
    "en": "Terrain parameters; the meaning depends on kind. ramp uses start (m), height (m), length (m), angle_deg (degrees)."
  }
}
```

`x-assumption` 用来标猜测值；`x-calibratable` 用来标"这个参数以后可以用实测校准"。注解规范见 [`schemas/ANNOTATIONS.md`](../schemas/ANNOTATIONS.md)。

### 1.4 重新生成派生文件

```bash
.venv/bin/python scripts/gen_models.py
.venv/bin/python scripts/gen_reference_docs.py
```

然后确认同步：

```bash
.venv/bin/python scripts/gen_models.py --check
.venv/bin/python scripts/gen_reference_docs.py --check
```

`docs/reference/` 里会出现新的假设清单条目——**这正是"我们到底猜了哪些参数"的总账**，别跳过。

### 1.5 契约语料库：证明两边一致

MJCF 的字节级一致性由 `contracts/sim-mjcf/cases.json` 保证。在 `contracts/generate_sim_mjcf.py` 的用例表里加一行：

```python
("terrain-ramp-defaults", "base", {"terrain": {"kind": "ramp"}}),
("terrain-ramp-params", "base", {"terrain": {"kind": "ramp", "friction": 0.8, "params": {"start": 0.2, "height": 0.05, "length": 0.4, "angle_deg": 25.0}}}),
```

然后重新生成：

```bash
.venv/bin/python contracts/generate_sim_mjcf.py
```

这个脚本会调用 Python 的构建器生成期望的 MJCF 文本；`packages/sim-web` 必须**逐字节**复现。测试在 `packages/sim-web/src/builder.test.ts`，由 `contracts/` 里的语料库驱动。

> **注意**：语料库的期望值是从 Python 侧生成的，所以它**只能证明两侧一致，不能证明两边都对**。语义正确性要靠你在 §1.7 里写测试。

### 1.6 场景预设（可选，但推荐）

`contracts/scenes.json` 是浏览器播放器和 Python 共用的场景预设。加一个 `ramp` 预设，浏览器里就能直接选：

```json
"ramp": {
  "label": { "zh": "斜坡", "en": "Ramp" },
  "ov": { "terrain": { "kind": "ramp", "friction": 1.0 } }
}
```

### 1.7 测试：语义正确性

在 `packages/sim/tests/test_scenes.py`（或新文件）里加测试：

```python
def test_ramp_plan_matches_the_assumptions():
    from strandbeest_sim.registry import terrains
    from strandbeest_sim import scenario_from_design, sim_config
    from strandbeest_common import Design
    from strandbeest_common.schemas import schema_dir

    design = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")
    sc = sim_config(scenario_from_design(design, {"terrain": {"kind": "ramp"}}))
    plan = terrains.get("ramp")(sc)
    assert len(plan.obstacles) == 1
    box = plan.obstacles[0]
    assert box.name == "ramp"
    assert box.size[0] == pytest.approx(0.125)   # length / 2
    assert box.pos[2] == pytest.approx(0.03 / 2 + 0.125 * math.sin(math.radians(20.0)))
```

**测不变量，不要测魔数**：上面的 `0.125` 只是"半长 = 长的一半"；真正该断言的是"坡道起点在 start 处"、"坡度角确实是 angle_deg"这类关系。

在 `packages/sim-web/src/` 里加对应的 TypeScript 测试，用同一组用例参数断言同样的量——两边都要断。

### 1.8 跑全部检查

```bash
pnpm check && ./scripts/test-python.sh
```

这会跑到：

- `packages/sim` 的测试（Python 侧）
- `packages/sim-web` 的测试（浏览器侧，含 MJCF 字节级契约）
- `check_duplication_trigger.py`（你没有新增双实现模块，不该越过触发线）
- `check_doc_refs.py`（你写进文档的每个路径都要真实存在）
- `check_schema_annotations.py`（每个数值字段都要有 `x-unit`）

---

## 2. 加地形时的坑（都是这个仓库真实踩过的）

1. **浏览器侧漏了不会报错，只会"地形不存在"。** `packages/sim-web/src/terrains.ts` 的 `default` 分支抛 `unknown terrain '...'`——在浏览器里表现为场景跑不起来，而不是测试红。
2. **MJCF 文本差一个 `.0` 就会失败。** Python 的 `y` 槽是整数 `0`/`5`，TS 必须用 `intSlots: true` 才不会打成 `0.0`/`5.0`。
3. **`soft` 地形踩过"以为软了其实没软"的坑**：MuJoCo 对两个都带 `solref` 的 geom 取**更硬**的那个，所以软化必须同时作用在地面和脚上（见 `docs/EXPERIMENTS.md` §13）。你若做"软"的地形，照这个来。
4. **地形参数是自由字典**，schema 不会替你校验 `params` 里的键名。写错键名会静默走默认值——**所以每个参数都要有测试**。
5. **别在扩展里藏魔法数字。** 每个物理量要么是场景字段，要么是有名字的模块常量并标 `assumption`。

---

## 3. 加风（`winds`）的差别

风的注册表在 `packages/sim/src/strandbeest_sim/winds.py`，函数签名是 `(sc: SimConfig) -> WindFn`，`WindFn` 是"时间 → 风速"的函数（`packages/sim/src/strandbeest_sim/winds.py` 里的 `constant` / `gusts` / `lull` / `turbulent` / `shear` / `profile_turbulent` 就是例子）。

浏览器侧同样有平行实现：`packages/sim-web/src/winds.ts`。

风比地形多一条：**湍流谱、积分尺度这类参数必须标 `assumption`**，因为谱的选择会直接改变阵风结论（见 `docs/WIND.md` §4）。

## 4. 加驱动的差别

驱动注册必须声明 `energy_source`：

```python
@drives.register("my_drive", energy_source="wind")
def my_drive(sim): ...
```

漏了会直接 `ValueError: drive 'my_drive' must declare ['energy_source']`。取值只能是 `wind` / `gravity` / `test_rig`。

**不要为了让结果好看而声明 `wind`。** `test_rig` 的结果不进排行榜和优化目标（`docs/WIND.md` §2）。

---

<a name="english--extending"></a>
# English — Extending

> [中文](#0-扩展点在哪)

This guide has a **complete, runnable example**: adding a `ramp` terrain (an inclined platform). Follow it and your terrain will work in the Python simulator, the browser simulator, the scene presets and the reference docs — with the tests green.

Every step of the example has been verified in this repository.

## 0. Where the extension points are

Four registries in [`packages/sim/src/strandbeest_sim/registry.py`](../packages/sim/src/strandbeest_sim/registry.py):

| Registry | Named in the scenario by | Implemented in |
|---|---|---|
| `terrains` | `terrain.kind` | `packages/sim/src/strandbeest_sim/terrains.py` |
| `winds` | `wind.kind` | `packages/sim/src/strandbeest_sim/winds.py` |
| `drives` | `drive.kind` | `packages/sim/src/strandbeest_sim/drives.py` |
| `metrics` | the metric name | `packages/sim/src/strandbeest_sim/metrics_builtin.py` |

**Scenario documents name a string**, not a function. The registry is the single runtime source of truth.

Drives carry one extra rule: `drives` has `required_meta=("energy_source",)`, so a registration **must declare where the energy comes from** (`wind` / `gravity` / `test_rig`) or it raises. This is the rule in [`docs/WIND.md`](WIND.md) §2 — a motor drive may only ever be a test rig, never disguised as wind drive.

## 1. Example: adding a `ramp` terrain

**Goal**: a short inclined platform starting at x = 0.3 m and 3 cm high (a ramp, not the vertical wall of a step), to test whether the walker can climb a gentle slope.

### 1.1 Python: register the implementation

Add to the end of `packages/sim/src/strandbeest_sim/terrains.py`:

```python
@terrains.register("ramp")
def ramp(sc: SimConfig) -> TerrainPlan:
    """A short inclined platform the feet must climb (not a vertical step).

    The ramp is a single box rotated by `angle_deg` about the y axis, starting at `start` metres.
    The angle and the height are assumptions: a printed ramp is not a wedge unless you model it.
    """
    p = sc.terrain.params
    start = float(p.get("start", 0.3))
    height = float(p.get("height", 0.03))
    length = float(p.get("length", 0.25))
    angle = float(p.get("angle_deg", 20.0))
    mid = start + length / 2
    z = height / 2 + (length / 2) * math.sin(math.radians(angle))
    return TerrainPlan(obstacles=(Box("ramp", (mid, 0, z), (length / 2, 5, height / 2), sc.terrain.friction),))
```

Key points:

- **Every parameter comes from `sc.terrain.params` and has a default.** `params` is a free-form dict in the scenario; document each key's unit and meaning in `x-doc`.
- **A default value is an assumption.** `angle_deg=20` and `height=0.03` are guesses — record them in the schema's `x-doc` (both languages) and note the source (or `[unverified]`) in `docs/RESEARCH-NOTES.md`.
- `math` and `Box` / `TerrainPlan` are already imported at the top of the file.
- **The angle is geometric only.** It does not tilt the ground; that is `TerrainPlan.slope_deg` (tilted gravity). A ramp and the `slope` terrain are different things — say so in the docs.

### 1.2 Browser: the parallel implementation

**This step is not optional.** `packages/sim-web/src/terrains.ts` is a parallel implementation of the same MJCF-building logic (two copies exist on purpose — see `contracts/duplicated-modules.json`).

Add a branch to the `switch` in `terrainPlan()`:

```ts
case "ramp": {
	const start = num(p.start, 0.3);
	const height = num(p.height, 0.03);
	const length = num(p.length, 0.25);
	const angle = num(p.angle_deg, 20.0);
	const mid = start + length / 2;
	const z = height / 2 + (length / 2) * Math.sin((angle * Math.PI) / 180);
	return plan({
		obstacles: [
			{
				name: "ramp",
				pos: [mid, 0, z],
				size: [length / 2, 5, height / 2],
				friction: t.friction,
				intSlots: true,
			},
		],
	});
}
```

Note `intSlots: true` — the Python side writes integers `0` and `5` into the y slots and they must print without `.0`, or the MJCF text will not match and the contract test fails.

**The numbers must agree bit for bit**: same defaults, same order of operations. Python's `math.sin(math.radians(a))` versus TS's `Math.sin(a * Math.PI / 180)` can differ in the last bit, which is exactly what the byte-level contract test in §1.5 catches.

### 1.3 Schema: describe the terrain

In `schemas/scenario.schema.json`, the `terrain.kind` field's `x-doc` lists the known kinds:

```json
"x-doc": {
  "zh": "地形类型：flat、slope、step、bumps……",
  "en": "Terrain kind: flat, slope, step, bumps, ..."
}
```

Add `ramp` to it (both languages), and give every parameter you use in `params` an `x-unit` and an `x-doc`:

```json
"params": {
  "type": "object",
  "x-doc": {
    "zh": "地形参数，含义取决于 kind。ramp 用 start（m）、height（m）、length（m）、angle_deg（度）。",
    "en": "Terrain parameters; the meaning depends on kind. ramp uses start (m), height (m), length (m), angle_deg (degrees)."
  }
}
```

`x-assumption` marks a guessed value; `x-calibratable` marks one that could later be calibrated against measurement. The annotation spec is [`schemas/ANNOTATIONS.md`](../schemas/ANNOTATIONS.md).

### 1.4 Regenerate the derived files

```bash
.venv/bin/python scripts/gen_models.py
.venv/bin/python scripts/gen_reference_docs.py
```

Then confirm they are in sync:

```bash
.venv/bin/python scripts/gen_models.py --check
.venv/bin/python scripts/gen_reference_docs.py --check
```

A new entry appears in the assumptions inventory in `docs/reference/` — **that is the ledger of "what exactly are we guessing"**, so do not skip it.

### 1.5 Contract corpus: prove the two sides agree

Byte-level MJCF parity is enforced by `contracts/sim-mjcf/cases.json`. Add rows to the case table in `contracts/generate_sim_mjcf.py`:

```python
("terrain-ramp-defaults", "base", {"terrain": {"kind": "ramp"}}),
("terrain-ramp-params", "base", {"terrain": {"kind": "ramp", "friction": 0.8, "params": {"start": 0.2, "height": 0.05, "length": 0.4, "angle_deg": 25.0}}}),
```

Then regenerate:

```bash
.venv/bin/python contracts/generate_sim_mjcf.py
```

The script asks the Python builder for the expected MJCF text; `packages/sim-web` must reproduce it **byte for byte**. The test lives in `packages/sim-web/src/builder.test.ts`, driven by the corpus in `contracts/`.

> **Note**: the corpus expectations are generated from the Python side, so it **proves the two sides agree, not that either is right**. Semantic correctness is what §1.7 is for.

### 1.6 Scene presets (optional, but recommended)

`contracts/scenes.json` holds the scene presets shared by the browser player and Python. Add a `ramp` preset and it becomes selectable in the browser:

```json
"ramp": {
  "label": { "zh": "斜坡", "en": "Ramp" },
  "ov": { "terrain": { "kind": "ramp", "friction": 1.0 } }
}
```

### 1.7 Tests: semantic correctness

Add to `packages/sim/tests/test_scenes.py` (or a new file):

```python
def test_ramp_plan_matches_the_assumptions():
    from strandbeest_sim.registry import terrains
    from strandbeest_sim import scenario_from_design, sim_config
    from strandbeest_common import Design
    from strandbeest_common.schemas import schema_dir

    design = Design.load(schema_dir() / "examples" / "design-jansen-small-6leg.json")
    sc = sim_config(scenario_from_design(design, {"terrain": {"kind": "ramp"}}))
    plan = terrains.get("ramp")(sc)
    assert len(plan.obstacles) == 1
    box = plan.obstacles[0]
    assert box.name == "ramp"
    assert box.size[0] == pytest.approx(0.125)   # length / 2
    assert box.pos[2] == pytest.approx(0.03 / 2 + 0.125 * math.sin(math.radians(20.0)))
```

**Test invariants, not magic numbers**: the `0.125` above is just "half the length"; what should be asserted is the relationship ("the ramp starts at `start`", "the slope really is `angle_deg`").

Add the mirror test on the TypeScript side in `packages/sim-web/src/` with the same case parameters — assert the same quantities. Both sides must be covered.

### 1.8 Run everything

```bash
pnpm check && ./scripts/test-python.sh
```

That runs:

- `packages/sim` tests (Python side)
- `packages/sim-web` tests (browser side, including the byte-level MJCF contract)
- `check_duplication_trigger.py` (you did not add a duplicated module, so no trigger line is crossed)
- `check_doc_refs.py` (every path you wrote in the docs must exist)
- `check_schema_annotations.py` (every numeric field needs an `x-unit`)

## 2. Traps, all of them hit for real in this repository

1. **Missing the browser side does not fail loudly — the terrain simply does not exist.** The `default` branch of `packages/sim-web/src/terrains.ts` throws `unknown terrain '...'`; in the browser that shows up as a scene that will not run, not as a red test.
2. **One `.0` in the MJCF text fails the test.** The Python side writes integers `0`/`5` into the y slots; the TS side needs `intSlots: true` so they do not print as `0.0`/`5.0`.
3. **The `soft` terrain once "did nothing".** For two geoms that both carry `solref`, MuJoCo uses the **stiffer** one, so softening must apply to the ground *and* the feet (`docs/EXPERIMENTS.md` §13). If your terrain is "soft", follow that.
4. **Terrain parameters are a free-form dict.** The schema does not validate the key names in `params`; a typo silently falls back to the default — **so every parameter needs a test**.
5. **Do not hide magic numbers in the extension.** Every physical quantity is either a scenario field or a named module constant marked `assumption`.

## 3. Adding a wind

The wind registry is in `packages/sim/src/strandbeest_sim/winds.py`; the signature is `(sc: SimConfig) -> WindFn`, where `WindFn` maps time to wind speed (see `constant` / `gusts` / `lull` / `turbulent` / `shear` / `profile_turbulent`).

The browser has the parallel implementation: `packages/sim-web/src/winds.ts`.

Winds carry one extra rule: **turbulence spectra and integral scales must be marked `assumption`**, because the choice of spectrum directly changes the gust conclusions (`docs/WIND.md` §4).

## 4. Adding a drive

A drive registration must declare `energy_source`:

```python
@drives.register("my_drive", energy_source="wind")
def my_drive(sim): ...
```

Omitting it raises `ValueError: drive 'my_drive' must declare ['energy_source']`. The only allowed values are `wind` / `gravity` / `test_rig`.

**Do not declare `wind` to make a result look better.** `test_rig` results never enter the leaderboard or the optimisation objectives (`docs/WIND.md` §2).
