import type { MainModule } from "@mujoco/mujoco";

/** Work of the implicitfast velocity update, divided by dt.
 * Forces and Jacobians are the original evaluation at t_n. Do not forward
 * the post-state under the old servo target: position feedback is explicit.
 * Matches MujocoBackend.step_power_balance / step_actuator_force.
 */
export class StepWork {
	private readonly before: Float64Array;
	private readonly midpoint: Float64Array;
	private rows: InstanceType<MainModule["DoubleBuffer"]> | undefined;
	private capacity = 0;

	constructor(
		private readonly mj: MainModule,
		nv: number,
		// MuJoCo 3.14's bool-array binding is unavailable in JS. The builder
		// supplies the exact same flag from the scenario's force limit.
		private readonly forceLimited: readonly boolean[] = [],
	) {
		this.before = new Float64Array(nv);
		this.midpoint = new Float64Array(nv);
	}

	begin(data: any): void {
		this.before.set(data.qvel);
	}

	finish(model: any, data: any) {
		const after = data.qvel;
		let input = 0;
		let viscous = 0;
		for (let i = 0; i < this.before.length; i++) {
			const v = 0.5 * (this.before[i]! + after[i]);
			this.midpoint[i] = v;
			input += data.qfrc_applied[i] * v;
			viscous += model.dof_damping[i] * after[i] * v;
		}
		for (let a = 0; a < model.nu; a++) {
			if (this.forceLimited[a] === undefined)
				throw new Error("step work requires each actuator's force-limit flag");
			let force = data.actuator_force[a];
			let dv = 0;
			let vmid = 0;
			const start = data.moment_rowadr[a];
			for (let j = start; j < start + data.moment_rownnz[a]; j++) {
				const i = data.moment_colind[j];
				const moment = data.actuator_moment[j];
				dv += moment * (after[i] - this.before[i]!);
				vmid += moment * this.midpoint[i]!;
			}
			const limited =
				this.forceLimited[a] &&
				(force <= model.actuator_forcerange[2 * a] ||
					force >= model.actuator_forcerange[2 * a + 1]);
			if (!limited) {
				if (model.actuator_gaintype[a] !== 0)
					throw new Error("step work requires a fixed-gain actuator");
				if (model.actuator_biastype[a] === 1)
					force += model.actuator_biasprm[10 * a + 2] * dv;
			}
			input += force * vmid;
		}
		const nefc = data.nefc as number;
		let contact = 0;
		let equality = 0;
		let friction = viscous;
		if (nefc) {
			if (nefc !== this.capacity) {
				this.rows?.delete();
				this.rows = new this.mj.DoubleBuffer(nefc);
				this.capacity = nefc;
			}
			this.mj.mj_mulJacVec(model, data, this.rows!, Array.from(this.midpoint));
			const velocity = this.rows!.GetView();
			const forces = data.efc_force;
			const kinds = data.efc_type;
			for (let i = 0; i < nefc; i++) {
				const loss = -forces[i] * velocity[i]!;
				if (kinds[i] === 0) equality += loss;
				else if (kinds[i] === 1 || kinds[i] === 2) friction += loss;
				else if (kinds[i] >= 5 && kinds[i] <= 7) contact += loss;
			}
		}
		return { input, contact, equality, friction };
	}

	delete(): void {
		this.rows?.delete();
	}
}
