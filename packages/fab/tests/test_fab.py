import copy
import json
import math
from pathlib import Path

import pytest
import trimesh
from shapely.geometry import LineString

from strandbeest_common import Design, solve_pose
from strandbeest_common.schemas import schema_dir
from strandbeest_fab import export, plan_leg
from strandbeest_fab.checks import run_checks
from strandbeest_fab.export import bar_polygon

EX = schema_dir() / "examples" / "design-jansen-small-6leg.json"


def design(**mfg):
    d = json.loads(EX.read_text())
    d["manufacturing"].update(mfg)
    return Design(d)


def test_bar_holes_are_exactly_the_design_length_apart():
    poly = bar_polygon(98.0, 10.0, 3.3)
    centres = sorted((i.centroid.x, i.centroid.y) for i in poly.interiors)
    assert len(centres) == 2
    assert math.dist(centres[0], centres[1]) == pytest.approx(98.0, abs=1e-6)
    assert poly.bounds == pytest.approx((-5.0, -5.0, 103.0, 5.0))


def test_exported_stl_has_expected_size_and_is_watertight(tmp_path):
    d = design()
    mf = export(d, tmp_path)
    u = d.walker["unit_m"] * 1000
    longest = max(d.spec.val(r) for j in d.spec.joints for r in j.radii) * u
    name = f"bar_{longest:.1f}mm"
    mesh = trimesh.load(tmp_path / mf["parts"][name]["file"])
    ext = mesh.bounds[1] - mesh.bounds[0]
    assert mesh.is_watertight
    assert ext == pytest.approx([longest + 10, 10, 3], abs=1e-3)


def test_bom_counts_match_legs(tmp_path):
    d = design()
    mf = export(d, tmp_path)
    bars = sum(p["qty"] for p in mf["parts"].values() if p["kind"] == "bar")
    assert bars == 10 * d.walker["legs"]  # 10 bars per Jansen leg
    assert len(mf["crank_phase_deg"]) == d.walker["legs"]
    assert (tmp_path / "BOM.md").exists() and (tmp_path / "ASSEMBLY.md").exists()
    assert any(p.suffix == ".zip" for p in tmp_path.iterdir())


def test_layer_assignment_has_no_collisions_over_the_crank_cycle():
    d = design()
    plan = plan_leg(d)
    u = d.walker["unit_m"] * 1000
    width = d.mfg["bar_width_mm"]
    spec = d.spec
    by_layer = {}
    for b in plan.bars:
        by_layer.setdefault(b.layer, []).append(b)
    for th in [2 * math.pi * i / 360 for i in range(360)]:  # finer than the planner's sweep
        pose = dict(solve_pose(spec, th))
        pose["P"] = spec.pivot
        for bars in by_layer.values():
            segs = [LineString([(pose[b.a][0] * u, pose[b.a][1] * u), (pose[b.b][0] * u, pose[b.b][1] * u)]) for b in bars]
            for i in range(len(segs)):
                for j in range(i + 1, len(segs)):
                    assert segs[i].distance(segs[j]) >= width - 1e-6, (bars[i].label, bars[j].label, th)


def test_parts_sharing_a_pin_are_on_different_layers():
    plan = plan_leg(design())
    for point, layers in plan.pins.items():
        assert len(layers) == len(set(layers)), point


def test_thin_wall_fails_and_too_large_fails():
    d = design(pin_diameter_mm=8.0, clearance_mm=0.3)  # hole 8.3 in a 10 mm bar
    checks = {c.name: c for c in run_checks(d, plan_leg(d))}
    assert checks["wall around pin hole"].status == "fail"
    d = design(bed_mm=[100, 100])
    checks = {c.name: c for c in run_checks(d, plan_leg(d))}
    assert checks["longest part fits bed"].status == "fail"


def test_default_example_passes_all_checks():
    d = design()
    assert all(c.status != "fail" for c in run_checks(d, plan_leg(d)))
