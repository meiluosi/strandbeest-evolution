"""Generate contracts/sim-mjcf/cases.json: the MJCF text (and build facts) the Python builder makes for a set of designs and
overrides. packages/sim-web must reproduce every `xml` byte for byte. Run: .venv/bin/python contracts/generate_sim_mjcf.py

Cases cover every shared scene, odd and even leg counts, other linkages, material and scale changes, every terrain kind, and
the solver / drive / walker options the builder reads, plus designs the builder must refuse (the error text is not compared)."""

import copy
import json
from pathlib import Path

from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import scenario_from_design
from strandbeest_sim.backends.mujoco_backend import obstacles_xml
from strandbeest_sim.builder import build, resolve_spec
from strandbeest_sim.config import sim_config
from strandbeest_sim.registry import terrains
from strandbeest_sim.scenes import presets, scene_overrides

OUT = Path(__file__).parent / "sim-mjcf" / "cases.json"
BASE = json.loads((schema_dir() / "examples" / "design-jansen-small-6leg.json").read_text())


def variant(**changes):
    d = copy.deepcopy(BASE)
    for path, v in changes.items():
        keys = path.split("__")
        t = d
        for k in keys[:-1]:
            t = t[k]
        t[keys[-1]] = v
    return d


DESIGNS = {
    "base": BASE,
    "legs12": variant(walker__legs=12),
    "legs5": variant(walker__legs=5),
    "legs1": variant(walker__legs=1),
    "longcrank": variant(linkage__params={**BASE["linkage"]["params"], "m": 16.0}),
    "petg-scaled": variant(
        manufacturing__material="PETG", manufacturing__bar_width_mm=8, manufacturing__bar_thickness_mm=2.5, walker__unit_m=0.003, walker__body_mass_kg=0.5, walker__lateral_spacing_m=0.02
    ),
    "sail": variant(drive__kind="sail", drive__sail={"area_m2": 0.05, "radius_m": 0.1, "drag_coeff": 1.0, "gear": 8, "inertia_kg_m2": 0.0002, "damping_nm_s": 0.002, "friction_nm": 0.003}),
    "fourbar": variant(
        linkage={
            "params": {"a": 40.0, "l": 0.0, "m": 10.0, "b": 45.0, "j": 38.0},
            "crank": {"x": "a", "y": "l", "length": "m"},
            "joints": [{"id": "K", "centers": ["G", "C"], "radii": ["b", "j"], "side": 1}],
            "foot": "K",
        }
    ),
}

CASES: list[tuple[str, str, dict]] = []
for scene in presets():
    CASES.append((f"scene-{scene}", "base", scene_overrides(scene)))
for name in DESIGNS:
    if name != "base":
        CASES.append((f"design-{name}", name, {}))
CASES += [
    ("terrain-slope", "base", {"terrain": {"kind": "slope", "slope_deg": 7.5, "friction": 0.9}}),
    ("terrain-step-defaults", "base", {"terrain": {"kind": "step"}}),
    ("terrain-step-params", "base", {"terrain": {"kind": "step", "friction": 0.8, "params": {"distance": 0.2, "height": 0.015, "length": 0.6}}}),
    ("terrain-bumps-seed17", "base", {"terrain": {"kind": "bumps", "friction": 0.8, "params": {"count": 5, "max_height": 0.02, "start": 0.2, "seed": 17}}}),
    ("terrain-bumps-defaults", "base", {"terrain": {"kind": "bumps"}}),
    ("terrain-soft", "base", {"terrain": {"kind": "soft", "params": {"stiffness": 5000.0, "damping": 90.0}}}),
    ("solver-no-contact-stiffness", "base", {"solver": {"contact_stiffness": None, "contact_solref": 0.015}}),
    ("solver-options", "base", {"solver": {"timestep": 0.0002, "iterations": 50, "cone": "elliptic", "impratio": 10.0, "noslip_iterations": 5, "solref_time": 0.002, "solimp": "0.95 0.99 0.001", "contact_damping_ratio": 0.7}}),
    ("solver-tiny-timestep", "base", {"solver": {"timestep": 0.00001}}),
    ("walker-pitch-free", "base", {"walker": {"pitch": "free"}}),
    ("walker-pin-loss", "base", {"walker": {"joint_friction": 0.01, "joint_damping": 0.002}}),
    ("walker-total-mass", "base", {"walker": {"body_mass": None, "mass": 2.0, "foot_friction": 1.0, "foot_radius": 0.002, "bar_radius": 0.004}}),
    ("walker-too-heavy-legs", "base", {"walker": {"body_mass": None, "mass": 0.1}}),
    ("drive-no-torque-limit", "base", {"drive": {"max_torque": None, "kp": 123.456, "kv": 7.0}}),
    ("drive-torque-limit", "base", {"drive": {"max_torque": 0.5}}),
    ("environment-gravity", "base", {"environment": {"gravity": 3.71}}),
    ("linkage-param-override", "base", {"linkage": {"params": {"m": 14.0, "b": 43.0}}}),
]


def run_case(design, overrides):
    sc = scenario_from_design(Design(design), copy.deepcopy(overrides))
    cfg = sim_config(sc)
    plan = terrains.get(cfg.terrain.kind)(cfg)
    try:
        b = build(cfg, resolve_spec(cfg), obstacles=obstacles_xml(plan.obstacles))
    except ValueError as e:
        return {"error": str(e)}
    return {
        "xml": b.xml,
        "n_legs": b.n_legs,
        "crank_joint": b.crank_joint,
        "crank_q0": b.crank_q0,
        "actuator": b.actuator,
        "hip_height": b.hip_height,
        "bar_mass_total": b.bar_mass_total,
        "plan": {"slope_deg": plan.slope_deg, "softness": list(plan.softness) if plan.softness else None, "obstacles": len(plan.obstacles)},
    }


def main() -> None:
    cases = [{"name": n, "design": d, "overrides": ov, "expected": run_case(DESIGNS[d], ov)} for n, d, ov in CASES]
    doc = {
        "note": "Expected MJCF of the Python builder (packages/sim). packages/sim-web must match xml byte for byte and the numbers to 1e-12 relative. Regenerate with contracts/generate_sim_mjcf.py when the builder changes on purpose.",
        "tolerance": 1e-12,
        "designs": DESIGNS,
        "cases": cases,
    }
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    errs = sum("error" in c["expected"] for c in cases)
    print(f"{len(cases)} cases ({errs} expected errors), {OUT.stat().st_size // 1000} kB -> {OUT}")


if __name__ == "__main__":
    main()
