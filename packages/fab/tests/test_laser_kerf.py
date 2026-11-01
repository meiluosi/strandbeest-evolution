import json
import math
from pathlib import Path

import pytest
from shapely.geometry import Point, Polygon, box

from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_fab import (
    compensate_kerf,
    export,
    export_cut_plan,
    export_laser_dxf,
    export_laser_svg,
    layout_parts,
)
from strandbeest_fab.export import bar_polygon

EX = schema_dir() / "examples" / "design-jansen-small-6leg.json"


def test_square_with_hole_kerf_compensation():
    """Test that a 10x10 square with a 4mm circular hole, when compensated for 0.2mm kerf,
    yields an exterior of 10.2x10.2 and a hole of 3.8mm diameter."""
    square = box(0.0, 0.0, 10.0, 10.0)
    # 4mm diameter hole -> radius 2.0mm
    hole = Point(5.0, 5.0).buffer(2.0, quad_segs=64)
    poly = square.difference(hole)

    # Apply 0.2mm kerf compensation
    kerf = 0.2
    comp = compensate_kerf(poly, kerf_width_mm=kerf)

    # Exterior boundary expands by +w_kerf / 2 = +0.1mm on each side -> 10.2 x 10.2
    minx, miny, maxx, maxy = comp.bounds
    width = maxx - minx
    height = maxy - miny
    assert width == pytest.approx(10.2, abs=1e-3)
    assert height == pytest.approx(10.2, abs=1e-3)

    # Hole contracts by -w_kerf / 2 = -0.1mm radius -> radius 1.9mm -> diameter 3.8mm
    assert len(comp.interiors) == 1
    hole_poly = Polygon(comp.interiors[0])
    hole_diameter = 2.0 * math.sqrt(hole_poly.area / math.pi)
    assert hole_diameter == pytest.approx(3.8, abs=0.02)


def test_press_fit_hole_compensation():
    """Test press-fit hole undersize compensation for interference fit before/after kerf."""
    square = box(0.0, 0.0, 10.0, 10.0)
    # 4.0mm diameter hole -> radius 2.0mm
    hole = Point(5.0, 5.0).buffer(2.0, quad_segs=64)
    poly = square.difference(hole)

    # 1. Press fit only (no kerf): -0.05mm diameter offset
    comp_pf_only = compensate_kerf(poly, kerf_width_mm=0.0, press_fit_offset_mm=-0.05)
    hole_poly1 = Polygon(comp_pf_only.interiors[0])
    diam1 = 2.0 * math.sqrt(hole_poly1.area / math.pi)
    assert diam1 == pytest.approx(3.95, abs=0.02)

    # 2. Combined 0.2mm kerf and -0.05mm press-fit offset:
    # Exterior: 10.0 + 0.2 = 10.2 mm
    # Hole diameter: 4.0 - 0.2 - 0.05 = 3.75 mm
    comp_both = compensate_kerf(poly, kerf_width_mm=0.2, press_fit_offset_mm=-0.05)
    w = comp_both.bounds[2] - comp_both.bounds[0]
    h = comp_both.bounds[3] - comp_both.bounds[1]
    assert w == pytest.approx(10.2, abs=1e-3)
    assert h == pytest.approx(10.2, abs=1e-3)

    hole_poly2 = Polygon(comp_both.interiors[0])
    diam2 = 2.0 * math.sqrt(hole_poly2.area / math.pi)
    assert diam2 == pytest.approx(3.75, abs=0.02)


def test_press_fit_holes_dict_compensation_on_crank_arm():
    """Test press_fit_holes dict lookup: crank shaft hole is undersized while pin hole is not."""
    # Crank arm with length=30mm, bar_width=10mm, pin_hole=3.3mm at both ends
    crank = bar_polygon(30.0, 10.0, 3.3, first_hole_mm=3.3)
    press_fit_rules = {"crank": -0.05}

    comp = compensate_kerf(
        crank,
        kerf_width_mm=0.2,
        part_name="crank_arm_30.0mm",
        press_fit_holes=press_fit_rules,
    )

    assert len(comp.interiors) == 2
    # Sort holes by x coordinate: hole 0 at x=0 (shaft end), hole 1 at x=30 (pin end)
    holes_by_x = sorted(comp.interiors, key=lambda r: Polygon(r).centroid.x)
    diam_shaft = 2.0 * math.sqrt(Polygon(holes_by_x[0]).area / math.pi)
    diam_pin = 2.0 * math.sqrt(Polygon(holes_by_x[1]).area / math.pi)

    # Shaft bore has kerf (0.2) + press-fit offset (-0.05) -> 3.3 - 0.2 - 0.05 = 3.05 mm
    assert diam_shaft == pytest.approx(3.05, abs=0.03)

    # Pin hole only has kerf (0.2) -> 3.3 - 0.2 = 3.10 mm
    assert diam_pin == pytest.approx(3.10, abs=0.03)


def test_export_laser_svg_layer_and_color_conventions(tmp_path):
    """Test SVG export contains red cut paths and blue marking paths."""
    square = box(0.0, 0.0, 10.0, 10.0)
    hole = Point(5.0, 5.0).buffer(2.0, quad_segs=32)
    poly = square.difference(hole)

    out_file = tmp_path / "test_part.svg"
    svg_str = export_laser_svg(
        poly,
        kerf_width_mm=0.2,
        layout=False,
        out_path=out_file,
    )

    assert out_file.exists()
    assert "<svg" in svg_str
    assert 'id="cut"' in svg_str
    assert 'stroke="#ff0000"' in svg_str  # Red for through-cut
    assert 'id="mark"' in svg_str
    assert 'stroke="#0000ff"' in svg_str  # Blue for engrave/mark


def test_layout_nesting_and_cut_plan(tmp_path):
    """Test sheet nesting and cut plan generation."""
    bars = [bar_polygon(50.0, 10.0, 3.3) for _ in range(6)]
    plan = export_cut_plan(
        bars,
        kerf_width_mm=0.2,
        sheet_width_mm=200.0,
        out_dir=tmp_path,
    )

    assert plan["parts_count"] == 6
    assert plan["kerf_width_mm"] == 0.2
    assert (tmp_path / "cut_plan.svg").exists()
    assert (tmp_path / "cut_plan.json").exists()


def test_export_laser_dxf_generation(tmp_path):
    """Test DXF ASCII export contains CUT polylines."""
    b = bar_polygon(40.0, 10.0, 3.3)
    dxf_file = tmp_path / "bars.dxf"
    dxf_str = export_laser_dxf([b], kerf_width_mm=0.2, out_path=dxf_file)

    assert dxf_file.exists()
    assert "SECTION" in dxf_str
    assert "POLYLINE" in dxf_str
    assert "CUT" in dxf_str
    assert "EOF" in dxf_str


def test_export_design_generates_laser_svg(tmp_path):
    """Test that end-to-end export(design) produces laser_cut.svg."""
    d = Design(json.loads(EX.read_text()))
    mf = export(d, tmp_path)

    assert "laser_cut" in mf
    laser_svg = tmp_path / mf["laser_cut"]
    assert laser_svg.exists()
    content = laser_svg.read_text(encoding="utf-8")
    assert "<svg" in content
    assert 'id="cut"' in content
