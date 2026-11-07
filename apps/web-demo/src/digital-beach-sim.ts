/** Digital Beach Multi-Walker Sandbox Simulation Engine (M8-03).
 *
 * Implements:
 * - MAP-Elites phenotype library with distinct linkage morphologies and gait mechanics.
 * - Rolling coastal beach sand dune heightfield z_dune(x, y).
 * - Spatiotemporal traveling wind field v_wind(t, x, y) = v0 + A * sin(omega * t + kx * x).
 * - Dynamic tide water level z_water(t) = z0 + h_tide * sin(omega_tide * t).
 * - Multi-walker co-simulation with mutual bumper repulsion forces.
 * - Autonomous reflexes:
 *   * Water feeler: tip immersion in rising tide creates vacuum, flipping direction.
 *   * Storm anchor: tilt beyond 18 deg shoots anchor into sand, arresting overturning.
 * - Contact mark generation for foot-sand interaction.
 */

import { jansenSpec, type LinkageSpec } from "strandbeest-core";

export interface Phenotype {
	id: string;
	nameKey: string;
	descKey: string;
	spec: LinkageSpec;
	legs: number;
	bodyMass: number;
	crankRadius: number;
	color: number;
	unit: number;
	strideSpeed: number;
	bodyLength: number;
	bodyWidth: number;
}

const defaultParams = jansenSpec().params;

/** MAP-Elites atlas phenotypes representing distinct evolved walker niches */
export const PHENOTYPES: Record<string, Phenotype> = {
	classic_jansen: {
		id: "classic_jansen",
		nameKey: "beach.phenotype.classicJansen",
		descKey: "beach.phenotype.classicJansenDesc",
		spec: jansenSpec(),
		legs: 6,
		bodyMass: 0.85,
		crankRadius: 0.015,
		color: 0xe3b448, // Iconic Theo Jansen yellow PVC conduit tone
		unit: 0.002,
		strideSpeed: 0.18,
		bodyLength: 0.28,
		bodyWidth: 0.18,
	},
	speed_sprinter: {
		id: "speed_sprinter",
		nameKey: "beach.phenotype.speedSprinter",
		descKey: "beach.phenotype.speedSprinterDesc",
		spec: { ...jansenSpec(), params: { ...defaultParams, m: 16.0 } },
		legs: 6,
		bodyMass: 0.65,
		crankRadius: 0.016,
		color: 0xf77f00, // Speed orange
		unit: 0.002,
		strideSpeed: 0.26,
		bodyLength: 0.26,
		bodyWidth: 0.16,
	},
	dune_climber: {
		id: "dune_climber",
		nameKey: "beach.phenotype.duneClimber",
		descKey: "beach.phenotype.duneClimberDesc",
		spec: { ...jansenSpec(), params: { ...defaultParams, m: 14.5 } },
		legs: 8,
		bodyMass: 1.25,
		crankRadius: 0.0145,
		color: 0x2a9d8f, // Marine teal
		unit: 0.0024,
		strideSpeed: 0.16,
		bodyLength: 0.36,
		bodyWidth: 0.22,
	},
	storm_walker: {
		id: "storm_walker",
		nameKey: "beach.phenotype.stormWalker",
		descKey: "beach.phenotype.stormWalkerDesc",
		spec: { ...jansenSpec(), params: { ...defaultParams, m: 13.5 } },
		legs: 12,
		bodyMass: 2.1,
		crankRadius: 0.0135,
		color: 0x4a4e69, // Armored storm steel
		unit: 0.0026,
		strideSpeed: 0.12,
		bodyLength: 0.44,
		bodyWidth: 0.28,
	},
	compact_scout: {
		id: "compact_scout",
		nameKey: "beach.phenotype.compactScout",
		descKey: "beach.phenotype.compactScoutDesc",
		spec: { ...jansenSpec(), params: { ...defaultParams, m: 15.0 } },
		legs: 4,
		bodyMass: 0.45,
		crankRadius: 0.015,
		color: 0xd62828, // Agile crimson
		unit: 0.0016,
		strideSpeed: 0.22,
		bodyLength: 0.2,
		bodyWidth: 0.14,
	},
};

