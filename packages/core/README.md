# strandbeest-core

Kinematics and evolutionary optimization for Theo Jansen's Strandbeest leg (Jansen linkage). Pure TypeScript, no DOM, runs in the browser and Node.

```ts
import { jansenSpec, trace, gaitMetrics, runGA, fitnessFlatStroke, paramsToGenome, JANSEN_LENGTHS } from "strandbeest-core";

const path = trace(jansenSpec(), 180);            // foot trajectory over one crank revolution
console.log(gaitMetrics(path.foot));              // { width, lift, strokeLength, duty }

const result = runGA(paramsToGenome(JANSEN_LENGTHS), fitnessFlatStroke, { seed: 1, generations: 80 });
```

Randomness is always seeded, so results are reproducible. See the [project repository](https://github.com/meiluosi/strandbeest-evolution) for the demo, experiments and roadmap. MIT licensed.

The application installs the Rust/WASM kinematics kernel explicitly. The standalone
TypeScript reference remains available for geometry/GA use and independent checks.
The experimental `strideReference(spec, options)` capability requires that Rust
kernel; it reports an error if the active kernel does not provide it. It takes the
actual sphere-owning bar, leg phases, direction, length scale, radius and numerical
resolution as explicit inputs. It preserves signed, tiny and zero stride values
and reports nonassembly, incompatible supports and unresolved angular sampling.
It assumes a rigid, flat, nonrotating, no-slip walker; it is not a dynamic
prediction or a replacement for the simulation audit. Compare resolutions.

应用显式加载 Rust/WASM 内核。实验性的 `strideReference` 是带方向的理想几何诊断，
没有 TypeScript 数值回退；输入必须来自实际场景和足端所属杆。它不模拟柔性接触、
腾空或滑移，不能把双端一致或采样收敛当作实物验证。正式审计仍保留原参考及门槛。
