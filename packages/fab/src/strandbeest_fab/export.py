"""Write STL parts, a manifest, a bill of materials and assembly notes.

Everything here is a first-iteration design with stated assumptions (see `manifest["assumptions"]`); the first print is
expected to need adjustments to fits and clearances.
"""

from __future__ import annotations

import json
import math
import zipfile
from collections import Counter
from pathlib import Path

import trimesh
from shapely.geometry import LineString, Point, Polygon, box

from strandbeest_common import Design

from .checks import run_checks
from .parts import GAP_MM, LegPlan, axle_plan, plan_leg

SEG = 16  # circle quarter segments


def bar_polygon(length_mm: float, width_mm: float, hole_mm: float, first_hole_mm: float | None = None):
    """Stadium-shaped bar with a pin hole at each end; hole centres are exactly `length_mm` apart.
    `first_hole_mm` overrides the hole at x = 0 (used for the gripping bore of a crank arm)."""
    body = LineString([(0, 0), (length_mm, 0)]).buffer(width_mm / 2, cap_style="round", quad_segs=SEG)
    for x, d in ((0.0, first_hole_mm if first_hole_mm is not None else hole_mm), (length_mm, hole_mm)):
        body = body.difference(Point(x, 0).buffer(d / 2, quad_segs=SEG))
    return body


def frame_polygon(pivot_mm: tuple[float, float], width_mm: float, hole_mm: float, standoff_hole_mm: float | None = None):
    """Side plate carrying the hip axle (origin), the crank axle (pivot) and two standoff bolt holes."""
    margin = width_mm
    px, py = pivot_mm
    plate = box(min(0, px) - margin, min(0, py) - margin, max(0, px) + margin, max(0, py) + margin)
    for c in ((0.0, 0.0), (px, py)):
        plate = plate.difference(Point(*c).buffer(hole_mm / 2, quad_segs=SEG))
    if standoff_hole_mm:
        for c in _standoff_points(pivot_mm, width_mm):
            plate = plate.difference(Point(*c).buffer(standoff_hole_mm / 2, quad_segs=SEG))
    return plate


def _standoff_points(pivot_mm: tuple[float, float], width_mm: float) -> list[tuple[float, float]]:
    px, py = pivot_mm
    off = width_mm * 0.8
    return [(px / 2, py / 2 + off), (px / 2, py / 2 - off)]


def motor_bracket_polygon(pivot_mm, width_mm, hole_mm, standoff_hole_mm, shaft_pass_mm, spacing_mm, screw_mm):
    """Plate with a shaft pass-through at the crank axis and two motor screw holes on either side of it."""
    margin = width_mm
    px, py = pivot_mm
    plate = box(min(0, px) - margin, min(0, py) - margin, max(0, px) + margin, max(0, py) + margin)
    plate = plate.difference(Point(0, 0).buffer(hole_mm / 2, quad_segs=SEG))  # hip axle
    plate = plate.difference(Point(px, py).buffer(shaft_pass_mm / 2, quad_segs=SEG))  # motor shaft / coupler pass-through
    for c in _standoff_points(pivot_mm, width_mm):
        plate = plate.difference(Point(*c).buffer(standoff_hole_mm / 2, quad_segs=SEG))
    for dy in (-spacing_mm / 2, spacing_mm / 2):
        plate = plate.difference(Point(px, py + dy).buffer(screw_mm / 2, quad_segs=SEG))
    return plate


def phase_jig_polygon(radius_mm: float, notch_width_mm: float, notch_depth_mm: float, angles_deg: list[float], bore_mm: float):
    """Disc whose rim has a radial notch at every crank phase; the crank arms lie in the notches while the glue sets."""
    disc = Point(0, 0).buffer(radius_mm, quad_segs=SEG * 2)
    for a in angles_deg:
        r = math.radians(a)
        c, s = math.cos(r), math.sin(r)
        # rectangle from (radius - depth) to (radius + 1) along the angle, notch_width wide
        x0, x1, h = radius_mm - notch_depth_mm, radius_mm + 1.0, notch_width_mm / 2
        pts = [(x0, -h), (x1, -h), (x1, h), (x0, h)]
        disc = disc.difference(Polygon([(x * c - y * s, x * s + y * c) for x, y in pts]))
    return disc.difference(Point(0, 0).buffer(bore_mm / 2, quad_segs=SEG))


