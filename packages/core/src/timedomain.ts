import {
	quasiStaticSample,
	type Sail,
	sailTorque,
	type Terrain,
	type Walker,
} from "./dynamics";
import type { LinkageSpec } from "./linkage";

/**
 * Time-domain walking with inertia: a one-degree-of-freedom model driven by the sail.
 *
 * The crank angle ψ is the only coordinate (the leg is a 1-DOF linkage and stance feet do not slip), so the body's
 * kinetic energy is carried by the crank through the kinematics:
 *     T = ½ J_eff(ψ) ω²,    J_eff(ψ) = J + m [ (dX/dψ)² + (dH/dψ)² ]
 * with J the crank-referred rotor/sail inertia. Energy balance per radian of crank rotation:
 *     dT/dψ = τ_sail(ω) − τ_load(ψ) − friction − damping·ω.
 * where τ_load comes from the quasi-static model (slope, drag, body lift).
 *
 * Assumptions: massless legs, no slip, and **no impact loss** when the set of feet in contact changes
 * (kinetic energy, not momentum, is carried across those switches, so J_eff can jump while ω adjusts).
 * Sail size, gearing, inertia and drag are illustrative values.
 */
export interface TimeOptions {
	/** crank-referred rotor + sail inertia in kg·m² */
	inertia: number;
	/** crank revolutions to simulate */
	cycles: number;
	/** initial crank speed, rad/s (0 = from rest; a tiny seed speed is used internally) */
	omega0: number;
	/** table resolution per revolution */
	samples: number;
}

export const DEFAULT_TIME: TimeOptions = {
	inertia: 2,
	cycles: 20,
	omega0: 0,
	samples: 720,
};

export interface TimeResult {
	/** the crank got stuck (net torque ≤ 0 with no kinetic energy left) */
	stalled: boolean;
	/** crank angle at which it stalled, rad (only if stalled) */
	stalledAt: number | null;
	/** revolutions completed */
	revolutions: number;
	/** elapsed simulated time, s */
	time: number;
	/** series sampled every table step: [t, psi, omega, bodySpeed] */
	series: { t: number; psi: number; omega: number; speed: number }[];
	/** mean body speed over the last completed revolution, m/s (0 if none) */
	meanSpeed: number;
	/** min and max body speed over the last completed revolution */
	speedRange: [number, number];
}

interface Table {
	n: number;
	tau: number[];
	dX: number[];
	dH: number[];
}

function buildTable(
	spec: LinkageSpec,
	walker: Walker,
	terrain: Terrain,
	n: number,
): Table | null {
	const tau: number[] = [];
	const dX: number[] = [];
	const dH: number[] = [];
	for (let i = 0; i < n; i++) {
		// ψ is rotation in the walking direction; the spec's own angle is θ = direction·ψ
		const s = quasiStaticSample(
			spec,
			walker,
			terrain,
			walker.direction * ((2 * Math.PI * i) / n),
		);
		if (!s) return null;
		tau.push(s.torque);
		dX.push(s.dXdPsi);
		dH.push(s.dHdPsi);
	}
	return { n, tau, dX, dH };
}

export function simulateWalk(
	spec: LinkageSpec,
	walker: Walker,
	terrain: Terrain,
	sail: Sail,
	/** wind speed in m/s, constant or a function of simulated time (for gusts and lulls) */
	wind: number | ((t: number) => number),
	opts: Partial<TimeOptions> = {},
): TimeResult | null {
	const o = { ...DEFAULT_TIME, ...opts };
	const tab = buildTable(spec, walker, terrain, o.samples);
	if (!tab) return null;
	const h = (2 * Math.PI) / tab.n;
	const dXi = (i: number) => tab.dX[i] as number;
	const dHi = (i: number) => tab.dH[i] as number;
	const tau = (i: number) => tab.tau[i] as number;
	const Jeff = (i: number) =>
		o.inertia + walker.mass * (dXi(i) ** 2 + dHi(i) ** 2);

	// kinetic energy; ω follows from it. A tiny seed energy lets a stationary crank start without dividing by zero.
	let T = Math.max(0.5 * Jeff(0) * o.omega0 ** 2, 1e-9);
	const series: TimeResult["series"] = [];
	let t = 0;
	const total = o.cycles * tab.n;
	const omegaOf = (T: number, i: number) => Math.sqrt((2 * T) / Jeff(i));

	for (let k = 0; k < total; k++) {
		const i = k % tab.n;
		const omega = omegaOf(T, i);
		const speed = dXi(i) * omega;
		series.push({ t, psi: k * h, omega, speed });
		const net = (w: number) =>
			sailTorque(sail, typeof wind === "number" ? wind : wind(t), w) -
			tau(i) -
			sail.friction -
			sail.damping * w;
		// Midpoint steps in ψ, subdivided so one step never changes T by more than ~10 %: starting from rest the sail torque
		// is huge compared with the tiny kinetic energy, and a single big step overshoots and stalls spuriously.
		let remaining = h;
		let guard = 0;
		while (remaining > 1e-12 && guard++ < 20000) {
			const w0 = omegaOf(T, i);
			const n0 = net(w0);
			const dpsi = Math.min(
				remaining,
				(0.1 * Math.max(T, 1e-4)) / Math.max(Math.abs(n0), 1e-9),
			);
			const Tm = Math.max(T + 0.5 * dpsi * n0, 1e-12);
			const wm = omegaOf(Tm, i);
			const Tn = T + dpsi * net(wm);
			if (Tn <= 0) {
				// no kinetic energy left: stuck if the standstill torque cannot push through here
				if (net(0) <= 0) {
					return {
						stalled: true,
						stalledAt: k * h + (h - remaining),
						revolutions: k / tab.n,
						time: t,
						series,
						meanSpeed: 0,
						speedRange: [0, 0],
					};
				}
				T = 1e-9;
			} else T = Tn;
			t += dpsi / Math.max(wm, 1e-3);
			remaining -= dpsi;
		}
	}

	const last = series.slice(-tab.n);
	const speeds = last.map((s) => s.speed);
	return {
		stalled: false,
		stalledAt: null,
		revolutions: o.cycles,
		time: t,
		series,
		meanSpeed: speeds.reduce((s, v) => s + v, 0) / speeds.length,
		speedRange: [Math.min(...speeds), Math.max(...speeds)],
	};
}