/** Beach sand dune heightfield z_dune(x, y) */
export function beachDuneHeight(x: number, y: number): number {
	// Shoreline dips into sea at x < -10; dunes roll gracefully for x > -10
	const seaSlope = 0.045 * (x + 8.0);
	const dune1 = 0.28 * Math.sin(0.16 * x) * Math.cos(0.12 * y);
	const dune2 = 0.12 * Math.sin(0.35 * x + 0.6) * Math.sin(0.22 * y);
	const ridge = 0.18 / (1.0 + Math.exp(-0.25 * (x - 1.0)));
	return seaSlope + dune1 + dune2 + ridge;
}

export function beachDuneGradient(
	x: number,
	y: number,
): { dx: number; dy: number } {
	const eps = 0.05;
	const h = beachDuneHeight(x, y);
	const hx = beachDuneHeight(x + eps, y);
	const hy = beachDuneHeight(x, y + eps);
	return {
		dx: (hx - h) / eps,
		dy: (hy - h) / eps,
	};
}

export interface WindConfig {
	v0: number; // Base speed m/s
	amplitude: number; // Gust amplitude m/s
	omega: number; // rad/s
	kx: number; // rad/m
	directionDeg: number; // degrees (0 = along +x)
}

export function evaluateWind(
	cfg: WindConfig,
	t: number,
	x: number,
	y: number,
): { speed: number; vx: number; vy: number } {
	const wave = cfg.amplitude * Math.sin(cfg.omega * t + cfg.kx * x);
	const speed = Math.max(0, cfg.v0 + wave);
	const rad = (cfg.directionDeg * Math.PI) / 180;
	return {
		speed,
		vx: speed * Math.cos(rad),
		vy: speed * Math.sin(rad),
	};
}

export interface TideConfig {
	z0: number; // Mean water elevation m
	amplitude: number; // Tide amplitude m
	omega: number; // rad/s
	enabled: boolean; // Dynamic tide oscillation toggle
}

export function evaluateTide(cfg: TideConfig, t: number): number {
	if (!cfg.enabled) return cfg.z0;
	return cfg.z0 + cfg.amplitude * Math.sin(cfg.omega * t);
}

export interface ContactMark {
	x: number;
	y: number;
	z: number;
	radius: number;
	alpha: number;
}

export interface BeachWalkerState {
	id: string;
	name: string;
	phenotype: Phenotype;
	x: number;
	y: number;
	z: number;
	vx: number;
	vy: number;
	heading: number; // radians
	crankAngle: number;
	crankOmega: number;
	direction: number; // +1 forward, -1 reverse
	// Water feeler reflex
	feelerTipZ: number;
	feelerVacuum: number; // Pa
	feelerImmersed: boolean;
	feelerTripped: boolean;
	// Storm anchor reflex
	tiltAngleDeg: number;
	anchorFiring: boolean;
	anchorDeployed: boolean;
	anchorPenetration: number;
	anchorHoldingForce: number;
	// Interaction
	repulsionForce: number;
	stepTimer: number;
}

export class DigitalBeachSim {
	walkers: BeachWalkerState[] = [];
	wind: WindConfig = {
		v0: 6.0,
		amplitude: 2.0,
		omega: 1.0,
		kx: 0.5,
		directionDeg: 0.0,
	};
	tide: TideConfig = {
		z0: 0.05,
		amplitude: 0.18,
		omega: 0.6,
		enabled: true,
	};
	time = 0;
	contactMarks: ContactMark[] = [];
	maxMarks = 250;

	private _walkerCounter = 0;
	private _spawnSeed = 42;

	private _seededRandom(): number {
		this._spawnSeed = (this._spawnSeed + 0x6d2b79f5) | 0;
		let t = Math.imul(
			this._spawnSeed ^ (this._spawnSeed >>> 15),
			1 | this._spawnSeed,
		);
		t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
		return (t >>> 0) / 4294967296;
	}

