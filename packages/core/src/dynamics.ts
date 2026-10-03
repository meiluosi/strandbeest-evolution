import type { Point } from "./geometry";
import { type LinkageSpec, solvePose } from "./linkage";
import { evenPhases } from "./multileg";

/**
 * Quasi-static walking model for one Jansen leg design with several legs on a shared crankshaft.
 *
 * What it models: a rigid body of `mass` riding on massless legs whose stance feet do not slip, on ground with
 * a slope and a constant drag force. The crank torque follows from energy conservation (virtual work):
 *     τ(ψ) = (m g sinα + D) · dX/dψ  +  m g cosα · dH/dψ
 * with X the body's forward position, H its height above the lowest foot, ψ the crank rotation.
 *
 * What it does NOT model: leg/crank inertia, foot slip, soft ground (sand sinking), joint friction beyond a viscous
 * term, lateral dynamics. Treat results as first-order estimates for comparing designs, not predictions.
 */
export interface Walker {
	/** legs on the shared crank, evenly phased (planar projection) */
	legs: number;
	/** total mass in kg */
	mass: number;
	/** metres per length unit of the linkage spec (Jansen's numbers have no stated unit; this is an assumption) */
	unit: number;
	/** +1 if the crank turns the way θ increases, -1 otherwise. For the standard Jansen leg, -1 walks forward (+x). */
	direction: 1 | -1;
}

export interface Terrain {
	/** ground slope in radians, positive = uphill in the walking direction */
	slope: number;
	/** constant resisting force on the body, in newtons (e.g. rolling resistance, headwind) */
	drag: number;
}

export const G = 9.81;

export const DEFAULT_WALKER: Walker = {
	legs: 12,
	mass: 50,
	unit: 0.02,
	direction: -1,
};
export const FLAT: Terrain = { slope: 0, drag: 0 };

interface Sample {
	/** crank torque in N·m per unit crank rotation, positive = the crank must be driven */
	torque: number;
	/** body forward distance per radian of crank rotation, metres */
	dXdPsi: number;
	/** body height change per radian of crank rotation, metres */
	dHdPsi: number;
	/** number of legs in ground contact */
	contacts: number;
	/** hip is between the rearmost and foremost contact feet (no tipping) */
	stable: boolean;
	/** spread of the contact feet's ground speeds (units per radian): 0 = no slip needed */
	slipSpread: number;
}

function feetAt(
	spec: LinkageSpec,
	theta: number,
	phases: number[],
): Point[] | null {
	const out: Point[] = [];
	for (const ph of phases) {
		const pose = solvePose(spec, theta + ph);
		const f = pose?.[spec.foot];
		if (!f) return null;
		out.push(f);
	}
	return out;
}

/** Evaluate the walker at crank angle `theta` (radians, in the spec's own angle convention). */
export function quasiStaticSample(
	spec: LinkageSpec,
	walker: Walker,
	terrain: Terrain,
	theta: number,
	contactTol = 1.0,
): Sample | null {
	const phases = evenPhases(walker.legs).map((l) => l.phase);
	const h = 1e-4;
	const f0 = feetAt(spec, theta, phases);
	const fp = feetAt(spec, theta + h, phases);
	const fm = feetAt(spec, theta - h, phases);
	if (!f0 || !fp || !fm) return null;

	const lowest = Math.min(...f0.map((p) => p.y));
	const contact = f0.map((p) => p.y <= lowest + contactTol);
	const idx = contact.flatMap((c, i) => (c ? [i] : []));

	// body forward speed per radian = minus the contact feet's speed in the body frame
	const dfx = (i: number) =>
		((fp[i] as Point).x - (fm[i] as Point).x) / (2 * h);
	const groundSpeed = idx.map((i) => -walker.direction * dfx(i));
	const dXunits = groundSpeed.reduce((s, v) => s + v, 0) / groundSpeed.length;

	// height of the hip above the ground = -(lowest foot y); its rate follows the lowest foot
	const lowestOf = (feet: Point[]) => Math.min(...feet.map((p) => p.y));
	const dHunits =
		-walker.direction * -((lowestOf(fp) - lowestOf(fm)) / (2 * h));

	const dX = dXunits * walker.unit;
	const dH = dHunits * walker.unit;
	const W = walker.mass * G;
	const torque =
		(W * Math.sin(terrain.slope) + terrain.drag) * dX +
		W * Math.cos(terrain.slope) * dH;

	const xs = idx.map((i) => (f0[i] as Point).x);
	const stable =
		idx.length >= 2 && Math.min(...xs) <= 0 && Math.max(...xs) >= 0;
	const slipSpread =
		groundSpeed.length > 1
			? Math.max(...groundSpeed) - Math.min(...groundSpeed)
			: 0;
	return {
		torque,
		dXdPsi: dX,
		dHdPsi: dH,
		contacts: idx.length,
		stable,
		slipSpread,
	};
}

