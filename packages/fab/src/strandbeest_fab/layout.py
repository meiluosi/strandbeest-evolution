"""2D laser-cut layout, nesting, kerf offset compensation, and SVG/DXF export.

Physical laser cutters remove a beam width of material (kerf width w_kerf).
To ensure finished mechanical parts match design dimensions:
- Outer perimeters must be expanded outward by +w_kerf / 2.
- Inner holes must be shrunk inward by -w_kerf / 2.
- Press-fit holes (e.g. crank arm shaft bore) can be compensated with an explicit
  undersize offset (e.g. -0.05 mm) to guarantee an interference fit.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import shapely.affinity
from shapely.geometry import MultiPolygon, Point, Polygon, box

from strandbeest_common import Design

from .parts import LegPlan, plan_leg


@dataclass
class LaserPart:
    """A 2D mechanical part profile for laser cutting."""

    name: str
    poly: Polygon | MultiPolygon
    qty: int = 1
    kind: str = "bar"
    label: str = ""
    thickness_mm: float | None = None
    engravings: list[tuple[float, float, str]] = field(default_factory=list)


@dataclass
class PlacedPart:
    """A part placed onto a laser sheet at a specific position."""

    name: str
    poly: Polygon
    x: float
    y: float
    label: str = ""
    kind: str = ""
    part_index: int = 0


@dataclass
class LayoutResult:
    """Result of nesting parts onto a laser cutting sheet."""

    placed_parts: list[PlacedPart]
    width_mm: float
    height_mm: float
    sheet_count: int = 1


def coords_to_svg_path(coords: Sequence[tuple[float, float]]) -> str:
    """Convert a sequence of (x, y) coordinates into an SVG path data string."""
    if not coords:
        return ""
    pts = [f"{x:.4f} {y:.4f}" for x, y in coords]
    return f"M {pts[0]} " + " ".join(f"L {p}" for p in pts[1:]) + " Z"


def compensate_kerf(
    poly: Polygon | MultiPolygon,
    kerf_width_mm: float = 0.2,
    press_fit_offset_mm: float = 0.0,
    press_fit_hole_indices: Sequence[int] | None = None,
    part_name: str = "",
    press_fit_holes: Mapping[str, float] | None = None,
    quad_segs: int = 32,
    join_style: str = "mitre",
    mitre_limit: float = 5.0,
) -> Polygon | MultiPolygon:
    """Compensate a 2D profile for laser cutting beam kerf and press-fit hole undersize.

    - Exterior expands by +kerf_width_mm / 2.
    - Interior holes contract by -kerf_width_mm / 2.
    - Press-fit holes contract additionally by effective_press_offset / 2.
    """
    if isinstance(poly, MultiPolygon):
        comps = [
            compensate_kerf(
                p,
                kerf_width_mm=kerf_width_mm,
                press_fit_offset_mm=press_fit_offset_mm,
                press_fit_hole_indices=press_fit_hole_indices,
                part_name=part_name,
                press_fit_holes=press_fit_holes,
                quad_segs=quad_segs,
                join_style=join_style,
                mitre_limit=mitre_limit,
            )
            for p in poly.geoms
        ]
        return MultiPolygon([c for c in comps if isinstance(c, Polygon)])

    # Determine effective press fit offset for this part
    effective_press_offset = press_fit_offset_mm
    if press_fit_holes and part_name:
        for k, v in press_fit_holes.items():
            if k.lower() in part_name.lower():
                effective_press_offset = v
                break

    if kerf_width_mm == 0.0 and effective_press_offset == 0.0:
        return poly

    d = kerf_width_mm / 2.0

    # Expand exterior perimeter outward by +d
    ext_poly = Polygon(poly.exterior)
    ext_buffered = ext_poly.buffer(d, quad_segs=quad_segs, join_style=join_style, mitre_limit=mitre_limit)
    if isinstance(ext_buffered, MultiPolygon):
        ext_buffered = max(ext_buffered.geoms, key=lambda g: g.area)

    if not poly.interiors:
        return ext_buffered

    # Identify press-fit hole index if not explicitly specified
    pf_idx = None
    if effective_press_offset != 0.0 and press_fit_hole_indices is None:
        if len(poly.interiors) == 1:
            pf_idx = 0
        else:
            # For parts with multiple holes (like a crank arm), hole near origin (0, 0) is the shaft bore
            centroids = [Polygon(r).centroid for r in poly.interiors]
            origin_dists = [math.hypot(c.x, c.y) for c in centroids]
            pf_idx = origin_dists.index(min(origin_dists))

    # Contract inner holes inward by -d (plus press-fit offset)
    holes_buffered: list[Polygon] = []
    for i, ring in enumerate(poly.interiors):
        h_poly = Polygon(ring)
        is_pf = (
            (i in press_fit_hole_indices)
            if press_fit_hole_indices is not None
            else (effective_press_offset != 0.0 and (pf_idx is None or i == pf_idx))
        )
        delta_r = -d + (effective_press_offset / 2.0 if is_pf else 0.0)

        h_buf = h_poly.buffer(delta_r, quad_segs=quad_segs, join_style=join_style, mitre_limit=mitre_limit)
        if isinstance(h_buf, MultiPolygon):
            h_buf = max(h_buf.geoms, key=lambda g: g.area)
        if not h_buf.is_empty and h_buf.area > 1e-6:
            holes_buffered.append(h_buf)

    result = ext_buffered
    for h in holes_buffered:
        result = result.difference(h)

    if isinstance(result, MultiPolygon):
        result = max(result.geoms, key=lambda g: g.area)

    return result


def _extract_laser_parts(parts_input: Any) -> list[LaserPart]:
    """Convert various inputs (Design, dict, list) into a list of LaserPart objects."""
    if isinstance(parts_input, Design):
        from .export import bar_polygon, frame_polygon, motor_bracket_polygon, phase_jig_polygon

        d = parts_input
        m, w, spec = d.mfg, d.walker, d.spec
        u = w["unit_m"] * 1000.0
        T = m["bar_thickness_mm"]
        W = m["bar_width_mm"]
        pin = m["pin_diameter_mm"]
        hole = pin + m["clearance_mm"]
        press = m.get("press_fit_offset_mm", -0.05)
        grip = pin + press
        motor = m.get("motor", {})
        motor_shaft = motor.get("shaft_diameter_mm", pin)
        n_legs = w["legs"]
        plan: LegPlan = plan_leg(d)

        laser_parts: list[LaserPart] = []
        from collections import Counter

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
            lbl = ", ".join(sorted(set(labels[key])))
            laser_parts.append(LaserPart(key, bar_polygon(length, W, hole), qty=qty, kind="bar", label=lbl, thickness_mm=T))

        laser_parts.append(
            LaserPart(
                f"crank_arm_{plan.crank_mm:.1f}mm",
                bar_polygon(plan.crank_mm, W, hole, first_hole_mm=grip),
                qty=n_legs,
                kind="crank",
                label="crank",
                thickness_mm=T,
            )
        )

        px, py = spec.pivot[0] * u, spec.pivot[1] * u
        standoff_hole = pin + m["clearance_mm"]
        laser_parts.append(
            LaserPart("frame_plate", frame_polygon((px, py), W, hole, standoff_hole), qty=1, kind="frame", label="frame", thickness_mm=T)
        )
        laser_parts.append(
            LaserPart(
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
                qty=1,
                kind="frame",
                label="motor",
                thickness_mm=T,
            )
        )

        phases = [round(360.0 * i / n_legs, 2) for i in range(n_legs)]
        jig_r = plan.crank_mm + W
        laser_parts.append(
            LaserPart(
                "phase_jig",
                phase_jig_polygon(jig_r, W + 0.6, 6.0, phases, grip + 0.3),
                qty=1,
                kind="jig",
                label="jig",
                thickness_mm=T,
            )
        )
        return laser_parts

    if isinstance(parts_input, (Polygon, MultiPolygon)):
        return [LaserPart("part", parts_input, qty=1)]

    if isinstance(parts_input, Mapping):
        # Can be manifest["parts"]
        laser_parts = []
        for name, data in parts_input.items():
            if isinstance(data, (Polygon, MultiPolygon)):
                laser_parts.append(LaserPart(name, data, qty=1))
            elif isinstance(data, dict) and "outline" in data:
                ext = data["outline"]["exterior"]
                ints = data["outline"].get("interiors", [])
                poly = Polygon(ext, ints)
                qty = data.get("qty", 1)
                kind = data.get("kind", "part")
                laser_parts.append(LaserPart(name, poly, qty=qty, kind=kind))
            elif isinstance(data, LaserPart):
                laser_parts.append(data)
        return laser_parts

    if isinstance(parts_input, (list, tuple)):
        laser_parts = []
        for i, item in enumerate(parts_input):
            if isinstance(item, LaserPart):
                laser_parts.append(item)
            elif isinstance(item, (Polygon, MultiPolygon)):
                laser_parts.append(LaserPart(f"part_{i}", item, qty=1))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                name, poly = item[0], item[1]
                qty = item[2] if len(item) > 2 else 1
                laser_parts.append(LaserPart(name, poly, qty=qty))
        return laser_parts

    raise TypeError(f"Unsupported parts input type: {type(parts_input)}")


def layout_parts(
    parts_input: Any,
    sheet_width_mm: float | None = None,
    sheet_height_mm: float | None = None,
    margin_mm: float = 5.0,
    spacing_mm: float = 3.0,
    kerf_width_mm: float = 0.2,
    press_fit_holes: Mapping[str, float] | None = None,
) -> LayoutResult:
    """Nest laser cut parts onto a sheet with shelf packing and kerf compensation."""
    parts = _extract_laser_parts(parts_input)
    placed: list[PlacedPart] = []

    # Flatten parts according to quantities
    flat_items: list[tuple[str, Polygon, str, str]] = []
    for p in parts:
        comp_poly = compensate_kerf(
            p.poly,
            kerf_width_mm=kerf_width_mm,
            part_name=p.name,
            press_fit_holes=press_fit_holes,
        )
        if isinstance(comp_poly, MultiPolygon):
            comp_poly = max(comp_poly.geoms, key=lambda g: g.area)

        for _ in range(p.qty):
            flat_items.append((p.name, comp_poly, p.label, p.kind))

    if not flat_items:
        return LayoutResult([], width_mm=sheet_width_mm or 0.0, height_mm=sheet_height_mm or 0.0)

    # Auto-determine sheet width if none given
    if sheet_width_mm is None:
        total_area = sum((item[1].bounds[2] - item[1].bounds[0]) * (item[1].bounds[3] - item[1].bounds[1]) for item in flat_items)
        max_part_w = max(item[1].bounds[2] - item[1].bounds[0] for item in flat_items)
        sheet_width_mm = max(250.0, max_part_w + 2 * margin_mm, math.sqrt(total_area) * 1.4)

    # Shelf packing
    current_x = margin_mm
    current_y = margin_mm
    row_height = 0.0
    max_x = current_x
    max_y = current_y

    for idx, (name, poly, label, kind) in enumerate(flat_items):
        minx, miny, maxx, maxy = poly.bounds
        pw = maxx - minx
        ph = maxy - miny

        if current_x + pw + margin_mm > sheet_width_mm and current_x > margin_mm:
            # Advance to next shelf
            current_x = margin_mm
            current_y += row_height + spacing_mm
            row_height = 0.0

        # Translate part so local min bounds land at (current_x, current_y)
        dx = current_x - minx
        dy = current_y - miny
        placed_poly = shapely.affinity.translate(poly, dx, dy)
        placed.append(
            PlacedPart(
                name=name,
                poly=placed_poly,
                x=current_x,
                y=current_y,
                label=label,
                kind=kind,
                part_index=idx,
            )
        )

        row_height = max(row_height, ph)
        current_x += pw + spacing_mm
        max_x = max(max_x, current_x - spacing_mm + margin_mm)
        max_y = max(max_y, current_y + ph + margin_mm)

    total_w = max(sheet_width_mm, max_x)
    total_h = max(sheet_height_mm or 0.0, max_y)

    return LayoutResult(placed, width_mm=round(total_w, 2), height_mm=round(total_h, 2))


def export_laser_svg(
    parts: Any,
    kerf_width_mm: float = 0.2,
    press_fit_holes: Mapping[str, float] | None = None,
    sheet_width_mm: float | None = None,
    sheet_height_mm: float | None = None,
    margin_mm: float = 5.0,
    spacing_mm: float = 3.0,
    layout: bool = True,
    out_path: str | Path | None = None,
    include_labels: bool = True,
    cut_color: str = "#ff0000",
    mark_color: str = "#0000ff",
    stroke_width_mm: float = 0.1,
) -> str:
    """Generate a clean 2D laser-cut SVG with kerf compensation and standard cut/mark layers.

    - Cut paths (outer contours & inner holes) are placed in group with id="cut" and red stroke.
    - Engraving text/marks are placed in group with id="mark" and blue stroke.
    """
    if isinstance(parts, (Polygon, MultiPolygon)) and not layout:
        # Direct export of a single polygon without layout packing
        comp = compensate_kerf(
            parts,
            kerf_width_mm=kerf_width_mm,
            press_fit_holes=press_fit_holes,
        )
        if isinstance(comp, MultiPolygon):
            comp = max(comp.geoms, key=lambda g: g.area)

        minx, miny, maxx, maxy = comp.bounds
        w = maxx - minx
        h = maxy - miny
        vb_x = minx - margin_mm
        vb_y = miny - margin_mm
        vb_w = w + 2 * margin_mm
        vb_h = h + 2 * margin_mm

        cut_paths = [f'<path d="{coords_to_svg_path(comp.exterior.coords)}" />']
        for ring in comp.interiors:
            cut_paths.append(f'<path d="{coords_to_svg_path(ring.coords)}" />')

        svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     viewBox="{vb_x:.4f} {vb_y:.4f} {vb_w:.4f} {vb_h:.4f}"
     width="{vb_w:.4f}mm" height="{vb_h:.4f}mm">
  <g id="cut" inkscape:label="Cut" stroke="{cut_color}" stroke-width="{stroke_width_mm}" fill="none">
    {"".join(cut_paths)}
  </g>
  <g id="mark" inkscape:label="Mark" stroke="{mark_color}" stroke-width="{stroke_width_mm}" fill="none">
  </g>
</svg>
"""
    else:
        res = layout_parts(
            parts,
            sheet_width_mm=sheet_width_mm,
            sheet_height_mm=sheet_height_mm,
            margin_mm=margin_mm,
            spacing_mm=spacing_mm,
            kerf_width_mm=kerf_width_mm,
            press_fit_holes=press_fit_holes,
        )

        cut_elements: list[str] = []
        mark_elements: list[str] = []

        for p in res.placed_parts:
            # Exterior contour
            cut_elements.append(
                f'<path d="{coords_to_svg_path(p.poly.exterior.coords)}" id="{p.name}_{p.part_index}_ext" />'
            )
            # Interior holes
            for j, ring in enumerate(p.poly.interiors):
                cut_elements.append(
                    f'<path d="{coords_to_svg_path(ring.coords)}" id="{p.name}_{p.part_index}_hole_{j}" />'
                )
            # Optional engraving label
            if include_labels and p.label:
                c = p.poly.centroid
                mark_elements.append(
                    f'<text x="{c.x:.3f}" y="{c.y:.3f}" font-family="sans-serif" font-size="2.5" '
                    f'fill="{mark_color}" stroke="none" text-anchor="middle" dominant-baseline="central">{p.label}</text>'
                )

        cut_content = "\n    ".join(cut_elements)
        mark_content = "\n    ".join(mark_elements)

        svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     viewBox="0 0 {res.width_mm:.4f} {res.height_mm:.4f}"
     width="{res.width_mm:.4f}mm" height="{res.height_mm:.4f}mm">
  <g id="cut" inkscape:label="Cut" stroke="{cut_color}" stroke-width="{stroke_width_mm}" fill="none">
    {cut_content}
  </g>
  <g id="mark" inkscape:label="Mark" stroke="{mark_color}" stroke-width="{stroke_width_mm}" fill="none">
    {mark_content}
  </g>
