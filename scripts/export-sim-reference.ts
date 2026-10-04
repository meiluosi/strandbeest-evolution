// Export the Jansen spec and the reduced-order (quasi-static) reference curves for cross-checking the MuJoCo simulator.
// Usage: pnpm sim:reference
import { writeFileSync } from "node:fs";
import { DEFAULT_WALKER, FLAT, jansenSpec, quasiStaticSample } from "../packages/core/src";

const spec = jansenSpec();
const walker = { ...DEFAULT_WALKER, mass: 50, legs: 12 };
const n = 720;
const samples = Array.from({ length: n }, (_, i) => {
	const psi = (2 * Math.PI * i) / n;
	// psi is rotation in the walking direction; the spec's own angle is theta = direction * psi
	const s = quasiStaticSample(spec, walker, FLAT, walker.direction * psi);
	return { psi, torque: s?.torque ?? null, dXdPsi: s?.dXdPsi ?? null, dHdPsi: s?.dHdPsi ?? null };
});
const stride = samples.reduce((a, s) => a + (s.dXdPsi ?? 0) * ((2 * Math.PI) / n), 0);
writeFileSync("packages/sim/tests/data/jansen-spec.json", `${JSON.stringify(spec, null, 2)}\n`);
writeFileSync(
	"packages/sim/tests/data/reference-flat.json",
	`${JSON.stringify({ walker, terrain: FLAT, stride, samples }, null, 2)}\n`,
);
console.log("stride per revolution (m):", stride.toFixed(4));
