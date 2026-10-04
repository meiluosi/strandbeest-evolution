# strandbeest-evolution

对 Theo Jansen 的 Strandbeest（风力动力兽）腿部连杆机构的研究项目：运动学、遗传算法演化、准静态动力学（风力驱动估算）、交互式演示，以及配套的科普文章。

*Kinematics, evolutionary optimization, quasi-static wind-driven dynamics and interactive demos for Theo Jansen's Strandbeest leg.* — [English README](README.en.md)

![Jansen 连杆的脚轨迹 / foot path of the Jansen linkage](docs/assets/jansen-leg.gif)
![多条腿相位错开行走（示意）/ multi-leg walking (schematic)](docs/assets/walker.gif)

平台设计与阶段计划见 [docs/PLATFORM.md](docs/PLATFORM.md)。

## 里面有什么

| 目录 | 内容 |
|---|---|
| `packages/core` | 纯 TypeScript 库（npm: `strandbeest-core`）：连杆求解、步态指标、带种子的遗传算法、多腿、准静态动力学与风帆模型 |
| `packages/sim` | Python / MuJoCo 动力学仿真器（配置驱动，见 [设计](docs/SIM-DESIGN.md)）；早期，扭矩结果尚未收敛 |
| `apps/web-demo` | 交互演示：拖动 13 个长度看脚轨迹；浏览器里跑遗传算法；风力估算面板 |
| `scripts/` | 实验脚本（演化、复现 Jansen、动力学对比）与 GIF 渲染 |
| `docs/` | 路线图、架构、研究笔记（史料出处）、实验记录 |

## 运行

全链路（Python 部分）：

```bash
./scripts/setup-python.sh && source .venv/bin/activate
strandbeest-pipeline run schemas/examples/design-jansen-small-6leg.json out/   # 评估 → 打印包 → 仿真
strandbeest-api                                                                 # 后端，配合下面的网页演示
```


```bash
pnpm install
pnpm check                                   # 格式检查 + 类型检查 + 测试
pnpm --filter @strandbeest/web-demo dev      # 本地打开交互演示
pnpm experiment flat 1 80                    # 演化实验
pnpm dynamics                                # 动力学对比
```

## 诚实声明

- Jansen 的 13 个长度与连杆拓扑来源见 [研究笔记](docs/RESEARCH-NOTES.md)；演化时期已对照 strandbeest.com 各时期页面核实（Pregluton 除外）。
- 动力学是**准静态**模型（无惯性、无滑移、无松软地面），帆、传动比、阻力为示意假设，只适合比较设计，不是实测预测。
- 我们的遗传算法是对"演化出腿长"这一思路的重构，并不是 Jansen 实际使用的方法。

欢迎 issue 和 PR。开发约定见 [AGENTS.md](AGENTS.md)。MIT 许可。