	spawnWalker(
		phenotypeId: string,
		x?: number,
		y?: number,
		heading = 0.0,
	): BeachWalkerState {
		const defaultPheno = PHENOTYPES.classic_jansen as Phenotype;
		const pheno = PHENOTYPES[phenotypeId] ?? defaultPheno;
		this._walkerCounter++;
		const id = `walker_${Date.now()}_${this._walkerCounter}`;
		const posX = x ?? this._seededRandom() * 6.0 - 1.0;
		const posY = y ?? this._seededRandom() * 8.0 - 4.0;
		const groundZ = beachDuneHeight(posX, posY);

		const walker: BeachWalkerState = {
			id,
			name: pheno.nameKey,
			phenotype: pheno,
			x: posX,
			y: posY,
			z: groundZ + 0.16,
			vx: 0.0,
			vy: 0.0,
			heading,
			crankAngle: this._seededRandom() * Math.PI * 2,
			crankOmega: 2.0,
			direction: 1,
			feelerTipZ: groundZ + 0.05,
			feelerVacuum: 0.0,
			feelerImmersed: false,
			feelerTripped: false,
			tiltAngleDeg: 0.0,
			anchorFiring: false,
			anchorDeployed: false,
			anchorPenetration: 0.0,
			anchorHoldingForce: 0.0,
			repulsionForce: 0.0,
			stepTimer: 0.0,
		};
		this.walkers.push(walker);
		return walker;
	}

	removeWalker(id: string) {
		this.walkers = this.walkers.filter((w) => w.id !== id);
	}

	clear() {
		this.walkers = [];
		this.contactMarks = [];
	}

	scatter(count = 4) {
		this.clear();
		const phenoKeys = Object.keys(PHENOTYPES);
		if (phenoKeys.length === 0) return;
		for (let i = 0; i < count; i++) {
			const phenoKey = phenoKeys[i % phenoKeys.length] ?? "classic_jansen";
			const x = -3.0 + i * 2.5;
			const y = -3.0 + i * 1.8;
			this.spawnWalker(phenoKey, x, y, 0.0);
		}
	}

