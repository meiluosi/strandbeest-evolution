"""LinkageSpec + Scenario -> MJCF.

Planar model in the x–z plane (x forward, z up; MuJoCo's y is lateral and only separates legs visually).

Reduced-coordinate tree plus loop closures (the formulation MuJoCo recommends for closed chains):
- Every bar is a body hinged (about +y) at its start point on the body that "owns" that point:
  G -> torso, C -> crank, a joint J -> the first of the two bars that end at J.
- The second bar ending at J closes the loop with a `connect` equality at J. One closure per linkage joint.
- N legs share one crankshaft: crank i is tied to crank 0 by a joint equality, which keeps the initial phase offset.
- Only feet collide with terrain, so legs may pass each other.

All body frames stay axis-aligned at the reference pose (hinge refs are folded into the geometry), so every position
below is a plain world-frame difference.

Angle convention: the linkage's crank angle theta is counter-clockwise in (x right, y up); MuJoCo's hinge about +y is
clockwise in that view, so q = -theta. `psi` (rotation in the walking direction) satisfies theta = direction * psi.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from .config import Scenario, SimConfig, sim_config
from .linkage import LinkageSpec, Point, load_spec, solve_pose

DATA = Path(__file__).parent / "data"

# Reproduces the foot bug of 2026-10-05 (two coincident foot spheres per leg that collided with each other). Kept ONLY so the
# simulator skeptic can prove it would catch it; never set it outside that test.
LEGACY_FOOT_BUG = False


def resolve_spec(sc: Scenario | SimConfig) -> LinkageSpec:
    sc = sim_config(sc)
    src = sc.linkage.spec
    if isinstance(src, dict):
        d = json.loads(json.dumps(src))
    else:
        path = DATA / "jansen.json" if src == "jansen" else Path(src)
        d = json.loads(path.read_text())
    d["params"].update(sc.linkage.params)
    return load_spec(d)


@dataclass
class Built:
    xml: str
    n_legs: int
    crank_joint: str  # name of the driven crank joint (leg 0)
    crank_q0: float  # its reference angle, rad
    actuator: str
    hip_height: float  # initial torso height, m
    bar_mass_total: float


@dataclass
class EntityBuilt:
    name: str
    torso_body: str
    crank_joint: str
    crank_q0: float
    actuator: str
    hip_height: float
    n_legs: int
    bar_mass_total: float
    total_mass: float
    body_length: float = 0.25
    body_width: float = 0.1
    direction: int = -1
    drive_kind: str = "motor"
    sail_area: float = 0.04
    sail_radius: float = 0.04
    sail_drag_coeff: float = 1.2
    sail_gear: float = 1.0


@dataclass
class HerdBuilt:
    xml: str
    entities: dict[str, EntityBuilt]


def _f(v: float) -> str:
    return f"{v:.9g}"


@dataclass
class _Bar:
    name: str
    start: str  # linkage point the bar is hinged at (the bar's body origin)
    end: str
    mass: float


def _build_walker_tree(
    w: Any,
    drive: Any,
    spec: LinkageSpec,
    prefix: str = "",
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    phase_offset: float = 0.0,
) -> tuple[str, list[str], str, EntityBuilt]:
    u = w.unit
    n = w.legs
    phases = [phase_offset + 2 * math.pi * i / n for i in range(n)]
    poses = []
    for ph in phases:
        p = solve_pose(spec, ph)
        if p is None:
            raise ValueError("linkage cannot assemble at the initial crank angle")
        poses.append(p)

    lowest = min(p[spec.foot][1] for p in poses) * u
    hip_h = -lowest + w.foot_radius
    pin_loss = (f' frictionloss="{_f(w.joint_friction)}"' if w.joint_friction > 0 else "") + (f' damping="{_f(w.joint_damping)}"' if w.joint_damping > 0 else "")

    def mass_of(length_units: float) -> float:
        return max(w.tube_mass_per_m * length_units * u, w.min_bar_mass)

    crank_mass = mass_of(spec.crank)
    per_leg_mass = crank_mass + sum(mass_of(spec.val(r)) for j in spec.joints for r in j.radii)
    torso_mass = w.body_mass if w.body_mass is not None else w.mass - n * per_leg_mass
    if torso_mass <= 0:
        raise ValueError(f"legs weigh {n * per_leg_mass:.1f} kg, more than the total mass {w.mass} kg")

    eq: list[str] = []
    torso_children: list[str] = []

    for i in range(n):
        pose = poses[i]
        y = (i - (n - 1) / 2) * w.lateral_spacing
        px, py = spec.pivot
        tip = pose["C"]

        crank_body_name = f"{prefix}crank{i}"
        bars_at: dict[str, list[_Bar]] = {}
        owner_of: dict[str, str] = {"C": crank_body_name}
        by_name: dict[str, _Bar] = {}
        for j in spec.joints:
            for k, (c, r) in enumerate(zip(j.centers, j.radii)):
                b = _Bar(f"{prefix}bar{i}_{j.id}{k}", c, j.id, mass_of(spec.val(r)))
                bars_at.setdefault(c, []).append(b)
                by_name[b.name] = b
            owner_of[j.id] = f"{prefix}bar{i}_{j.id}0"

        foot_done: list[bool] = []

        def emit(b: _Bar, parent_origin: Point, y_off: float) -> str:
            ps, pe = pose[b.start], pose[b.end]
            pos = ((ps[0] - parent_origin[0]) * u, y_off, (ps[1] - parent_origin[1]) * u)
            rel = ((pe[0] - ps[0]) * u, (pe[1] - ps[1]) * u)
            geoms = (
                f'<geom type="capsule" fromto="0 0 0 {_f(rel[0])} 0 {_f(rel[1])}" size="{_f(w.bar_radius)}" mass="{_f(b.mass)}" '
                f'contype="0" conaffinity="0" rgba="0.75 0.7 0.2 1"/>'
            )
            if b.end == spec.foot and (not foot_done or LEGACY_FOOT_BUG):
                foot_done.append(True)
                geoms += (
                    f'<geom name="foot_{b.name}" type="sphere" pos="{_f(rel[0])} 0 {_f(rel[1])}" size="{_f(w.foot_radius)}" '
                    f'mass="1e-6" friction="{_f(w.foot_friction)} 0.005 0.0001" contype="{1 if LEGACY_FOOT_BUG else 2}" conaffinity="1" rgba="0.9 0.45 0.25 1"/>'
                )
            kids = ""
            if owner_of.get(b.end) == b.name:
                kids = "".join(emit(c, ps, 0.0) for c in bars_at.get(b.end, []))
            return (
                f'<body name="{b.name}" pos="{_f(pos[0])} {_f(pos[1])} {_f(pos[2])}">'
                f'<joint name="{b.name}" type="hinge" axis="0 1 0"{pin_loss}/>{geoms}{kids}</body>'
            )

        torso_children.extend(emit(b, (0.0, 0.0), y) for b in bars_at.get("G", []))
        crank_vec = ((tip[0] - px) * u, (tip[1] - py) * u)
        crank_kids = "".join(emit(b, (px, py), 0.0) for b in bars_at.get("C", []))
        torso_children.append(
            f'<body name="{crank_body_name}" pos="{_f(px * u)} {_f(y)} {_f(py * u)}">'
            f'<joint name="{crank_body_name}" type="hinge" axis="0 1 0" ref="{_f(-phases[i])}"/>'
            f'<geom type="capsule" fromto="0 0 0 {_f(crank_vec[0])} 0 {_f(crank_vec[1])}" size="{_f(w.bar_radius)}" '
            f'mass="{_f(crank_mass)}" contype="0" conaffinity="0" rgba="0.2 0.2 0.25 1"/>{crank_kids}</body>'
        )

        for j in spec.joints:
            first, second = f"{prefix}bar{i}_{j.id}0", f"{prefix}bar{i}_{j.id}1"
            at = pose[j.id]
            s2 = pose[by_name[second].start]
            eq.append(
                f'<connect body1="{second}" body2="{first}" anchor="{_f((at[0] - s2[0]) * u)} 0 {_f((at[1] - s2[1]) * u)}"/>'
            )
        if i > 0:
            eq.append(f'<joint joint1="{crank_body_name}" joint2="{prefix}crank0" polycoef="0 1 0 0 0"/>')

    pitch_joint = f'<joint name="{prefix}tp" type="hinge" axis="0 1 0"/>' if w.pitch == "free" else ""
    half_y = max(w.lateral_spacing * n / 2, 0.05)
    torso_name = f"{prefix}torso" if prefix else "torso"
    tx_name = f"{prefix}tx" if prefix else "tx"
    tz_name = f"{prefix}tz" if prefix else "tz"
    pos_str = f"{_f(offset_x)} {_f(offset_y)} {_f(hip_h)}"
    torso_geom_name = f"{torso_name}_geom"

    torso_xml = f"""<body name="{torso_name}" pos="{pos_str}">
      <joint name="{tx_name}" type="slide" axis="1 0 0"/>
      <joint name="{tz_name}" type="slide" axis="0 0 1"/>
      {pitch_joint}
      <geom name="{torso_geom_name}" type="box" size="{_f(w.body_length / 2)} {_f(half_y)} 0.03" mass="{_f(torso_mass)}" contype="4" conaffinity="4" rgba="0.15 0.15 0.2 1"/>
      {"".join(torso_children)}
    </body>"""

    force_attr = f' forcelimited="true" forcerange="{-drive.max_torque} {drive.max_torque}"' if drive.max_torque else ""
    actuator_name = f"{prefix}drive" if prefix else "drive"
    crank0_name = f"{prefix}crank0"
    actuator_xml = f'<position name="{actuator_name}" joint="{crank0_name}" kp="{drive.kp}" kv="{drive.kv}" ctrlrange="-1e6 1e6"{force_attr}/>'

    ent_built = EntityBuilt(
        name=prefix.rstrip("_"),
        torso_body=torso_name,
        crank_joint=crank0_name,
        crank_q0=-phases[0],
        actuator=actuator_name,
        hip_height=hip_h,
        n_legs=n,
        bar_mass_total=n * per_leg_mass,
        total_mass=torso_mass + n * per_leg_mass,
        body_length=float(getattr(w, "body_length", 0.25)),
        body_width=float(half_y * 2),
        direction=int(getattr(w, "direction", -1)),
        drive_kind=str(getattr(drive, "kind", "motor")),
        sail_area=float(getattr(drive, "sail_area", 0.04)),
        sail_radius=float(getattr(drive, "sail_radius", 0.04)),
        sail_drag_coeff=float(getattr(drive, "sail_drag_coeff", 1.2)),
        sail_gear=float(getattr(drive, "sail_gear", 1.0)),
    )
    return torso_xml, eq, actuator_xml, ent_built


def _tolerance_attribute(tolerance: float | None) -> str:
    if tolerance is None:
        return ""
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("solver.tolerance must be null or a finite nonnegative number")
    return f' tolerance="{tolerance}"'


def build(sc: Scenario | SimConfig, spec: LinkageSpec, obstacles: str = "") -> Built:
    """`obstacles` is MJCF for the static blocks of the terrain (made by the MuJoCo adapter from the terrain plan)."""
    sc = sim_config(sc)
    w = sc.walker
    torso_xml, eq, actuator_xml, ent_built = _build_walker_tree(w, sc.drive, spec)

    sv = sc.solver
    if sv.contact_stiffness is not None:
        # MuJoCo direct solref is already mass-normalised: [1/s^2, 1/s].
        # The documented damping ratio is b / (2*sqrt(k)); no effective mass
        # or assumed number of supporting feet belongs in this conversion.
        damping = 2.0 * sv.contact_damping_ratio * math.sqrt(sv.contact_stiffness)
        geom_solref = f"{-sv.contact_stiffness} {-damping}"
    else:
        geom_solref = f"{sv.contact_solref} 1"

    xml = f"""<mujoco model="{sc.name}">
  <compiler angle="radian"/>
  <option timestep="{sv.timestep}" integrator="implicitfast" solver="Newton" iterations="{sv.iterations}"{_tolerance_attribute(sv.tolerance)} cone="{sv.cone}" impratio="{sv.impratio}" noslip_iterations="{sv.noslip_iterations}" gravity="0 0 -{sc.environment.gravity}"/>
  <default>
    <equality solref="{sv.solref_time} 1" solimp="{sv.solimp}"/>
    <geom solref="{geom_solref}"/>
  </default>
  <worldbody>
    {obstacles}
    <geom name="ground" type="plane" size="200 20 0.1" friction="{sc.terrain.friction} 0.005 0.0001" contype="1" conaffinity="2" rgba="0.85 0.82 0.75 1"/>
    {torso_xml}
  </worldbody>
  <equality>
    {"".join(eq)}
  </equality>
  <actuator>
    {actuator_xml}
  </actuator>