export interface CycleSummary {
	/** metres advanced per crank revolution */
	stride: number;
	/** mean crank torque over a revolution (N·m): work / 2π */
	meanTorque: number;
	/** largest positive torque (N·m): what the wind must beat to start */
	peakTorque: number;
	/** most negative torque (N·m): the load pushes the crank; needs friction or a brake to hold */
	minTorque: number;
	/** fraction of the cycle with a stable (non-tipping) support */
	stableFraction: number;
	/** worst-case slip spread among contact feet, in length units per radian */
	maxSlipSpread: number;
	samples: Sample[];
}

export function cycleSummary(
	spec: LinkageSpec,
	walker: Walker,
	terrain: Terrain,
	samples = 240,
): CycleSummary | null {
	const out: Sample[] = [];
	for (let i = 0; i < samples; i++) {
		const s = quasiStaticSample(
			spec,
			walker,
			terrain,
			(2 * Math.PI * i) / samples,
		);
		if (!s) return null;
		out.push(s);
	}
	const dpsi = (2 * Math.PI) / samples;
	const taus = out.map((s) => s.torque);
	return {
		stride: out.reduce((s, v) => s + v.dXdPsi * dpsi, 0),
		meanTorque: taus.reduce((s, v) => s + v, 0) / samples,
		peakTorque: Math.max(...taus),
		minTorque: Math.min(...taus),
		stableFraction: out.filter((s) => s.stable).length / samples,
		maxSlipSpread: Math.max(...out.map((s) => s.slipSpread)),
		samples: out,
	};
}

// ---------------------------------------------------------------- wind

/** Drag-type sail of `area` m² at radius `radius` m, geared down by `gear` to the crank. */
export interface Sail {
	area: number;
	radius: number;
	dragCoeff: number;
	/** sail turns `gear` times per crank turn (ideal, lossless reduction) */
	gear: number;
	/** viscous loss at the crank: N·m per rad/s */
	damping: number;
	/** constant (Coulomb) friction at the crank, N·m */
	friction: number;
}

export const AIR_DENSITY = 1.2;

/** Illustrative values only; real Strandbeest sail sizes and gearing are not modelled from documentation. */
export const DEFAULT_SAIL: Sail = {
	area: 4,
	radius: 0.5,
	dragCoeff: 1.2,
	gear: 20,
	damping: 0.5,
	friction: 0.5,
};

/** Torque (N·m) delivered at the crank at crank speed `omega` (rad/s) in wind `wind` (m/s). */
export function sailTorque(sail: Sail, wind: number, omega: number): number {
	const rel = wind - omega * sail.gear * sail.radius;
	if (rel <= 0) return 0;
	return (
		sail.gear *
		0.5 *
		AIR_DENSITY *
		sail.dragCoeff *
		sail.area *
		sail.radius *
		rel *
		rel
	);
}

/** Smallest wind speed (m/s) whose standstill torque beats the peak crank torque plus Coulomb friction. */
export function minStartWind(sail: Sail, peakTorque: number): number {
	const need = Math.max(peakTorque, 0) + sail.friction;
	return Math.sqrt(
		(2 * need) /
			(sail.gear * AIR_DENSITY * sail.dragCoeff * sail.area * sail.radius),
	);
}

/**
 * Steady crank speed (rad/s): sail torque = mean load + Coulomb friction + damping·ω.
 * Returns 0 if the sail cannot supply that load at standstill.
 */
export function steadyOmega(
	sail: Sail,
	wind: number,
	meanTorque: number,
): number {
	const load = Math.max(meanTorque, 0) + sail.friction;
	if (sailTorque(sail, wind, 0) <= load) return 0;
	let lo = 0;
	let hi = wind / (sail.gear * sail.radius);
	for (let i = 0; i < 80; i++) {
		const mid = (lo + hi) / 2;
		if (sailTorque(sail, wind, mid) > load + sail.damping * mid) lo = mid;
		else hi = mid;
	}
	return (lo + hi) / 2;
}

export interface WindResult {
	/** wind speed that can start the walker from rest, m/s */
	minStartWind: number;
	/** can the sail supply the average torque at this wind? */
	runs: boolean;
	/** crank speed, rad/s */
	omega: number;
	/** body speed in m/s */
	speed: number;
}

/**
 * Wind-driven walking estimate. Starting uses the peak torque; once moving, the average torque.
 * No inertia is modelled, so there is no flywheel smoothing: optimistic about peaks, and a real walker
 * needs the wind to exceed the start threshold at least until it is moving.
 */
export function windWalk(
	sail: Sail,
	summary: CycleSummary,
	wind: number,
): WindResult {
	const omega = steadyOmega(sail, wind, summary.meanTorque);
	return {
		minStartWind: minStartWind(sail, summary.peakTorque),
		runs: omega > 0,
		omega,
		speed: omega * (summary.stride / (2 * Math.PI)),
	};
}