</svg>
"""

    if out_path is not None:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(svg, encoding="utf-8")

    return svg


def export_laser_dxf(
    parts: Any,
    kerf_width_mm: float = 0.2,
    press_fit_holes: Mapping[str, float] | None = None,
    sheet_width_mm: float | None = None,
    sheet_height_mm: float | None = None,
    margin_mm: float = 5.0,
    spacing_mm: float = 3.0,
    out_path: str | Path | None = None,
) -> str:
    """Generate AutoCAD R12 DXF ASCII string with CUT (color 1 red) and MARK (color 5 blue) layers."""
    res = layout_parts(
        parts,
        sheet_width_mm=sheet_width_mm,
        sheet_height_mm=sheet_height_mm,
        margin_mm=margin_mm,
        spacing_mm=spacing_mm,
        kerf_width_mm=kerf_width_mm,
        press_fit_holes=press_fit_holes,
    )

    lines = [
        "0",
        "SECTION",
        "2",
        "ENTITIES",
    ]

    def add_polyline(coords: Sequence[tuple[float, float]], layer: str, color: int):
        if len(coords) < 2:
            return
        lines.extend(["0", "POLYLINE", "8", layer, "62", str(color), "66", "1", "70", "1"])
        for x, y in coords:
            lines.extend(["0", "VERTEX", "8", layer, "10", f"{x:.4f}", "20", f"{y:.4f}"])
        lines.extend(["0", "SEQEND"])

    for p in res.placed_parts:
        add_polyline(p.poly.exterior.coords, layer="CUT", color=1)
        for ring in p.poly.interiors:
            add_polyline(ring.coords, layer="CUT", color=1)

    lines.extend(["0", "ENDSEC", "0", "EOF", ""])
    dxf_text = "\n".join(lines)

    if out_path is not None:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(dxf_text, encoding="utf-8")

    return dxf_text


def export_cut_plan(
    parts: Any,
    kerf_width_mm: float = 0.2,
    press_fit_holes: Mapping[str, float] | None = None,
    sheet_width_mm: float | None = 300.0,
    sheet_height_mm: float | None = 200.0,
    margin_mm: float = 5.0,
    spacing_mm: float = 3.0,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Export a comprehensive cut plan with SVG and manifest."""
    res = layout_parts(
        parts,
        sheet_width_mm=sheet_width_mm,
        sheet_height_mm=sheet_height_mm,
        margin_mm=margin_mm,
        spacing_mm=spacing_mm,
        kerf_width_mm=kerf_width_mm,
        press_fit_holes=press_fit_holes,
    )

    svg_content = export_laser_svg(
        parts,
        kerf_width_mm=kerf_width_mm,
        press_fit_holes=press_fit_holes,
        sheet_width_mm=sheet_width_mm,
        sheet_height_mm=sheet_height_mm,
        margin_mm=margin_mm,
        spacing_mm=spacing_mm,
    )

    plan_info = {
        "kerf_width_mm": kerf_width_mm,
        "press_fit_holes": dict(press_fit_holes) if press_fit_holes else {},
        "sheet_width_mm": res.width_mm,
        "sheet_height_mm": res.height_mm,
        "parts_count": len(res.placed_parts),
        "parts": [
            {
                "name": p.name,
                "x_mm": round(p.x, 3),
                "y_mm": round(p.y, 3),
                "label": p.label,
                "kind": p.kind,
            }
            for p in res.placed_parts
        ],
    }

    if out_dir is not None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "cut_plan.svg").write_text(svg_content, encoding="utf-8")
        (out / "cut_plan.json").write_text(json.dumps(plan_info, indent=2), encoding="utf-8")

    return plan_info