</mujoco>"""
    return Built(
        xml=xml,
        n_legs=ent_built.n_legs,
        crank_joint=ent_built.crank_joint,
        crank_q0=ent_built.crank_q0,
        actuator=ent_built.actuator,
        hip_height=ent_built.hip_height,
        bar_mass_total=ent_built.bar_mass_total,
    )


def build_herd(
    sc: Scenario | dict[str, Any],
    specs: dict[str, LinkageSpec] | None = None,
    obstacles: str = "",
) -> HerdBuilt:
    """Build a multi-entity herd of walkers inside a single shared MuJoCo world (E4-04)."""
    doc = sc.model_dump(mode="json") if isinstance(sc, Scenario) else sc
    entities = doc.get("entities", [])
    world = doc.get("world", {})
    solver = doc.get("solver", {})
    from strandbeest_common.models.scenario_v1 import Solver

    sv = Solver.model_validate(solver)

    grav = world.get("gravity", 9.81)
    terrain_fric = world.get("terrain", {}).get("friction", 0.95)

    if sv.contact_stiffness is not None:
        # Same mass-normalised contact contract as the single-walker builder.
        damping = 2.0 * sv.contact_damping_ratio * math.sqrt(sv.contact_stiffness)
        geom_solref = f"{-sv.contact_stiffness} {-damping}"
    else:
        geom_solref = f"{sv.contact_solref} 1"

    torsos = []
    equalities = []
    actuators = []
    built_entities = {}

    for idx, ent in enumerate(entities):
        ename = ent.get("name", f"walker{idx}")
        prefix = f"{ename}_"
        comps = ent["components"]
        from strandbeest_common.models.scenario_v1 import Drive, Linkage, Walker

        w = Walker.model_validate(comps.get("body", {}))
        drive = Drive.model_validate(comps.get("drive", {}))
        link_cfg = Linkage.model_validate(comps.get("linkage", {}))

        if specs and ename in specs:
            spec = specs[ename]
        else:
            spec_src = link_cfg.spec
            if isinstance(spec_src, dict):
                spec = load_spec(spec_src)
            else:
                p = DATA / "jansen.json" if spec_src == "jansen" else Path(spec_src)
                d = json.loads(p.read_text())
                d["params"].update(link_cfg.params)
                spec = load_spec(d)

        placement = ent.get("placement", {})
        ox = float(placement.get("x", 0.0))
        oy = float(placement.get("y", 0.0))
        phase_off = float(placement.get("phase_offset", 0.0))

        torso_xml, eq_list, act_xml, ent_built = _build_walker_tree(
            w, drive, spec, prefix=prefix, offset_x=ox, offset_y=oy, phase_offset=phase_off
        )
        torsos.append(torso_xml)
        equalities.extend(eq_list)
        actuators.append(act_xml)
        built_entities[ename] = ent_built

    xml = f"""<mujoco model="{doc.get('name', 'herd')}">
  <compiler angle="radian"/>
  <option timestep="{sv.timestep}" integrator="implicitfast" solver="Newton" iterations="{sv.iterations}"{_tolerance_attribute(sv.tolerance)} cone="{sv.cone}" impratio="{sv.impratio}" noslip_iterations="{sv.noslip_iterations}" gravity="0 0 -{grav}"/>
  <default>
    <equality solref="{sv.solref_time} 1" solimp="{sv.solimp}"/>
    <geom solref="{geom_solref}"/>
  </default>
  <worldbody>
    {obstacles}
    <geom name="ground" type="plane" size="200 20 0.1" friction="{terrain_fric} 0.005 0.0001" contype="1" conaffinity="2" rgba="0.85 0.82 0.75 1"/>
    {"".join(torsos)}
  </worldbody>
  <equality>
    {"".join(equalities)}
  </equality>
  <actuator>
    {"".join(actuators)}
  </actuator>
</mujoco>"""
    return HerdBuilt(xml=xml, entities=built_entities)

