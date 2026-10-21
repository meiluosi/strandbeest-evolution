# 贡献指南

> 简体中文 · [English](#english--contributing)
>
> 读完这一页你应该能：装好环境、跑通检查、加一个扩展、把设计/数据提进来，并且**不违反本项目的诚实规则**。

---

## 0. 这个项目在做什么（先看这个）

一个 **Strandbeest（Jansen 连杆）仿真平台**：从连杆几何、运动学、动力学、风驱动仿真，到演化优化与可交互演示。

产品的方向写在 [`docs/WIND.md`](docs/WIND.md)：**产品结论里的走兽只靠风驱动**（电机只作测试台），每个数字都带**证据等级** E0–E3（见 [`docs/VALIDATION.md`](docs/VALIDATION.md)）。

这意味着两件事：

1. **"能跑"不等于"对"。** 我们的多数结论是 **E0（只有一个模型算过）**。把一个结果说成"验证过"，需要两个独立求解器一致（E1）或与公开数据相符（E2），实测才是 E3。
2. **负面结果同样是成果。** 走不动、扭矩对摩擦建模敏感、某个设计在模型里好看但换个求解器就掉队——这些都要写进 [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md)，**带数字**。

---

## 1. 环境

```bash
git clone <this repo> && cd strandbeest-evolution
pnpm install                 # Node >= 22
./scripts/setup-python.sh    # Python 3.10+（用 .venv/）
```

装好后应当能跑：

```bash
pnpm check                   # Biome + 类型检查 + TS 测试
./scripts/test-python.sh     # Python 测试 + 仓库级检查（含文档链接检查）
```

`./scripts/test-python.sh` 里包含几个"仓库级"检查，它们会拦住大部分低级错误：

| 检查 | 拦什么 |
|---|---|
| `check_no_hardcoded_cjk.py` | 界面代码里写死的中文（必须走 i18n 消息键） |
| `check_schema_annotations.py` | schema 里缺 `x-unit` 等注解的数值字段 |
| `gen_models.py --check` | 生成的 Python 模型与 schema 不同步 |
| `gen_reference_docs.py --check` | `docs/reference/` 与 schema 注解不同步 |
| `check_duplication_trigger.py` | TS/Python 双实现的模块数越过 ADR-0009 的触发线 |
| `check_doc_refs.py` | **文档里引用的脚本/文件/命令不存在** |

---

## 2. 提交之前必跑

```bash
pnpm check && ./scripts/test-python.sh
```

两者都必须全绿。**不要在报告里说"应该没问题"——贴真实输出。**

需要长期跑的慢测试（仿真器怀疑者、模糊测试、bug 回注）单独跑：

```bash
(cd packages/sim && ../../.venv/bin/python -m pytest -q -m slow)
(cd packages/agent && ../../.venv/bin/python -m pytest -q -m slow)
```

CI 里它们是独立的 job（`python-slow`）。

---

## 3. 提交规范

- **Conventional Commits**：`feat:`、`fix:`、`docs:`、`chore:`、`test:`、`perf:`。一次提交只做一件事。
- **不擅自加依赖**。确需新增，在提交信息里写明理由。
- **代码风格**：Biome，**tab 缩进、双引号**、严格 TypeScript。Python 用类型注解，模块顶部写一句说明这个模块干什么的 docstring。
- **`packages/core` 必须保持纯净**：无 DOM、无 Node 专属 API，任何随机性都走**带种子的 RNG 参数**，不许直接调 `Math.random()`。博客（meiluosi.github.io）要能直接 import 它。
- **每个新函数都要有测试**（`foo.ts` → `foo.test.ts`）。测**不变量**（连杆长度守恒、镜像对称、装配可行），别测魔数。

---

## 4. 本项目的诚实规则（不要绕过）

这几条是项目的底线，评审时会看：

1. **猜的物理参数必须有名有姓。** 放进 schema 的具名字段，默认值标 `assumption`，并在 `docs/RESEARCH-NOTES.md` 记出处。没验证的写 `[unverified]`，**不要当成事实写进文章**。
2. **历史或数值主张要有出处。** 关于 Jansen 本人的说法（尺寸、"神圣数字"、约 15 km/h）必须能追到来源；没有就标 `[unverified]`。
3. **发现旧结果错了要回头更正，并留痕。** 在 `docs/EXPERIMENTS.md` 里写清楚：错在哪、什么时候改的、哪些结论受影响。
4. **区分"核对"与"验证"。** "核对"是代码正确实现了我们写下的模型（可以和别的求解器、文献方程对比）；"验证"是模型符合真实世界（需要实测）。**文档里不许把核对说成验证。**
5. **否定性与边界结果要报告，并带数字。** "走不动"也是结果。
6. **测试台的结果不进排行榜。** 电机驱动是仪器（`test_rig`），风驱动才是产品（`wind`）。

---

## 5. 加一个扩展（地形、风、驱动、指标）

四个注册表都在 [`packages/sim/src/strandbeest_sim/registry.py`](packages/sim/src/strandbeest_sim/registry.py) 里。

**最短路径**：跟着 [`docs/EXTENDING.md`](docs/EXTENDING.md) 走一遍，那份文档以"加一个地形插件"为例，把要碰的每个文件、每条命令、每个坑都写清楚了，并且**保证你能跑通测试**。

几条容易踩的：

- 注册表是**运行时唯一真相来源**。场景文件里写字符串名（`"flat"`、`"slope"`…），不是函数。
- **浏览器侧是另一份实现**：`packages/sim-web/src/terrains.ts` 里有一个平行的 `switch`。新增地形如果不在两边都加，浏览器里就会缺。
- **双实现必须进契约语料库**：见 [`contracts/duplicated-modules.json`](contracts/duplicated-modules.json)。MJCF 的字节级一致性由 `contracts/sim-mjcf/` 保证。
- **改了 schema 要重新生成**：`gen_models.py` 和 `gen_reference_docs.py`，然后跑 `--check` 确认同步。

---

## 6. 三种贡献

我们用三个 Issue 模板区分，因为它们的评审标准完全不同：

### 6.1 设计请求（Design request）

"我想看某种连杆几何能不能走"。

- 用 `packages/core` 的演化工具搜，或直接给一份设计文档（`schemas/examples/` 里有范例）。
- 设计必须**装得起来**（全周期可装配、无分支翻转）。`packages/core/src/ops.ts` 的守门会检查。
- 提交时说明你**测过什么**（步幅？起步风速？）。

### 6.2 模型缺陷（Model defect）

"仿真器在某个条件下给出我信不过的结果"。

这是我们**最想要**的一类。请给出：

- 复现用的**完整场景**（设计 + 场景覆盖）；
- 你看到的数字和我们模型预期的数字；
- 你判断哪里不对，以及为什么。

模型缺陷的记录方式见 [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md) §9（更正记录）和 §20（环约束张开）。复现用例请加进 `contracts/` 下的对应语料库。

### 6.3 数据贡献（Data contribution）

"我有一只真的走兽，测了点东西"。

- 先读 [`docs/HOW-TO-MEASURE.md`](docs/HOW-TO-MEASURE.md)：能测什么、怎么测、误差怎么估、提交成什么格式。
- 提交用 `packages/calib` 的校验器（`scripts/validate_community_measurement.py`）先自查。
- 你的数据能升到 **E3**，前提是**可追溯**：仪器、校准、日期、单位、原始数据、不确定度。缺了这些就只能算"一个数字"，不能算证据。

---

## 7. 数据与设计的许可证

代码是 **MIT**（见 [`LICENSE`](LICENSE)）。**设计与实测数据的许可证尚未定案**——提案与取舍写在 [`docs/LICENSING.md`](docs/LICENSING.md)，等仓库所有者拍板。

在你提交设计或数据之前，请先看那份文件：它决定了"你交出来的东西，之后别人能怎么用"。如果上面写着"待定"，请在 Issue 里先问一句，别默认。

---

## 8. 什么时候需要找维护者

- 要**对外发布**（npm、GitHub Pages、博客、印刷导出）：一律先问。项目规则是**未经确认不对外发布**。
- 要动 **ADR**（`docs/adr/`）里已经接受的决定：先开 Issue 讨论，别直接改。
- 要新增**第三方依赖**：先开 Issue 说理由。

---

<a name="english--contributing"></a>
# English — Contributing

> [中文](#0-这个项目在做什么先看这个)

This project is a **Strandbeest (Jansen linkage) simulation platform**: linkage geometry, kinematics, dynamics, wind-driven simulation, evolutionary optimisation, and an interactive demo.

The product direction is in [`docs/WIND.md`](docs/WIND.md): **the walkers in our product conclusions are driven by wind alone** (a motor is a test rig only), and every number carries an **evidence level** E0–E3 (see [`docs/VALIDATION.md`](docs/VALIDATION.md)).

Two consequences:

1. **"It runs" is not "it is right".** Most of our results are **E0 (one model only)**. Calling something validated needs two independent solvers agreeing (E1) or agreement with public data (E2); only measurements reach E3.
2. **Negative results are results.** "It does not walk", "the torque depends on the friction model", "this design wins under one solver and loses under another" — all of it goes into [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md), **with numbers**.

## Setup

```bash
pnpm install                 # Node >= 22
./scripts/setup-python.sh    # Python 3.10+ (into .venv/)
```

## Before you commit

```bash
pnpm check && ./scripts/test-python.sh
```

Both must be green, and **report the real output** — never "it should be fine".

`./scripts/test-python.sh` also runs repository-level checks that catch most low-level mistakes: hard-coded CJK in UI code, schema fields missing `x-unit`, generated models out of sync with the schema, reference docs out of sync, the ADR-0009 duplicated-module trigger, and **documentation references that do not exist** (`check_doc_refs.py`).

Slow tests (the simulator skeptic, fuzzing, bug injection) run separately in CI:

```bash
(cd packages/sim && ../../.venv/bin/python -m pytest -q -m slow)
(cd packages/agent && ../../.venv/bin/python -m pytest -q -m slow)
```

## Commit conventions

- **Conventional Commits**: `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `perf:`. One concern per commit.
- **No new dependencies without a reason** stated in the commit message.
- **Biome**: tabs, double quotes, strict TypeScript. Python: type hints, a module docstring saying what the module is for.
- **`packages/core` stays pure**: no DOM, no Node-only APIs, all randomness through a **seeded RNG argument** — never `Math.random()` directly. The blog imports it directly.
- **Every new function gets a test** (`foo.ts` → `foo.test.ts`). Test **invariants** (link lengths preserved, mirror symmetry, assemblability), not magic numbers.

## The honesty rules (do not bypass them)

1. **A guessed physical parameter must have a name.** It goes in the schema as a named field with an `assumption` default and a source in `docs/RESEARCH-NOTES.md`. Unverified claims are marked `[unverified]` and **never stated as fact in an article**.
2. **Historical and numerical claims need a source.** Anything about Jansen himself (dimensions, the "holy numbers", the ~15 km/h) must be traceable, or marked unverified.
3. **If an old result turns out to be wrong, go back and correct it, and leave a trail** in `docs/EXPERIMENTS.md`: what was wrong, when it was fixed, which conclusions changed.
4. **Verification vs validation.** *Verification* is "the code implements the model we wrote" (comparable against another solver or a published equation). *Validation* is "the model matches the real world" (needs measurement). **The docs must never call verification validation.**
5. **Report negative and limiting results, with numbers.** "It does not walk" is a result.
6. **Test-rig results never enter the leaderboard.** Motor drive is an instrument (`test_rig`); wind drive is the product (`wind`).

## Adding an extension (terrain, wind, drive, metric)

The four registries live in [`packages/sim/src/strandbeest_sim/registry.py`](packages/sim/src/strandbeest_sim/registry.py).

**Fastest path**: follow [`docs/EXTENDING.md`](docs/EXTENDING.md). It walks through adding a terrain plugin, naming every file to touch, every command to run, and every trap — and it is written so that **you end up with passing tests**.

Common traps:

- The registry is the **single runtime source of truth**; scenarios refer to extensions by name string.
- **The browser is a second implementation**: `packages/sim-web/src/terrains.ts` has a parallel `switch`. A terrain missing on one side is simply absent in the browser.
- **Duplicated modules need a contract corpus** — see [`contracts/duplicated-modules.json`](contracts/duplicated-modules.json). MJCF byte-level parity is enforced by `contracts/sim-mjcf/`.
- **Changed the schema? Regenerate**: `gen_models.py` and `gen_reference_docs.py`, then run with `--check`.

## The three kinds of contribution

### Design request

"I want to know whether this linkage geometry walks." Use the evolutionary tooling in `packages/core`, or send a design document (`schemas/examples/` has examples). The design must assemble over the whole crank cycle. Say **what you measured** (stride? start wind?).

### Model defect

"I do not trust what the simulator produced here." This is the **most valuable** kind of report. Please give the **complete scenario** (design + scenario overrides), the numbers you saw, the numbers you expected, and why you think the model is wrong.

Model corrections are recorded in [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md) §9 (corrections) and §20 (loop opening). Please add your reproduction case to the matching corpus under `contracts/`.

### Data contribution

"I have a real walker and measured something." Read [`docs/HOW-TO-MEASURE.md`](docs/HOW-TO-MEASURE.md) first: what can be measured, how, with what error, and in what format to submit. Validate your file with `scripts/validate_community_measurement.py` before submitting. Your data can reach **E3** provided it is **traceable**: instrument, calibration, date, units, raw data, uncertainty. Without those it is "a number", not evidence.

## When to ask the maintainer first

- **Publishing externally** (npm, GitHub Pages, the blog, print exports): always ask. The project rule is **no external publishing without confirmation**.
- Changing an **accepted ADR** in `docs/adr/`: open an issue first.
- Adding a **third-party dependency**: open an issue with the reason.

## Licensing

The code is **MIT** (see [`LICENSE`](LICENSE)). **The licence for designs and measured data is not decided yet** — the proposal and its trade-offs are in [`docs/LICENSING.md`](docs/LICENSING.md), pending the repository owner's decision. Please read it before submitting a design or data: it decides what happens to what you hand over. If it still says "pending", ask in the issue rather than assuming.
