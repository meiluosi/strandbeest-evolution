"""Reference run for the WebAssembly spike (EXPERIMENTS section 22): exports the MJCF of the default design on flat ground and
the native result of settle + 1 revolution. Usage: .venv/bin/python experiments/wasm-spike/ref.py experiments/wasm-spike  (reads design.json, writes model.xml and ref.json).
The JS side (run.mjs in Node, worker.mjs + index.html in a browser) needs `npm i @mujoco/mujoco@3.14.0` next to it
(the same version as the Python wheel)."""
import json, math, sys, time
from strandbeest_common import Design
from strandbeest_sim import scenario_from_design
from strandbeest_sim.scenes import scene_overrides
from strandbeest_sim.runner import make_sim
from strandbeest_sim.builder import build as build_mjcf, resolve_spec
from strandbeest_sim.backends.mujoco_backend import obstacles_xml
from strandbeest_sim.registry import terrains, drives

S = sys.argv[1]
design = Design(json.load(open(f"{S}/design.json")))
ov = scene_overrides("flat", revolutions=1.0)
ov["run"]["frame_rate"] = 0
sc = scenario_from_design(design, ov)
sim = make_sim(sc)
cfg = sim.scenario
plan = terrains.get(cfg.terrain.kind)(cfg)
xml = build_mjcf(cfg, resolve_spec(cfg), obstacles=obstacles_xml(plan.obstacles)).xml
open(f"{S}/model.xml", "w").write(xml)
be = sim.backend
meta = dict(dt=be.timestep, settle=cfg.run.settle, revolutions=cfg.run.revolutions, omega=cfg.drive.omega, ramp=cfg.drive.ramp,
            direction=cfg.walker.direction, q0=sim.q0, actuator=sim.info.actuator, crank=sim.info.crank_joint, nbody=be.model.nbody, ngeom=be.model.ngeom, nu=be.model.nu)
drive = drives.get(cfg.drive.kind)(sim)
t0 = time.time()
for _ in range(int(round(cfg.run.settle / be.timestep))):
    drive.control(sim, 0.0, driving=False); be.step()
x_settle = be.body_position("torso")
psi0 = sim.psi(); t = 0.0; samples = []; tau = []
while sim.psi() - psi0 < cfg.run.revolutions * 2 * math.pi:
    drive.control(sim, t, driving=True); be.step(); t += be.timestep
    tau.append(drive.torque(sim))
    if len(tau) % 2000 == 0: samples.append([round(t, 4), *[float(v) for v in be.body_position("torso")]])
wall = time.time() - t0
meta.update(wall_s=round(wall, 1), sim_t=round(t, 4), steps=len(tau), torso_settle=[float(v) for v in x_settle], torso_end=[float(v) for v in be.body_position("torso")], mean_torque=sum(tau)/len(tau), samples=samples)
json.dump(meta, open(f"{S}/ref.json", "w"), indent=1)
print({k: v for k, v in meta.items() if k != "samples"})
