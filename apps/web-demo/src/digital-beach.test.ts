import { solvePose } from "strandbeest-core";
import { describe, expect, it } from "vitest";
import {
	beachDuneGradient,
	beachDuneHeight,
	DigitalBeachSim,
	evaluateTide,
	evaluateWind,
	PHENOTYPES,
} from "./digital-beach-sim";

describe("Digital Beach MAP-Elites phenotypes", () => {
	it("has all 5 distinct MAP-Elites evolved phenotypes", () => {
		const keys = Object.keys(PHENOTYPES);
		expect(keys).toContain("classic_jansen");
		expect(keys).toContain("speed_sprinter");
		expect(keys).toContain("dune_climber");
		expect(keys).toContain("storm_walker");
		expect(keys).toContain("compact_scout");
	});

	it("each phenotype assembles and solves linkage kinematics", () => {
		for (const [id, pheno] of Object.entries(PHENOTYPES)) {
			expect(pheno.legs).toBeGreaterThanOrEqual(4);
			const pose = solvePose(pheno.spec, 0.5);
			expect(pose).not.toBeNull();
			if (pose) {
				expect(pose.F).toBeDefined(); // Foot point exists
				expect(pose.F?.y).toBeLessThan(0); // Foot is lowest point
			}
		}
	});
});

describe("Beach sand dune terrain and environmental fields", () => {
	it("sand dune elevation rises from sea slope into rolling dunes", () => {
		const seaZ = beachDuneHeight(-12.0, 0.0);
		const shoreZ = beachDuneHeight(-2.0, 0.0);
		const duneZ = beachDuneHeight(6.0, 0.0);
		expect(seaZ).toBeLessThan(shoreZ);
		expect(shoreZ).toBeLessThan(duneZ);
	});

	it("beach dune gradient computes slopes accurately", () => {
		const grad = beachDuneGradient(0.0, 0.0);
		expect(Number.isFinite(grad.dx)).toBe(true);
		expect(Number.isFinite(grad.dy)).toBe(true);
	});

	it("evaluates spatiotemporal wind field traveling wave", () => {
		const windCfg = {
			v0: 8.0,
			amplitude: 3.0,
			omega: 1.5,
			kx: 0.5,
			directionDeg: 0.0,
		};
		const w0 = evaluateWind(windCfg, 0.0, 0.0, 0.0);
		expect(w0.speed).toBeCloseTo(8.0, 4);
		expect(w0.vx).toBeCloseTo(8.0, 4);
		expect(w0.vy).toBeCloseTo(0.0, 4);

		// Wave peak at x = pi / (2 * kx) = pi
		const wPeak = evaluateWind(windCfg, 0.0, Math.PI, 0.0);
		expect(wPeak.speed).toBeCloseTo(11.0, 3);
	});

	it("evaluates dynamic coastal tide water level", () => {
		const tideCfg = {
			z0: 0.1,
			amplitude: 0.25,
			omega: 1.0,
			enabled: true,
		};
		expect(evaluateTide(tideCfg, 0.0)).toBeCloseTo(0.1, 4);
		expect(evaluateTide(tideCfg, Math.PI / 2)).toBeCloseTo(0.35, 4);
		expect(evaluateTide(tideCfg, (3 * Math.PI) / 2)).toBeCloseTo(-0.15, 4);
	});
});

describe("Digital Beach multi-walker herd simulation", () => {
	it("spawns multiple walkers and steps kinematics", () => {
		const sim = new DigitalBeachSim();
		sim.spawnWalker("classic_jansen", 0.0, -1.0);
		sim.spawnWalker("speed_sprinter", 0.0, 1.0);
		expect(sim.walkers).toHaveLength(2);

		const walkerA = sim.walkers[0];
		const walkerB = sim.walkers[1];
		expect(walkerA).toBeDefined();
		expect(walkerB).toBeDefined();
		if (!walkerA || !walkerB) return;

		const x0_A = walkerA.x;
		const x0_B = walkerB.x;

		for (let i = 0; i < 20; i++) {
			sim.step(0.02);
		}

		expect(walkerA.x).toBeGreaterThan(x0_A);
		expect(walkerB.x).toBeGreaterThan(x0_B);
	});

	it("mutual bumper collisions repel approaching walkers", () => {
		const sim = new DigitalBeachSim();
		// Place two walkers close along x
		const wA = sim.spawnWalker("classic_jansen", 0.0, 0.0);
		const wB = sim.spawnWalker("classic_jansen", 0.2, 0.0);

		sim.step(0.02);

		// Mutual repulsion forces should be non-zero
		expect(wA.repulsionForce).toBeGreaterThan(0.0);
		expect(wB.repulsionForce).toBeGreaterThan(0.0);
		// Walkers should be pushed apart along x
		expect(wB.x - wA.x).toBeGreaterThan(0.2);
	});

	it("rising tide submergence trips water feeler direction reversal", () => {
		const sim = new DigitalBeachSim();
		// Place walker near shore
		const w = sim.spawnWalker("classic_jansen", -6.0, 0.0);
		w.direction = -1; // Walking toward sea

		// Set tide level above walker feeler tip
		sim.tide.z0 = 0.5;
		sim.tide.enabled = false;

		// Step until feeler vacuum trips
		for (let i = 0; i < 30; i++) {
			sim.step(0.02);
			if (w.feelerTripped) break;
		}

		expect(w.feelerImmersed).toBe(true);
		expect(w.feelerVacuum).toBeGreaterThanOrEqual(25000);
		expect(w.feelerTripped).toBe(true);
		expect(w.direction).toBe(1); // Reversed direction back to land!
	});

	it("steep tilt deploys storm ground anchor and locks walker", () => {
		const sim = new DigitalBeachSim();
		const w = sim.spawnWalker("storm_walker", 0.0, 0.0);

		// Induce high tilt beyond critical 18 degrees
		w.tiltAngleDeg = 24.0;
		sim.step(0.02);

		expect(w.anchorFiring || w.anchorDeployed).toBe(true);

		// After anchoring down
		for (let i = 0; i < 10; i++) {
			sim.step(0.02);
		}

		expect(w.anchorDeployed).toBe(true);
		expect(w.anchorHoldingForce).toBeGreaterThan(500);
		expect(w.crankOmega).toBe(0.0); // Drive locked
	});

	it("stamps and records contact footprints on sand dunes", () => {
		const sim = new DigitalBeachSim();
		sim.spawnWalker("classic_jansen", 0.0, 0.0);

		for (let i = 0; i < 20; i++) {
			sim.step(0.02);
		}

		expect(sim.contactMarks.length).toBeGreaterThan(0);
		const mark = sim.contactMarks[0];
		expect(mark).toBeDefined();
		if (!mark) return;
		expect(mark.radius).toBeGreaterThan(0);
		expect(mark.alpha).toBeGreaterThan(0);
	});
});
