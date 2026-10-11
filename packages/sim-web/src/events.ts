/** Port of strandbeest_sim.events (events and automatic diagnosis of a finished run) and of the `energy` metric of
 *  metrics_builtin. Works on the recorded series only, like the Python module; contracts/sim-events holds Python's answers for
 *  synthetic runs that fire every rule, and contracts/sim-run for real runs. */
import { gaitMetrics, type LinkageSpec, trace } from "strandbeest-core";
import type { SimConfig } from "./config";
import { fmtG, pyFixed, pyPercent0 } from "./pyfmt";

export const SLIP_SPEED = 0.02;
export const SLIP_MIN_SAMPLES = 3;
export const TORQUE_LIMIT_FRACTION = 0.98;
export const TORQUE_LIMIT_MIN_S = 0.006;
export const WEAK_SAIL_RATIO = 0.15;
export const LOOP_OPEN_M = 0.005;

export interface RunEvent {
	t: number;
	kind: string;
	leg?: number;
	detail?: Record<string, number>;
}
export interface Diagnosis {
	code: string;
	severity: "info" | "warning" | "error";
	message: string;
	evidence: Record<string, number | string | null>;
}
/** What the Python `Result` carries and the rules read. Series are per recorded sample; foot series are [sample][leg]. */
export interface RunResult {
	t: number[];
	psi: number[];
	x: number[];
	torque: number[];
	stalled: boolean;
	metrics: Record<string, number | boolean | null>;
	series: {
		foot_normal?: number[][];
		foot_slip?: number[][];
		loop_residual?: number[];
	} & Record<string, unknown>;
}

/** [start, end] index pairs of the true runs, at least `minLen` long */
function runs(mask: boolean[], minLen = 1): [number, number][] {
	const out: [number, number][] = [];
	let i = 0;
	while (i < mask.length) {
		if (mask[i]) {
			let j = i;
			while (j + 1 < mask.length && mask[j + 1]) j++;
			if (j - i + 1 >= minLen) out.push([i, j]);
			i = j + 1;
		} else i++;
	}
	return out;
}

const col = (m: number[][], k: number) => m.map((r) => r[k] as number);

export function detectEvents(res: RunResult, sc: SimConfig): RunEvent[] {
	const t = res.t;
	const ev: RunEvent[] = [];
	const s = res.series;
	if (t.length === 0) return ev;

	const movingAt = res.psi.findIndex((p) => p > 0.05);
	if (movingAt >= 0) ev.push({ t: t[movingAt] as number, kind: "start" });
	if (res.stalled)
		ev.push({
			t: t.at(-1) as number,
			kind: "stall",
			detail: { crank_rotation_rad: res.psi.at(-1) as number },
		});

	if (s.foot_normal && s.foot_slip) {
		const legs = (s.foot_normal[0] ?? []).length;
		for (let leg = 0; leg < legs; leg++) {
			const normal = col(s.foot_normal, leg);
			const slip = col(s.foot_slip, leg);
			const down = normal.map((v) => v > 1e-6);
			for (const [a, b] of runs(down)) {
				if (a > 0) ev.push({ t: t[a] as number, kind: "touchdown", leg });
				if (b < t.length - 1)
					ev.push({ t: t[b] as number, kind: "liftoff", leg });
			}
			for (const [a, b] of runs(
				down.map((d, i) => d && (slip[i] as number) > SLIP_SPEED),
				SLIP_MIN_SAMPLES,
			))
				ev.push({
					t: t[a] as number,
					kind: "slip",
					leg,
					detail: {
						duration_s: (t[b] as number) - (t[a] as number),
						peak_speed_m_s: Math.max(...slip.slice(a, b + 1)),
					},
				});
		}
	}

	const cap = sc.drive.max_torque;
	if (cap && sc.drive.kind === "motor") {
		const sat = res.torque.map(
			(q) => Math.abs(q) >= TORQUE_LIMIT_FRACTION * cap,
		);
		for (const [a, b] of runs(sat))
			if ((t[b] as number) - (t[a] as number) >= TORQUE_LIMIT_MIN_S)
				ev.push({
					t: t[a] as number,
					kind: "torque_limit",
					detail: {
						duration_s: (t[b] as number) - (t[a] as number),
						limit_nm: cap,
					},
				});
	}

	if (s.loop_residual) {
		const i = s.loop_residual.findIndex((v) => v > LOOP_OPEN_M);
		if (i >= 0)
			ev.push({
				t: t[i] as number,
				kind: "loop_open",
				detail: { opening_m: s.loop_residual[i] as number },
			});
	}

	if (sc.wind.kind === "gusts" && sc.drive.kind === "sail") {
		const period = Number(sc.wind.params.period ?? 6.0);
		const amp = Number(sc.wind.params.amplitude ?? 1.0);
		for (let k = 0; period * (k + 0.25) <= (t.at(-1) as number); k++)
			ev.push({
				t: period * (k + 0.25),
				kind: "gust",
				detail: { speed_m_s: sc.wind.speed + amp },
			});
	}

	return ev.sort(
		(a, b) =>
			a.t - b.t ||
			(a.kind < b.kind ? -1 : a.kind > b.kind ? 1 : 0) ||
			(a.leg ?? -1) - (b.leg ?? -1),
	);
}

