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


def _f(v: float) -> str:
    return f"{v:.9g}"


@dataclass
class _Bar:
    name: str
    start: str  # linkage point the bar is hinged at (the bar's body origin)
    end: str
    mass: float


def build(sc: Scenario | SimConfig, spec: LinkageSpec, obstacles: str = "") -> Built:
    """`obstacles` is MJCF for the static blocks of the terrain (made by the MuJoCo adapter from the terrain plan)."""
    sc = sim_config(sc)
    w = sc.walker
    u = w.unit
    n = w.legs
    phases = [2 * math.pi * i / n for i in range(n)]
    poses = []
    for ph in phases:
        p = solve_pose(spec, ph)  # theta_i0 = phase_i  (psi = 0 for leg 0)
        if p is None:
            raise ValueError("linkage cannot assemble at the initial crank angle")
        poses.append(p)

    lowest = min(p[spec.foot][1] for p in poses) * u
    hip_h = -lowest + w.foot_radius

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

        # two bars per joint, one from each centre; the first one owns the joint point
        bars_at: dict[str, list[_Bar]] = {}
        owner_of: dict[str, str] = {"C": f"crank{i}"}  # point -> name of the body that owns it (G handled apart)
        by_name: dict[str, _Bar] = {}
        for j in spec.joints:
            for k, (c, r) in enumerate(zip(j.centers, j.radii)):
                b = _Bar(f"bar{i}_{j.id}{k}", c, j.id, mass_of(spec.val(r)))
                bars_at.setdefault(c, []).append(b)
                by_name[b.name] = b
            owner_of[j.id] = f"bar{i}_{j.id}0"

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
                foot_done.append(True)  # both bars ending at the foot share one sphere: two coincident spheres would collide with each other
                geoms += (
                    f'<geom name="foot_{b.name}" type="sphere" pos="{_f(rel[0])} 0 {_f(rel[1])}" size="{_f(w.foot_radius)}" '
                    f'mass="1e-6" friction="{_f(w.foot_friction)} 0.005 0.0001" contype="{1 if LEGACY_FOOT_BUG else 2}" conaffinity="1" rgba="0.9 0.45 0.25 1"/>'
                )
            kids = ""
            if owner_of.get(b.end) == b.name:
                kids = "".join(emit(c, ps, 0.0) for c in bars_at.get(b.end, []))
            return (
                f'<body name="{b.name}" pos="{_f(pos[0])} {_f(pos[1])} {_f(pos[2])}">'
                f'<joint name="{b.name}" type="hinge" axis="0 1 0"/>{geoms}{kids}</body>'
            )

        # bars hinged at the hip G hang from the torso (offset laterally by this leg's y)
        torso_children.extend(emit(b, (0.0, 0.0), y) for b in bars_at.get("G", []))
        # crank: hinge at the pivot; its geometry already points along theta0 (the body frame is the q = ref pose)
        crank_vec = ((tip[0] - px) * u, (tip[1] - py) * u)
        crank_kids = "".join(emit(b, (px, py), 0.0) for b in bars_at.get("C", []))
        torso_children.append(
            f'<body name="crank{i}" pos="{_f(px * u)} {_f(y)} {_f(py * u)}">'
            f'<joint name="crank{i}" type="hinge" axis="0 1 0" ref="{_f(-phases[i])}"/>'
            f'<geom type="capsule" fromto="0 0 0 {_f(crank_vec[0])} 0 {_f(crank_vec[1])}" size="{_f(w.bar_radius)}" '
            f'mass="{_f(crank_mass)}" contype="0" conaffinity="0" rgba="0.2 0.2 0.25 1"/>{crank_kids}</body>'
        )

        # loop closures: the second bar at each joint connects to the first at the joint's position
        for j in spec.joints:
            first, second = f"bar{i}_{j.id}0", f"bar{i}_{j.id}1"
            at = pose[j.id]
            s2 = pose[by_name[second].start]
            eq.append(
                f'<connect body1="{second}" body2="{first}" anchor="{_f((at[0] - s2[0]) * u)} 0 {_f((at[1] - s2[1]) * u)}"/>'
            )
        if i > 0:
            eq.append(f'<joint joint1="crank{i}" joint2="crank0" polycoef="0 1 0 0 0"/>')

    sv = sc.solver
    force_attr = f' forcelimited="true" forcerange="{-sc.drive.max_torque} {sc.drive.max_torque}"' if sc.drive.max_torque else ""
    if sv.contact_stiffness is not None:
        # direct (negative) solref = stiffness (1/s^2, mass-normalised) and damping (1/s); damping from a damping ratio
        m_eff = (torso_mass + n * per_leg_mass) / 5.0
        damping = 2.0 * sv.contact_damping_ratio * math.sqrt(sv.contact_stiffness * m_eff)
        geom_solref = f"{-sv.contact_stiffness} {-damping}"
    else:
        geom_solref = f"{sv.contact_solref} 1"
    pitch_joint = '<joint name="tp" type="hinge" axis="0 1 0"/>' if w.pitch == "free" else ""
    half_y = max(w.lateral_spacing * n / 2, 0.05)
    xml = f"""<mujoco model="{sc.name}">
  <compiler angle="radian"/>
  <option timestep="{sv.timestep}" integrator="implicitfast" solver="Newton" iterations="{sv.iterations}" cone="{sv.cone}" impratio="{sv.impratio}" noslip_iterations="{sv.noslip_iterations}" gravity="0 0 -{sc.environment.gravity}"/>
  <default>
    <equality solref="{sv.solref_time} 1" solimp="{sv.solimp}"/>
    <geom solref="{geom_solref}"/>
  </default>
  <worldbody>
    {obstacles}
    <geom name="ground" type="plane" size="200 20 0.1" friction="{sc.terrain.friction} 0.005 0.0001" contype="1" conaffinity="2" rgba="0.85 0.82 0.75 1"/>
    <body name="torso" pos="0 0 {_f(hip_h)}">
      <joint name="tx" type="slide" axis="1 0 0"/>
      <joint name="tz" type="slide" axis="0 0 1"/>
      {pitch_joint}
      <geom type="box" size="{_f(w.body_length / 2)} {_f(half_y)} 0.03" mass="{_f(torso_mass)}" contype="0" conaffinity="0" rgba="0.15 0.15 0.2 1"/>
      {"".join(torso_children)}
    </body>
  </worldbody>
  <equality>
    {"".join(eq)}
  </equality>
  <actuator>
    <position name="drive" joint="crank0" kp="{sc.drive.kp}" kv="{sc.drive.kv}" ctrlrange="-1e6 1e6"{force_attr}/>
  </actuator>
</mujoco>"""
    return Built(
        xml=xml,
        n_legs=n,
        crank_joint="crank0",
        crank_q0=-phases[0],
        actuator="drive",
        hip_height=hip_h,
        bar_mass_total=n * per_leg_mass,
    )
