/** Port of strandbeest_sim.winds: wind speed at the sail (m/s) as a function of time and optional height z (W-04). */
import type { SimConfig } from "./config";
import { PyRandom } from "./pyrandom";

export type WindFn = (t: number, z?: number) => number;

function shearFactor(
	z: number | undefined,
	zRef: number,
	alpha: number,
	z0: number,
	profile: string,
	minRatio: number,
): number {
	if (z === undefined) return 1.0;
	const zSafe = Math.max(z, 1e-4);
	if (profile === "log") {
		const num = Math.max(0.0, Math.log(Math.max(zSafe, z0) / z0));
		const denom = Math.max(1e-4, Math.log(Math.max(zRef, z0) / z0));
		return Math.max(minRatio, num / denom);
	}
	return Math.max(minRatio, (zSafe / zRef) ** alpha);
}

export class TurbulentGenerator {
	private tau: number;
	private sigma: number;
	private decay: number;
	private noiseScale: number;
	private rng: PyRandom;
	private buffer: number[];
	private cosYaw: number;

	constructor(
		public meanSpeed: number,
		public intensity = 0.15,
		public integralLength = 25.0,
		public seed = 1,
		public dt = 0.05,
		public yawDeg = 0.0,
	) {
		this.tau = integralLength / Math.max(meanSpeed, 0.1);
		this.sigma = intensity * meanSpeed;
		this.decay = Math.exp(-dt / this.tau);
		this.noiseScale =
			this.sigma *
			Math.sqrt(Math.max(0.0, 1.0 - Math.exp((-2.0 * dt) / this.tau)));
		this.cosYaw = Math.max(0.0, Math.cos((yawDeg * Math.PI) / 180.0));

		this.rng = new PyRandom(Math.trunc(seed));
		const u0 = this.rng.gauss(0.0, this.sigma);
		this.buffer = [u0];
	}

	private extendTo(targetIdx: number) {
		let u = this.buffer[this.buffer.length - 1] as number;
		while (this.buffer.length <= targetIdx) {
			u = u * this.decay + this.rng.gauss(0.0, this.noiseScale);
			this.buffer.push(u);
		}
	}

	getFluctuation(t: number): number {
		if (t <= 0.0) return this.buffer[0] as number;
		const idx = Math.floor(t / this.dt);
		const alpha = (t - idx * this.dt) / this.dt;
		this.extendTo(idx + 1);
		return (
			(1.0 - alpha) * (this.buffer[idx] as number) +
			alpha * (this.buffer[idx + 1] as number)
		);
	}

	eval(t: number, _z?: number): number {
		const uT = this.getFluctuation(t);
		const totalV = Math.max(0.0, this.meanSpeed + uT);
		return totalV * this.cosYaw;
	}
}

export function makeWind(w: SimConfig["wind"]): WindFn {
	const p = (w.params ?? {}) as Record<string, unknown>;
	const yawDeg = Number(p.yaw_deg ?? 0.0);
	const cosYaw = Math.max(0.0, Math.cos((yawDeg * Math.PI) / 180.0));

	switch (w.kind) {
		case "constant": {
			const speed = w.speed * cosYaw;
			return () => speed;
		}
		case "gusts": {
			const amp = Number(p.amplitude ?? 1.0);
			const period = Number(p.period ?? 6.0);
			return (t) =>
				Math.max(
					0.0,
					(w.speed + amp * Math.sin((2 * Math.PI * t) / period)) * cosYaw,
				);
		}
		case "lull": {
			const at = Number(p.at ?? 10.0);
			const speed = w.speed * cosYaw;
			return (t) => (t < at ? speed : 0.0);
		}
		case "turbulent": {
			const intensity = Number(p.intensity ?? 0.15);
			const integralLength = Number(p.integral_length ?? 25.0);
			const seed = Number(p.seed ?? 1);
			const dt = Number(p.dt ?? 0.05);
			const gen = new TurbulentGenerator(
				w.speed,
				intensity,
				integralLength,
				seed,
				dt,
				yawDeg,
			);
			return (t, z) => gen.eval(t, z);
		}
		case "shear": {
			const zRef = Number(p.z_ref ?? 1.0);
			const alpha = Number(p.alpha ?? 0.14);
			const z0 = Number(p.z_0 ?? 0.0002);
			const profile = String(p.profile ?? "power");
			const minRatio = Number(p.min_speed_ratio ?? 0.05);
			return (_t, z) => {
				const sf = shearFactor(z, zRef, alpha, z0, profile, minRatio);
				return Math.max(0.0, w.speed * sf * cosYaw);
			};
		}
		case "profile_turbulent": {
			const zRef = Number(p.z_ref ?? 1.0);
			const alpha = Number(p.alpha ?? 0.14);
			const z0 = Number(p.z_0 ?? 0.0002);
			const profile = String(p.profile ?? "power");
			const minRatio = Number(p.min_speed_ratio ?? 0.05);

			const intensity = Number(p.intensity ?? 0.15);
			const integralLength = Number(p.integral_length ?? 25.0);
			const seed = Number(p.seed ?? 1);
			const dt = Number(p.dt ?? 0.05);
			const gen = new TurbulentGenerator(
				w.speed,
				intensity,
				integralLength,
				seed,
				dt,
				0.0,
			);
			return (t, z) => {
				const sf = shearFactor(z, zRef, alpha, z0, profile, minRatio);
				const uT = gen.getFluctuation(t);
				const baseV = Math.max(0.0, w.speed * sf + uT);
				return baseV * cosYaw;
			};
		}
		default:
			throw new Error(`unknown wind '${w.kind}'`);
	}
}