/** Distance one crank revolution carries the body if no foot slipped or was blocked (stance travel / duty factor). */
export function nominalStrideM(
	sc: SimConfig,
	spec: LinkageSpec | null,
): number | null {
	if (!spec) return null;
	const g = gaitMetrics(trace(spec, 180).foot);
	return g.duty > 0 ? (g.strokeLength / g.duty) * sc.walker.unit : null;
}

const g6 = (v: number) => fmtG(v, 6);

export function diagnose(
	res: RunResult,
	events: RunEvent[],
	sc: SimConfig,
	nominal: number | null,
): Diagnosis[] {
	const t = res.t;
	const m = res.metrics;
	const out: Diagnosis[] = [];
	const stride = m.stride_per_rev as number | null | undefined;
	const efficiency =
		nominal && stride !== null && stride !== undefined && !Number.isNaN(stride)
			? stride / nominal
			: null;
	const advanced =
		res.x.length > 1 ? (res.x.at(-1) as number) - (res.x[0] as number) : 0.0;
	const duration = t.length ? (t.at(-1) as number) : 0.0;
	const add = (
		code: string,
		severity: Diagnosis["severity"],
		message: string,
		evidence: Diagnosis["evidence"],
	) => out.push({ code, severity, message, evidence });

	const sail = sc.drive.kind === "sail";
	const rho = sc.environment.air_density;
	if (res.stalled && sail) {
		const d = sc.drive as unknown as Record<string, number>;
		const wind = sc.wind.speed;
		const tau0 =
			(d.sail_gear as number) *
			0.5 *
			rho *
			(d.sail_drag_coeff as number) *
			(d.sail_area as number) *
			(d.sail_radius as number) *
			wind *
			wind;
		add(
			"sail_torque_insufficient",
			"error",
			`The sail did not turn the crank: at standstill it gives about ${pyFixed(tau0 * 1000, 2)} mN·m in a ${g6(wind)} m/s wind and ${g6(rho)} kg/m³ air, which is not enough to overcome the starting load of the walker.`,
			{
				wind_m_s: wind,
				air_density_kg_m3: rho,
				sail_standstill_torque_nm: tau0,
				crank_rotation_rad: res.psi.length ? (res.psi.at(-1) as number) : 0.0,
				waited_s: duration,
			},
		);
	}
	if (sail && !res.stalled && duration > 0) {
		const d = sc.drive as unknown as Record<string, number>;
		const free =
			sc.wind.speed > 0
				? sc.wind.speed / ((d.sail_gear as number) * (d.sail_radius as number))
				: 0.0;
		const omega = (res.psi.at(-1) as number) / duration;
		if (free > 0 && omega < WEAK_SAIL_RATIO * free)
			add(
				"sail_weak",
				"warning",
				`The sail barely turns the crank: ${pyFixed(omega, 2)} rad/s on average, only ${pyPercent0(omega / free)} of the ${pyFixed(free, 2)} rad/s the sail reaches unloaded. The load takes nearly all of the sail torque.`,
				{
					mean_crank_speed_rad_s: omega,
					free_speed_rad_s: free,
					ratio: omega / free,
					wind_m_s: sc.wind.speed,
					air_density_kg_m3: rho,
				},
			);
	}
	const kinds = new Set(events.map((e) => e.kind));
	const limitEvents = events.filter((e) => e.kind === "torque_limit");
	const limitTime = limitEvents.reduce(
		(a, e) => a + (e.detail as Record<string, number>).duration_s!,
		0,
	);
	const cap = sc.drive.max_torque;
	if (
		sc.drive.kind === "motor" &&
		cap &&
		(limitTime > 0.02 * Math.max(duration, 1e-9) || limitEvents.length >= 2)
	) {
		const hasObstacles =
			sc.terrain.kind === "step" || sc.terrain.kind === "bumps";
		if ((efficiency !== null && efficiency < 0.5) || res.stalled) {
			if (hasObstacles)
				add(
					"blocked_by_terrain_torque_limit",
					"error",
					`The walker is blocked by the terrain (${sc.terrain.kind}) and the motor reaches its torque limit (${g6(cap)} N·m) ${limitEvents.length} time(s), ${pyPercent0(limitTime / duration)} of the run in total.`,
					{
						terrain: sc.terrain.kind,
						torque_limit_nm: cap,
						time_at_limit_s: limitTime,
						time_at_limit_share: limitTime / Math.max(duration, 1e-9),
						times_at_limit: limitEvents.length,
						advance_efficiency: efficiency,
						advanced_m: advanced,
					},
				);
			else
				add(
					"torque_limit_too_low",
					"error",
					`The motor reaches its torque limit (${g6(cap)} N·m) ${limitEvents.length} time(s), ${pyPercent0(limitTime / duration)} of the run in total, and the walker makes little progress.`,
					{
						torque_limit_nm: cap,
						time_at_limit_s: limitTime,
						time_at_limit_share: limitTime / Math.max(duration, 1e-9),
						times_at_limit: limitEvents.length,
						advance_efficiency: efficiency,
					},
				);
		}
	}
	if (kinds.has("loop_open")) {
		const e = events.find((x) => x.kind === "loop_open") as RunEvent;
		const opening = (e.detail as Record<string, number>).opening_m as number;
		add(
			"loop_constraints_opened",
			"error",
			`A loop of the linkage opened by ${pyFixed(opening * 1000, 1)} mm at t = ${pyFixed(e.t, 2)} s: the model has come apart, so the numbers after that are not trustworthy.`,
			{ first_time_s: e.t, opening_m: opening },
		);
	}
	const slips = events.filter((e) => e.kind === "slip");
	if (slips.length) {
		const total = slips.reduce(
			(a, e) => a + (e.detail as Record<string, number>).duration_s!,
			0,
		);
		const share = total / (Math.max(duration, 1e-9) * sc.walker.legs);
		if (share > 0.1 && efficiency !== null && efficiency < 0.8)
			add(
				"slipping",
				"warning",
				`Feet slip for ${pyFixed(total, 2)} foot-seconds (${pyPercent0(share)} of all foot time) and the stride is ${pyPercent0(efficiency)} of the ideal.`,
				{
					slip_foot_seconds: total,
					slip_share: share,
					advance_efficiency: efficiency,
					events: slips.length,
				},
			);
	}
	const pen = m.max_penetration as number | null | undefined;
	if (pen !== null && pen !== undefined && pen > 0.005)
		add(
			"deep_sinkage",
			"warning",
			`Feet sink ${pyFixed(pen * 1000, 1)} mm into the ground (soft contact or heavy load).`,
			{ max_penetration_m: pen },
		);
	if (out.length === 0 && efficiency !== null && efficiency < 0.5)
		add(
			"slow_unexplained",
			"warning",
			`The walker covers only ${pyPercent0(efficiency)} of its ideal stride, but no blocking, slipping or torque limit was found.`,
			{ advance_efficiency: efficiency, advanced_m: advanced },
		);
	const rank = { error: 0, warning: 1, info: 2 };
	out.sort((a, b) => rank[a.severity] - rank[b.severity]); // stable: within a severity the rules keep their order
	if (out.length === 0)
		add(
			"ok",
			"info",
			`No problem found: the walker advances normally.${efficiency !== null ? ` Stride is ${pyPercent0(efficiency)} of the ideal.` : ""}`,
			{
				advance_efficiency: efficiency,
				advanced_m: advanced,
				duration_s: duration,
			},
		);
	return out;
}

