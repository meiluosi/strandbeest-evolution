import { t } from "./i18n/index.svelte";
import type { Diagnosis } from "./replay-types";

const pct = (v: unknown) => `${Math.round(Number(v) * 100)}%`;
const num = (v: unknown, d = 1) => Number(v).toFixed(d);

/** The diagnosis in the user's language. The server sends a code, a fallback sentence in English and the evidence numbers; the
 * wording is a message in the catalog filled with those numbers, so a language switch changes it. */
export function diagText(d: Diagnosis): string {
	const e = d.evidence;
	switch (d.code) {
		case "ok":
			return e.advance_efficiency == null
				? t("diag.ok.plain")
				: t("diag.ok", { efficiency: pct(e.advance_efficiency) });
		case "sail_torque_insufficient":
			return t("diag.sail_torque_insufficient", {
				wind: num(e.wind_m_s),
				rho: num(e.air_density_kg_m3, 2),
				torque: num(Number(e.sail_standstill_torque_nm) * 1000, 2),
			});
		case "sail_weak":
			return t("diag.sail_weak", {
				omega: num(e.mean_crank_speed_rad_s, 2),
				free: num(e.free_speed_rad_s, 2),
				ratio: pct(e.ratio),
			});
		case "blocked_by_terrain_torque_limit":
			return t("diag.blocked", {
				terrain: String(e.terrain),
				n: Number(e.times_at_limit),
				limit: num(e.torque_limit_nm, 2),
				share: pct(e.time_at_limit_share),
			});
		case "torque_limit_too_low":
			return t("diag.torque_limit_too_low", {
				n: Number(e.times_at_limit),
				limit: num(e.torque_limit_nm, 2),
				share: pct(e.time_at_limit_share),
			});
		case "loop_constraints_opened":
			return t("diag.loop_open", {
				time: num(e.first_time_s, 2),
				opening: num(Number(e.opening_m) * 1000),
			});
		case "slipping":
			return t("diag.slipping", {
				foot_s: num(e.slip_foot_seconds, 1),
				share: pct(e.slip_share),
				efficiency: pct(e.advance_efficiency),
			});
		case "deep_sinkage":
			return t("diag.deep_sinkage", {
				depth: num(Number(e.max_penetration_m) * 1000),
			});
		case "slow_unexplained":
			return t("diag.slow_unexplained", {
				efficiency: pct(e.advance_efficiency),
			});
		default:
			return d.message;
	}
}