def tube_polygon(od_mm: float, id_mm: float):
    return Point(0, 0).buffer(od_mm / 2, quad_segs=SEG).difference(Point(0, 0).buffer(id_mm / 2, quad_segs=SEG))


def coupler_mesh(od_mm: float, length_mm: float, bore_a_mm: float, bore_b_mm: float, depth_mm: float) -> trimesh.Trimesh:
    """Cylinder with a blind bore from each end (motor shaft on one side, crankshaft on the other)."""
    body = trimesh.creation.cylinder(radius=od_mm / 2, height=length_mm, sections=64)
    for bore, sign in ((bore_a_mm, 1), (bore_b_mm, -1)):
        cut = trimesh.creation.cylinder(radius=bore / 2, height=depth_mm, sections=48)
        cut.apply_translation([0, 0, sign * (length_mm / 2 - depth_mm / 2 + 0.001)])
        body = trimesh.boolean.difference([body, cut], engine="manifold")
    body.apply_translation([0, 0, length_mm / 2])
    return body


def _extrude(poly, thickness: float) -> trimesh.Trimesh:
    return trimesh.creation.extrude_polygon(poly, thickness)


def _outline(poly) -> dict:
    """Exterior and interior rings as coordinate lists, for a 2D preview in the UI."""
    return {
        "exterior": [[round(x, 3), round(y, 3)] for x, y in poly.exterior.coords],
        "interiors": [[[round(x, 3), round(y, 3)] for x, y in r.coords] for r in poly.interiors],
    }


