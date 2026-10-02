# strandbeest-core

Kinematics and evolutionary optimization for Theo Jansen's Strandbeest leg (Jansen linkage). Pure TypeScript, no DOM, runs in the browser and Node.

```ts
import { jansenSpec, trace, gaitMetrics, runGA, fitnessFlatStroke, paramsToGenome, JANSEN_LENGTHS } from "strandbeest-core";

const path = trace(jansenSpec(), 180);            // foot trajectory over one crank revolution
console.log(gaitMetrics(path.foot));              // { width, lift, strokeLength, duty }

const result = runGA(paramsToGenome(JANSEN_LENGTHS), fitnessFlatStroke, { seed: 1, generations: 80 });
```

Randomness is always seeded, so results are reproducible. See the [project repository](https://github.com/meiluosi/strandbeest-evolution) for the demo, experiments and roadmap. MIT licensed.
