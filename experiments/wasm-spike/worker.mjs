import loadMujoco from "./node_modules/@mujoco/mujoco/mujoco.js";
self.onmessage = async () => {
	const ref = await (await fetch("./ref.json")).json();
	const xml = await (await fetch("./model.xml")).text();
	const t0 = performance.now();
	const mj = await loadMujoco();
	const tLoad = performance.now() - t0;
	const model = mj.MjModel.from_xml_string(xml);
	const data = new mj.MjData(model);
	const id = (kind, name) => mj.mj_name2id(model, kind.value, name);
	const act = id(mj.mjtObj.mjOBJ_ACTUATOR, ref.actuator);
	const torso = id(mj.mjtObj.mjOBJ_BODY, "torso");
	const qadr = model.jnt_qposadr[id(mj.mjtObj.mjOBJ_JOINT, ref.crank)];
	const dt = model.opt.timestep;
	const t1 = performance.now();
	for (let i = 0, n = Math.round(ref.settle / dt); i < n; i++) { data.ctrl[act] = ref.q0; mj.mj_step(model, data); }
	const psi = () => -ref.direction * (data.qpos[qadr] - ref.q0);
	const psi0 = psi();
	let target = ref.q0, t = 0, steps = 0, tau = 0;
	while (psi() - psi0 < ref.revolutions * 2 * Math.PI) {
		const f0 = Math.min(t / ref.ramp, 1), f = f0 * f0 * (3 - 2 * f0);
		target += -ref.direction * f * ref.omega * dt;
		data.ctrl[act] = target;
		mj.mj_step(model, data); t += dt; steps++;
		tau += -ref.direction * data.actuator_force[act];
		if (steps % 5000 === 0) postMessage({ progress: psi() / (2 * Math.PI) });
	}
	const x = data.xpos[torso * 3];
	postMessage({ done: true, wasmLoad_ms: Math.round(tLoad), wall_s: +((performance.now() - t1) / 1000).toFixed(1), steps, torso_x: x, dx_mm: (x - ref.torso_end[0]) * 1000, torque_rel_diff_pct: ((tau / steps - ref.mean_torque) / ref.mean_torque) * 100, ua: navigator.userAgent });
};