def export(design: Design, out_dir: Path) -> dict:
    out = Path(out_dir)
    (out / "stl").mkdir(parents=True, exist_ok=True)
    m, w, spec = design.mfg, design.walker, design.spec
    u = w["unit_m"] * 1000.0
    T = m["bar_thickness_mm"]
    W = m["bar_width_mm"]
    pin = m["pin_diameter_mm"]
    hole = pin + m["clearance_mm"]  # loose pin hole
    press = m.get("press_fit_offset_mm", -0.05)
    grip = pin + press  # gripping bore (crank arm on its shaft)
    motor = m.get("motor", {})
    motor_shaft = motor.get("shaft_diameter_mm", pin)
    n_legs = w["legs"]
    plan: LegPlan = plan_leg(design)
    axles = axle_plan(design, plan)
    checks = run_checks(design, plan, axles)

    parts: dict[str, dict] = {}

    def register(name: str, mesh: trimesh.Trimesh, kind: str, qty: int, note: str, poly=None):
        mesh.export(out / "stl" / f"{name}.stl")
        entry = {
            "file": f"stl/{name}.stl",
            "kind": kind,
            "qty": qty,
            "bounds_mm": [round(float(x), 3) for x in (mesh.bounds[1] - mesh.bounds[0])],
            "note": note,
        }
        if poly is not None:
            entry["outline"] = _outline(poly)
        parts[name] = entry

    def add_flat(name: str, poly, kind: str, qty: int, note: str = "", thickness: float = T):
        register(name, _extrude(poly, thickness), kind, qty, note, poly)

    # bars, by unique length
    by_len: Counter = Counter()
    labels: dict[str, list[str]] = {}
    for b in plan.bars:
        if b.key == "crank":
            continue
        key = f"bar_{b.length_mm:.1f}mm"
        by_len[key] += n_legs
        labels.setdefault(key, []).append(b.label)
    for key, qty in by_len.items():
        length = float(key.split("_")[1].replace("mm", ""))
        add_flat(key, bar_polygon(length, W, hole), "bar", qty, "used for " + ", ".join(labels[key]))

    # crank arm: gripping bore on the shaft end, loose pin hole on the crank-pin end
    add_flat(
        f"crank_arm_{plan.crank_mm:.1f}mm",
        bar_polygon(plan.crank_mm, W, hole, first_hole_mm=grip),
        "crank",
        n_legs,
        "tight bore at the shaft end (glue it), loose hole at the crank pin; set the phase with the jig",
    )

    px, py = spec.pivot[0] * u, spec.pivot[1] * u
    standoff_hole = pin + m["clearance_mm"]
    add_flat("frame_plate", frame_polygon((px, py), W, hole, standoff_hole), "frame", 1, "side plate opposite the motor")
    add_flat(
        "motor_bracket",
        motor_bracket_polygon(
            (px, py),
            W,
            hole,
            standoff_hole,
            shaft_pass_mm=motor_shaft + 1.6,
            spacing_mm=motor.get("mount_hole_spacing_mm", 9.0),
            screw_mm=motor.get("mount_hole_diameter_mm", 1.8),
        ),
        "frame",
        1,
        "side plate on the motor side; motor screws to its outer face, shaft passes through to the coupler",
    )

    # phase jig
    phases = [round(360.0 * i / n_legs, 2) for i in range(n_legs)]
    jig_r = plan.crank_mm + W
    add_flat(
        "phase_jig",
        phase_jig_polygon(jig_r, W + 0.6, 6.0, phases, grip + 0.3),
        "jig",
        1,
        "slide onto the crankshaft; lay crank arm i in notch i; glue; remove",
    )

    coupler_len = 2 * 6.0 + 2.0
    inner_width_for_standoff = axles.inner_width_mm + coupler_len

    # spacers (tubes) along the axles and standoffs between the plates
    spacer_od = pin + 4.0
    spacer_counts: Counter = Counter()
    for length in axles.hip_spacers + axles.crank_spacers:
        spacer_counts[round(length, 2)] += 1
    for length, qty in sorted(spacer_counts.items()):
        add_flat(
            f"spacer_{length:.2f}mm",
            tube_polygon(spacer_od, hole),
            "spacer",
            qty,
            "loose tube on the hip axle or crankshaft, fills the gaps between layers and legs",
            thickness=length,
        )
    add_flat(
        f"standoff_{inner_width_for_standoff:.1f}mm",
        tube_polygon(spacer_od, standoff_hole),
        "spacer",
        2,
        "joins the two frame plates; a bolt of the same nominal diameter runs through",
        thickness=inner_width_for_standoff,
    )

    # shaft coupler: sits inside the frame against the motor-side plate; the motor shaft enters from the plate side
    register(
        "shaft_coupler",
        coupler_mesh(spacer_od + 2.0, coupler_len, motor_shaft + press, grip, 6.0),
        "coupler",
        1,
        "motor shaft in one end, crankshaft in the other; glue or set screw",
    )

    # pins and shafts
    pin_rows = []
    for point, layers in sorted(plan.pins.items()):
        if point in ("G", "P"):
            continue
        span = max(layers) - min(layers) + 1
        length = span * (T + GAP_MM) + 2.0
        pin_rows.append({"point": point, "layers": sorted(set(layers)), "length_mm": round(length, 1), "qty": n_legs})
    legs_width = axles.inner_width_mm
    inner_width = legs_width + coupler_len  # between the plates: the legs plus the coupler
    shaft_len = inner_width + 2 * T + 6.0
    crankshaft_len = 6.0 + legs_width + T + 3.0  # 6 mm in the coupler, through the legs, 3 mm past the far plate
    shared = [
        {"name": "hip axle (through G)", "length_mm": round(shaft_len, 1), "diameter_mm": pin},
        {"name": "crankshaft (through P)", "length_mm": round(crankshaft_len, 1), "diameter_mm": pin},
        {"name": "standoff bolts", "length_mm": round(inner_width + 2 * T + 4.0, 1), "diameter_mm": pin, "qty": 2},
    ]

    manifest = {
        "design": design.name,
        "parts": parts,
        "pins": pin_rows,
        "shared_axles": shared,
        "crank_phase_deg": phases,
        "layers_per_leg": plan.layers,
        "layer_of_part": {b.key: b.layer for b in plan.bars},
        "leg_pitch_mm": round(axles.leg_pitch_mm, 2),
        "legs_width_mm": round(legs_width, 2),
        "inner_width_mm": round(inner_width, 2),
        "washers": {"count": axles.washers, "thickness_mm": GAP_MM},
        "checks": [c.__dict__ for c in checks],
        "assumptions": [
            f"washer gap {GAP_MM} mm between layers",
            "pin retention allowance 2 mm",
            f"press-fit offset {press} mm for gripping bores; FDM holes print small, expect to ream or sand",
            "motor is N20-class: two screw holes on a spacing from the Design, its shaft passes through a hole 1.6 mm larger; the shaft is assumed long enough to reach 6 mm into the coupler",
            "clearance and pin size from the Design",
            "loads, wear and flex of printed parts are not modelled",
        ],
    }
    (out / "parts.json").write_text(json.dumps(manifest, indent=2))
    (out / "printability.json").write_text(json.dumps([c.__dict__ for c in checks], indent=2))
    (out / "BOM.md").write_text(_bom(design, manifest))
    (out / "ASSEMBLY.md").write_text(_assembly(design, manifest, plan, axles))
    with zipfile.ZipFile(out / f"{design.name}-print-pack.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.rglob("*")):
            if f.is_file() and f.suffix != ".zip":
                z.write(f, f.relative_to(out))
    return manifest


def _bom(d: Design, mf: dict) -> str:
    m = d.mfg
    lines = [
        f"# Bill of materials: {d.name}",
        "",
        f"Material: {m['material']}, {m['bar_thickness_mm']} mm thick, bar width {m['bar_width_mm']} mm",
        "",
        "## Printed parts",
        "",
        "| part | qty | size (mm) | note |",
        "|---|---|---|---|",
    ]
    for name, p in mf["parts"].items():
        lines.append(f"| {name} | {p['qty']} | {p['bounds_mm'][0]} x {p['bounds_mm'][1]} x {p['bounds_mm'][2]} | {p['note']} |")
    lines += [
        "",
        "## Pins, shafts and bolts (not printed)",
        "",
        f"Nominal diameter {m['pin_diameter_mm']} mm (bolt, rod or filament). Pin lengths include layer gaps and a 2 mm allowance.",
        "",
        "| item | qty | length (mm) |",
        "|---|---|---|",
    ]
    for r in mf["pins"]:
        lines.append(f"| leg pin at {r['point']} | {r['qty']} | {r['length_mm']} |")
    for a in mf["shared_axles"]:
        lines.append(f"| {a['name']} | {a.get('qty', 1)} | {a['length_mm']} |")
    lines += [
        "",
        f"Washers: {mf['washers']['count']} x {mf['washers']['thickness_mm']} mm (one per occupied slot on each axle).",
        "",
        "Also needed: retention for the pins (nuts, e-clips or glue), a geared DC motor (N20-class assumed) and its supply.",
        "",
        "Assumptions: " + "; ".join(mf["assumptions"]) + ".",
    ]
    return "\n".join(lines) + "\n"


def _assembly(d: Design, mf: dict, plan: LegPlan, axles) -> str:
    lines = [
        f"# Assembly notes: {d.name}",
        "",
        "Generated from the Design. Read printability.json first. The first print is a test: expect to adjust clearances.",
        "",
        "## Layers (per leg)",
        "",
        f"Each leg stacks {mf['layers_per_leg']} layers along the pin axis (layer 0 on the side you choose). Parts per layer:",
        "",
    ]
    for layer in range(plan.layers):
        lines.append(f"- layer {layer}: " + ", ".join(b.label for b in plan.bars if b.layer == layer))
    lines += [
        "",
        f"Legs sit {mf['leg_pitch_mm']} mm apart on the axles; the frame plates are {mf['inner_width_mm']} mm apart (inside faces: the legs plus the {mf['inner_width_mm'] - mf['legs_width_mm']:.0f} mm coupler).",
        "",
        "## Crank phases",
        "",
        "Crank arm i, counting along the shaft from the motor side, is fixed at these angles (degrees, in the walking direction):",
        "",
        ", ".join(str(p) for p in mf["crank_phase_deg"]),
        "",
        "## Order",
        "",
        "1. Print one bar and one pin; the bar must turn freely without wobble. If not, change `clearance_mm` in the Design and re-export.",
        "2. Assemble ONE leg flat on a table with its pins and turn the crank arm by hand: the foot should trace the D-shaped path.",
        "3. Thread legs onto the hip axle (through the G holes) in order, with spacers and washers between layers and legs as in the BOM.",
        "4. Slide the crankshaft through the crank arms' tight bores (ream or sand the bores if needed). Put the phase jig on the shaft, lay each crank arm in its notch, glue, let set, remove the jig.",
        "5. Connect each leg's crank pin to its bars (the loose hole at the free end of each arm).",
        "6. Fit the frame plate and motor bracket on the axles and join them with the standoffs.",
        "7. Screw the motor to the bracket, couple its shaft to the crankshaft with the coupler.",
        "",
        "Stated limits: loads, wear and flex of printed pins are not modelled; coupler and motor-bracket geometry are assumptions for an N20-class motor.",
    ]
    return "\n".join(lines) + "\n"