	step(dt: number) {
		this.time += dt;
		const currentWaterLevel = evaluateTide(this.tide, this.time);

		// 1. Advance individual kinematics, environmental wind and autonomous reflexes
		for (const w of this.walkers) {
			const wLocal = evaluateWind(this.wind, this.time, w.x, w.y);
			const cosH = Math.cos(w.heading);
			const sinH = Math.sin(w.heading);

			// Wind aerodynamic drag/thrust along walker heading
			const windEff = wLocal.vx * cosH + wLocal.vy * sinH;
			const windSpeedRatio = Math.max(0.2, 1.0 + 0.06 * windEff);

			// Compute terrain elevation and tilt
			const groundZ = beachDuneHeight(w.x, w.y);
			const grad = beachDuneGradient(w.x, w.y);
			const slopeAlongHeading = grad.dx * cosH + grad.dy * sinH;
			const terrainTiltDeg = (Math.atan(slopeAlongHeading) * 180) / Math.PI;

			w.z = groundZ + 0.16;

			// Autonomous reflex 1: Water feeler
			// Oscillates with stride: tip reaches down near the sand
			w.feelerTipZ = groundZ + 0.05 + 0.035 * Math.sin(2.0 * w.crankAngle);
			w.feelerImmersed = w.feelerTipZ <= currentWaterLevel;

			if (w.feelerImmersed) {
				// Submerged: intake tube sealed by water meniscus; vacuum builds rapidly
				w.feelerVacuum = Math.min(60000, w.feelerVacuum + 90000 * dt);
				// Vacuum exceeds trip threshold (-25 kPa)
				if (w.feelerVacuum >= 25000 && !w.feelerTripped) {
					w.feelerTripped = true;
					w.direction = -w.direction; // Trip direction reverse!
				}
			} else {
				// In air: free aspiration dissipates vacuum
				w.feelerVacuum = Math.max(0, w.feelerVacuum - 40000 * dt);
				if (w.feelerVacuum < 5000) {
					w.feelerTripped = false;
				}
			}

			// Autonomous reflex 2: Storm ground-anchor
			// Dynamic tilt includes terrain slope and collision push
			const totalTilt = Math.abs(terrainTiltDeg) + w.tiltAngleDeg;
			if (totalTilt >= 18.0 && !w.anchorDeployed && !w.anchorFiring) {
				w.anchorFiring = true;
			}

			if (w.anchorFiring || w.anchorDeployed) {
				// Pneumatic cylinder fires spike downward into beach sand
				w.anchorPenetration = Math.min(0.15, w.anchorPenetration + 3.5 * dt);
				if (w.anchorPenetration >= 0.15) {
					w.anchorDeployed = true;
					w.anchorFiring = false;
				}
				// Rankine passive earth pressure soil holding force
				w.anchorHoldingForce = 1500 * (w.anchorPenetration / 0.15);

				// Pin walker: halt forward drive, damp tilt
				w.crankOmega = 0.0;
				w.vx = 0.0;
				w.vy = 0.0;
				w.tiltAngleDeg = Math.max(0, w.tiltAngleDeg - 25.0 * dt);
			} else {
				// Normal walking drive
				w.anchorHoldingForce = 0.0;
				w.crankOmega = 2.0 * windSpeedRatio;
				w.crankAngle += w.direction * w.crankOmega * dt;

				const forwardSpeed =
					w.phenotype.strideSpeed * w.direction * (w.crankOmega / 2.0);
				w.vx = forwardSpeed * cosH;
				w.vy = forwardSpeed * sinH;
				w.x += w.vx * dt;
				w.y += w.vy * dt;

				// Relax tilt
				w.tiltAngleDeg = Math.max(0, w.tiltAngleDeg - 10.0 * dt);

				// Stance contact imprint on sand dunes
				w.stepTimer += dt;
				if (w.stepTimer > 0.18) {
					w.stepTimer = 0.0;
					this.recordContactMark(w.x, w.y, groundZ);
				}
			}
		}

		// 2. Multi-walker mutual bumper collisions & repulsive forces
		const n = this.walkers.length;
		for (let i = 0; i < n; i++) {
			const w = this.walkers[i];
			if (w) w.repulsionForce = 0.0;
		}

		for (let i = 0; i < n; i++) {
			for (let j = i + 1; j < n; j++) {
				const wA = this.walkers[i];
				const wB = this.walkers[j];
				if (!wA || !wB) continue;
				const dx = wB.x - wA.x;
				const dy = wB.y - wA.y;
				const dist = Math.sqrt(dx * dx + dy * dy);
				const bumperDist =
					(wA.phenotype.bodyLength + wB.phenotype.bodyLength) * 0.5 + 0.08;

				if (dist < bumperDist && dist > 1e-4) {
					const compression = bumperDist - dist;
					const nx = dx / dist;
					const ny = dy / dist;

					// Relative velocity
					const rvx = wB.vx - wA.vx;
					const rvy = wB.vy - wA.vy;
					const vRelNorm = rvx * nx + rvy * ny;

					const fRep = Math.max(0, 350 * compression - 25 * vRelNorm);
					wA.repulsionForce = Math.max(wA.repulsionForce, fRep);
					wB.repulsionForce = Math.max(wB.repulsionForce, fRep);

					// Displace and push apart
					const displace = compression * 0.5;
					wA.x -= nx * displace;
					wA.y -= ny * displace;
					wB.x += nx * displace;
					wB.y += ny * displace;

					// Bumping causes pitching tilt torque
					const tiltImpact = Math.min(22.0, fRep * 0.08);
					wA.tiltAngleDeg += tiltImpact * 0.5;
					wB.tiltAngleDeg += tiltImpact * 0.5;
				}
			}
		}

		// Decay contact marks
		for (let i = this.contactMarks.length - 1; i >= 0; i--) {
			const mark = this.contactMarks[i];
			if (!mark) continue;
			mark.alpha -= 0.04 * dt;
			if (mark.alpha <= 0.0) {
				this.contactMarks.splice(i, 1);
			}
		}
	}

	recordContactMark(x: number, y: number, z: number) {
		this.contactMarks.push({
			x,
			y,
			z: z + 0.005,
			radius: 0.028,
			alpha: 0.85,
		});
		if (this.contactMarks.length > this.maxMarks) {
			this.contactMarks.shift();
		}
	}
}