/** The `energy` metric: input work per revolution over the same whole-revolution window as the gait metric, and where it went. */
export function energyMetrics(
	psi: number[],
	s: Record<
		"e_in" | "e_contact" | "e_loops" | "e_friction" | "kinetic" | "potential",
		number[]
	>,
): Record<string, number> {
	if (psi.length < 2) return {};
	const rev = 2 * Math.PI;
	const total = ((psi.at(-1) as number) - (psi[0] as number)) / rev;
	let lo: number;
	let hi: number;
	if (total >= 1.98) {
		const n = Math.max(1, Math.floor(total + 0.02) - 1);
		lo = rev;
		hi = Math.min(rev * (1 + n), psi.at(-1) as number);
	} else {
		lo = 0;
		hi = psi.at(-1) as number;
	}
	let i0 = -1;
	let i1 = -1;
	psi.forEach((p, i) => {
		if (p >= lo && p <= hi) {
			if (i0 < 0) i0 = i;
			i1 = i;
		}
	});
	if (i0 < 0 || i1 - i0 < 1 || (psi[i1] as number) - (psi[i0] as number) <= 0)
		return {};
	const revs = ((psi[i1] as number) - (psi[i0] as number)) / rev;
	const d = (k: "e_in" | "e_contact" | "e_loops" | "e_friction") =>
		(s[k][i1] as number) - (s[k][i0] as number);
	const dIn = d("e_in");
	const dMech =
		(s.kinetic[i1] as number) +
		(s.potential[i1] as number) -
		((s.kinetic[i0] as number) + (s.potential[i0] as number));
	if (dIn <= 1e-12) return { energy_window_revs: revs };
	return {
		energy_in_per_rev: dIn / revs,
		energy_contact_share: d("e_contact") / dIn,
		energy_loops_share: d("e_loops") / dIn,
		energy_friction_share: d("e_friction") / dIn,
		energy_residual_share:
			(dIn - d("e_contact") - d("e_loops") - d("e_friction") - dMech) / dIn,
		energy_window_revs: revs,
	};
}
