import {
	cycleSummary,
	DEFAULT_SAIL,
	DEFAULT_WALKER,
	FLAT,
	type Sail,
	type Terrain,
	type Walker,
	windWalk,
} from "./dynamics";
import {
	type Fitness,
	genomeToParams,
	INFEASIBLE,
	infeasibility,
	legMetrics,
} from "./fitness";
import { jansenSpec } from "./jansen";

export interface WindObjective {
	wind: number;
	walker?: Walker;
	terrain?: Terrain;
	sail?: Sail;
	/** reject legs that are stable for less than this fraction of the cycle */
	minStable?: number;
}

/**
 * Fitness from the quasi-static wind model: steady body speed (m/s) in `wind`.
 * A leg must first be a sensible walking leg (assembles, flat stroke with a swing phase, stable support).
 * If the peak crank torque exceeds what the sail gives at standstill, the leg cannot start and is penalised
 * in proportion to how far the wind is below its start wind.
 *
 * Trade-off this captures: a longer stride goes further per crank turn but raises the mean load
 * (drag × stride), so there is an interior optimum for a given sail and wind.
 * All sail / mass / drag values are illustrative assumptions (see dynamics.ts).
 */
export function fitnessWindSpeed(obj: WindObjective): Fitness {
	const walker = obj.walker ?? DEFAULT_WALKER;
	const terrain = obj.terrain ?? FLAT;
	const sail = obj.sail ?? DEFAULT_SAIL;
	const minStable = obj.minStable ?? 0.9;
	return (genome) => {
		const m = legMetrics(genome);
		if (!m) return infeasibility(genome) as number;
		// same walking constraints as the kinematic objectives, as graded penalties below INFEASIBLE-free range
		if (m.lift / m.width < 0.15) return m.lift / m.width - 1;
		if (m.duty < 0.35) return m.duty - 0.35 - 1;
		const s = cycleSummary(
			jansenSpec(genomeToParams(genome)),
			walker,
			terrain,
			90,
		);
		if (!s) return INFEASIBLE - 1;
		if (s.stableFraction < minStable) return s.stableFraction - minStable - 1;
		const r = windWalk(sail, s, obj.wind);
		if (obj.wind < r.minStartWind)
			return -(r.minStartWind - obj.wind) / r.minStartWind - 1;
		return r.speed;
	};
}
