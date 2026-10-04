"""Write STL parts, a manifest, a bill of materials and assembly notes."""

from __future__ import annotations

import json
import math
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import LineString, Point, box

from strandbeest_common import Design

from .checks import Check, run_checks
from .parts import GAP_MM, plan_leg


def bar_polygon(length_mm: float, width_mm: float, hole_mm: float):
    """Stadium-shaped bar with a pin hole at each end; hole centres are exactly `length_mm` apart."""
    body = LineString([(0, 0), (length_mm, 0)]).buffer(width_mm / 2, cap_style="round", quad_segs=8)
    for x in (0.0, length_mm):
        body = body.difference(Point(x, 0).buffer(hole_mm / 2, quad_segs=8))
    return body


def frame_polygon(pivot_mm: tuple[float, float], width_mm: float, hole_mm: float):
    """Side plate carrying the hip axle (origin) and the crank axle (pivot)."""
    margin = width_mm
    px, py = pivot_mm
    plate = box(min(0, px) - margin, min(0, py) - margin, max(0, px) + margin, max(0, py) + margin)
    for c in ((0.0, 0.0), (px, py)):
        plate = plate.difference(Point(*c).buffer(hole_mm / 2, quad_segs=8))
    return plate


def _mesh(poly, thickness: float) -> trimesh.Trimesh:
    return trimesh.creation.extrude_polygon(poly, thickness)


