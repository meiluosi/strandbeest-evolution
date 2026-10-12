/** Port of strandbeest_sim.winds: wind speed at the sail (m/s) as a function of time since the start of driving. */
import type { SimConfig } from "./config";

export type WindFn = (t: number) => number;

export function makeWind(w: SimConfig["wind"]): WindFn {
	switch (w.kind) {
		case "constant":
			return () => w.speed;
		case "gusts": {
			// mean speed plus a sinusoidal gust, never negative
			const amp = Number(w.params.amplitude ?? 1.0);
			const period = Number(w.params.period ?? 6.0);
			return (t) =>
				Math.max(0.0, w.speed + amp * Math.sin((2 * Math.PI * t) / period));
		}
		case "lull": {
			// steady wind that drops to zero at `at` seconds
			const at = Number(w.params.at ?? 10.0);
			return (t) => (t < at ? w.speed : 0.0);
		}
		default:
			throw new Error(`unknown wind '${w.kind}'`);
	}
}
