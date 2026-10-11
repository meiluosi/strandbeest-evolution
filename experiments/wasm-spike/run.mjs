import fs from "node:fs";
import loadMujoco from "@mujoco/mujoco";
const ref = JSON.parse(fs.readFileSync("ref.json", "utf8"));
const xml = fs.readFileSync("model.xml", "utf8");
const t0 = performance.now();
const mj = await loadMujoco();
const tLoad = performance.now() - t0;
const model = mj.MjModel.from_xml_string(xml);
const data = new mj.MjData(model);
const id = (kind, name) => mj.mj_name2id(model, kind.value, name);
const act = id(mj.mjtObj.mjOBJ_ACTUATOR, ref.actuator);
const torso = id(mj.mjtObj.mjOBJ_BODY, "torso");
const jnt = id(mj.mjtObj.mjOBJ_JOINT, ref.crank);
const qadr = model.jnt_qposadr[jnt];
console.log("mujoco", mj.mj_versionString?.(), "timestep", model.opt.timestep, "nbody", model.nbody, "ngeom", model.ngeom);
const pos = () => [...data.xpos.slice(torso * 3, torso * 3 + 3)];
const dt = model.opt.timestep;
const t1 = performance.now();
const settle = Math.round(ref.settle / dt);
for (let i = 0; i < settle; i++) { data.ctrl[act] = ref.q0; mj.mj_step(model, data); }
const tSettle = performance.now() - t1;
const psi = () => -ref.direction * (data.qpos[qadr] - ref.q0);
const psi0 = psi();
let target = ref.q0, t = 0, steps = 0, tauSum = 0;
const samples = [];
while (psi() - psi0 < ref.revolutions * 2 * Math.PI) {
  const f0 = Math.min(t / ref.ramp, 1); const f = f0 * f0 * (3 - 2 * f0);
  target += -ref.direction * f * ref.omega * dt;
  data.ctrl[act] = target;
  mj.mj_step(model, data); t += dt; steps++;
  tauSum += -ref.direction * data.actuator_force[act];
  if (steps % 2000 === 0) samples.push([+t.toFixed(4), ...pos()]);
}
const wall = (performance.now() - t1) / 1000;
const end = pos();
console.log(JSON.stringify({ wasmLoad_ms: Math.round(tLoad), settle_wall_s: +(tSettle / 1000).toFixed(2), wall_s: +wall.toFixed(1), steps, sim_t: +t.toFixed(4), torso_end: end, mean_torque: tauSum / steps }));
console.log("python:", JSON.stringify({ wall_s: ref.wall_s, steps: ref.steps, sim_t: ref.sim_t, torso_end: ref.torso_end, mean_torque: ref.mean_torque }));
const dx = end[0] - ref.torso_end[0];
console.log("end x diff (mm):", (dx * 1000).toFixed(4), "| torque rel diff:", ((tauSum / steps - ref.mean_torque) / ref.mean_torque * 100).toFixed(3), "%");
let worst = 0; for (const [i, s] of samples.entries()) { const r = ref.samples[i]; if (r) worst = Math.max(worst, Math.abs(s[1] - r[1]), Math.abs(s[3] - r[3])); }
console.log("worst torso position diff over sampled trajectory (mm):", (worst * 1000).toFixed(4), "n =", Math.min(samples.length, ref.samples.length));