def export(design: Design, out_dir: Path) -> dict:
    out = Path(out_dir)
    (out / "stl").mkdir(parents=True, exist_ok=True)
    m, w, spec = design.mfg, design.walker, design.spec
    u = w["unit_m"] * 1000.0
    hole = m["pin_diameter_mm"] + m["clearance_mm"]
    plan = plan_leg(design)
    checks = run_checks(design, plan)
    n_legs = w["legs"]

    # unique bar parts by rounded length
    parts: dict[str, dict] = {}

    def add_part(name: str, poly, kind: str, qty: int, note: str = ""):
        mesh = _mesh(poly, m["bar_thickness_mm"])
        path = out / "stl" / f"{name}.stl"
        mesh.export(path)
        parts[name] = {"file": f"stl/{name}.stl", "kind": kind, "qty": qty,
                       "bounds_mm": [round(float(x), 3) for x in (mesh.bounds[1] - mesh.bounds[0])], "note": note}

    by_len = Counter()
    labels: dict[str, list[str]] = {}
    for b in plan.bars:
        if b.key == "crank":
            continue
        key = f"bar_{b.length_mm:.1f}mm"
        by_len[key] += n_legs
        labels.setdefault(key, []).append(b.label)
    for key, qty in by_len.items():
        length = float(key.split("_")[1].replace("mm", ""))
        add_part(key, bar_polygon(length, m["bar_width_mm"], hole), "bar", qty, "used for " + ", ".join(labels[key]))
    add_part(f"crank_{plan.crank_mm:.1f}mm", bar_polygon(plan.crank_mm, m["bar_width_mm"], hole), "crank", n_legs,
             "crank arm; fix to the crankshaft at the listed phase angle")
    px, py = spec.pivot[0] * u, spec.pivot[1] * u
    add_part("frame_plate", frame_polygon((px, py), m["bar_width_mm"], hole), "frame", 2, "one per side of the legs")

    # pins: one per leg at each moving pivot; lengths from the layers stacked there
    pin_rows = []
    for point, layers in sorted(plan.pins.items()):
        if point in ("G", "P"):
            continue  # shared axles, handled below
        span = max(layers) - min(layers) + 1
        length = span * (m["bar_thickness_mm"] + GAP_MM) + 2.0  # + ends for retention
        pin_rows.append({"point": point, "layers": sorted(set(layers)), "length_mm": round(length, 1), "qty": n_legs})
    axle_len = n_legs * plan.layers * (m["bar_thickness_mm"] + GAP_MM) + 2 * m["bar_thickness_mm"] + 10
    phases = [round(360.0 * i / n_legs, 2) for i in range(n_legs)]

    manifest = {
        "design": design.name,
        "parts": parts,
        "pins": pin_rows,
        "shared_axles": [{"name": "hip axle (through G)", "length_mm": round(axle_len, 1)},
                         {"name": "crankshaft (through P)", "length_mm": round(axle_len, 1)}],
        "crank_phase_deg": phases,
        "layers_per_leg": plan.layers,
        "layer_of_part": {b.key: b.layer for b in plan.bars},
        "checks": [c.__dict__ for c in checks],
        "assumptions": ["washer gap 0.6 mm between layers", "pin retention allowance 2 mm", "clearance and pin size from the Design"],
    }
    (out / "parts.json").write_text(json.dumps(manifest, indent=2))
    (out / "printability.json").write_text(json.dumps([c.__dict__ for c in checks], indent=2))
    (out / "BOM.md").write_text(_bom(design, manifest))
    (out / "ASSEMBLY.md").write_text(_assembly(design, manifest, plan))
    with zipfile.ZipFile(out / f"{design.name}-print-pack.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in [*out.rglob("*")]:
            if f.is_file() and f.suffix != ".zip":
                z.write(f, f.relative_to(out))
    return manifest


def _bom(d: Design, mf: dict) -> str:
    m = d.mfg
    lines = [f"# Bill of materials: {d.name}", "", f"Material: {m['material']}, {m['bar_thickness_mm']} mm thick, bar width {m['bar_width_mm']} mm", "",
             "## Printed parts", "", "| part | qty | size (mm) | note |", "|---|---|---|---|"]
    for name, p in mf["parts"].items():
        lines.append(f"| {name} | {p['qty']} | {p['bounds_mm'][0]} x {p['bounds_mm'][1]} x {p['bounds_mm'][2]} | {p['note']} |")
    lines += ["", "## Pins and axles (not printed)", "", f"Nominal pin diameter {m['pin_diameter_mm']} mm (bolt, rod or filament). Lengths include layer gaps and a 2 mm allowance.", "",
              "| pivot | per leg x legs | length (mm) |", "|---|---|---|"]
    for r in mf["pins"]:
        lines.append(f"| {r['point']} | {r['qty']} | {r['length_mm']} |")
    for a in mf["shared_axles"]:
        lines.append(f"| {a['name']} | 1 | {a['length_mm']} |")
    lines += ["", "Also needed: washers/spacers (about 0.6 mm), retention (nuts, e-clips or glue), a motor with gearbox, a power supply."]
    return "\n".join(lines) + "\n"


def _assembly(d: Design, mf: dict, plan) -> str:
    lines = [f"# Assembly notes: {d.name}", "", "Generated from the Design; check the printability report first.", "",
             "## Layers", "", f"Each leg stacks {mf['layers_per_leg']} layers along the pin axis (layer 0 is outermost on the side you choose). Parts per layer:", ""]
    for layer in range(plan.layers):
        names = ", ".join(b.label for b in plan.bars if b.layer == layer)
        lines.append(f"- layer {layer}: {names}")
    lines += ["", "## Crank phases", "", "Fix the crank arms to the crankshaft at these angles (degrees, in order along the shaft):", "",
              ", ".join(str(p) for p in mf["crank_phase_deg"]), "",
              "## Order", "",
              "1. Check clearance with one test bar and one pin; they should turn freely without wobble.",
              "2. Assemble one leg flat on a table and turn the crank by hand; the foot should trace the D-shaped path.",
              "3. Repeat for every leg, mount them on the hip axle and crankshaft in order, set the crank phases.",
              "4. Fit the frame plates, motor and gearbox.", "",
              "Stated limits: loads, wear and flex of printed pins are not modelled; treat the first print as a test."]
    return "\n".join(lines) + "\n"
