import loadMujoco from "@mujoco/mujoco";
import { beforeAll, expect, it } from "vitest";
import { StepWork } from "./step-work";

let mj: Awaited<ReturnType<typeof loadMujoco>>;
beforeAll(async () => {
	mj = await loadMujoco();
});

it.each([
	[0, 1],
	[0, -1],
	[2, 1],
	[-2, -1],
	[2, -1],
	[-2, 1],
])(
	"constant force work equals analytic kinetic change (%s, %s)",
	(velocity, force) => {
		const model: any = mj.MjModel.from_xml_string(
			'<mujoco><option timestep=".01" gravity="0 0 0" integrator="implicitfast"/><worldbody><body><joint type="slide" axis="1 0 0"/><geom type="sphere" size=".1" mass="1"/></body></worldbody></mujoco>',
		);
		const data: any = new mj.MjData(model);
		const work = new StepWork(mj, 1);
		try {
			data.qvel[0] = velocity;
			data.qfrc_applied[0] = force;
			let input = 0;
			for (let n = 1; n <= 100; n++) {
				work.begin(data);
				mj.mj_step(model, data);
				input += 0.01 * work.finish(model, data).input;
				expect(input).toBeCloseTo(
					0.5 * (velocity + force * n * 0.01) ** 2 - 0.5 * velocity ** 2,
					11,
				);
			}
		} finally {
			work.delete();
			data.delete();
			model.delete();
		}
	},
);

it.each([-2, 2])(
	"implicit damping closes discrete energy exactly (%s)",
	(velocity) => {
		const model: any = mj.MjModel.from_xml_string(
			'<mujoco><option timestep=".01" gravity="0 0 0" integrator="implicitfast"/><worldbody><body><joint type="slide" axis="1 0 0" damping=".5"/><geom type="sphere" size=".1" mass="1"/></body></worldbody></mujoco>',
		);
		const data: any = new mj.MjData(model);
		const work = new StepWork(mj, 1);
		try {
			data.qvel[0] = velocity;
			let loss = 0;
			for (let n = 1; n <= 100; n++) {
				work.begin(data);
				mj.mj_step(model, data);
				loss += 0.01 * work.finish(model, data).friction;
				expect(loss).toBeCloseTo(
					0.5 * velocity ** 2 - 0.5 * (velocity / 1.005 ** n) ** 2,
					11,
				);
			}
		} finally {
			work.delete();
			data.delete();
			model.delete();
		}
	},
);

it.each([
	[0, 1, 0],
	[0, -1, 0],
	[2, -1, 0],
	[-2, 1, 0],
	[0, 1, 0.5],
	[0, -1, 0.5],
])(
	"servo work includes implicit velocity correction and saturation (%s, %s, %s)",
	(velocity, target, limit) => {
		const limits = limit ? `forcerange="${-limit} ${limit}"` : "";
		const model: any = mj.MjModel.from_xml_string(
			`<mujoco><option timestep=".05" gravity="0 0 0" integrator="implicitfast"/><worldbody><body><joint name="j" type="slide" axis="1 0 0"/><geom type="sphere" size=".1" mass="1"/></body></worldbody><actuator><position joint="j" kp="10" kv="3" ${limits}/></actuator></mujoco>`,
		);
		const data: any = new mj.MjData(model);
		const work = new StepWork(mj, 1, [limit > 0]);
		try {
			data.qvel[0] = velocity;
			data.ctrl[0] = target;
			let input = 0;
			for (let n = 0; n < 30; n++) {
				const v = data.qvel[0];
				const raw = 10 * (target - data.qpos[0]) - 3 * v;
				const clamped = limit > 0 && Math.abs(raw) >= limit;
				const force = limit ? Math.max(-limit, Math.min(limit, raw)) : raw;
				const next = v + (0.05 * force) / (1 + (clamped ? 0 : 0.05 * 3));
				work.begin(data);
				mj.mj_step(model, data);
				input += 0.05 * work.finish(model, data).input;
				expect(data.qvel[0]).toBeCloseTo(next, 12);
				expect(input).toBeCloseTo(0.5 * next ** 2 - 0.5 * velocity ** 2, 11);
			}
		} finally {
			work.delete();
			data.delete();
			model.delete();
		}
	},
);
