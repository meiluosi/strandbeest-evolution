"""Validate actual browser downloads with the existing Python mesh dependencies.

No extraction to disk and no physical printing/publication. Also exercise corrupted
archive and mesh controls, so a successful download alone cannot satisfy this check.
"""

import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import trimesh


def validate_pack(data: bytes, source: dict) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.testzip() is None, "ZIP checksum mismatch"
        manifest = json.loads(archive.read("parts.json"))
        assert manifest == source["manifest"], "downloaded manifest differs from the UI's actual API response"
        assert json.loads(archive.read("printability.json")) == source["pack"]["checks"]
        for name in ("BOM.md", "ASSEMBLY.md", "laser_cut.svg"):
            assert archive.read(name).strip(), f"empty {name}"
        stls = set(name for name in archive.namelist() if name.endswith(".stl"))
        assert stls == {part["file"] for part in manifest["parts"].values()}, "missing or extra part files"
        meshes = []
        for name, part in manifest["parts"].items():
            mesh = trimesh.load(io.BytesIO(archive.read(part["file"])), file_type="stl", force="mesh")
            assert len(mesh.faces) and np.isfinite(mesh.vertices).all(), f"invalid mesh {name}"
            assert mesh.is_watertight and mesh.volume > 0, f"open or inverted mesh {name}"
            assert np.allclose(mesh.extents, part["bounds_mm"], rtol=0, atol=0.001), f"wrong physical size {name}"
            assert isinstance(part["qty"], int) and part["qty"] > 0, f"invalid quantity {name}"
            meshes.append({"name": name, "triangles": len(mesh.faces), "bounds_mm": mesh.extents.tolist(), "qty": part["qty"]})
        design = source["design"]
        assert len(manifest["crank_phase_deg"]) == design["walker"]["legs"]
        assert sum(part["qty"] for part in manifest["parts"].values() if part["kind"] == "bar") == 10 * design["walker"]["legs"]
        return {"export_id": source["pack"]["export_id"], "parts": meshes, "physical_validation": False}


def negative_controls(data: bytes, source: dict) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as original:
        entries = {name: original.read(name) for name in original.namelist()}
    variants = {"truncated_archive": data[:100]}
    missing = dict(entries)
    del missing["BOM.md"]
    scaled = dict(entries)
    path = next(name for name in scaled if name.startswith("stl/bar_"))
    mesh = trimesh.load(io.BytesIO(scaled[path]), file_type="stl", force="mesh")
    mesh.apply_scale(2.0)
    scaled[path] = mesh.export(file_type="stl")
    for name, files in (("missing_bom", missing), ("doubled_bar_size", scaled)):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
            for member, value in files.items():
                archive.writestr(member, value)
        variants[name] = buf.getvalue()
    for name, variant in variants.items():
        try:
            validate_pack(variant, source)
        except (AssertionError, KeyError, ValueError, zipfile.BadZipFile):
            continue
        raise AssertionError(f"negative control was incorrectly accepted: {name}")
    return list(variants)


if __name__ == "__main__":
    paths = sorted(Path(sys.argv[1] if len(sys.argv) > 1 else "test-results/browser").rglob("manufacturing-pack.zip"))
    for path in paths:
        source = json.loads(path.with_name("manufacturing-input.json").read_text())
        data = path.read_bytes()
        report = validate_pack(data, source)
        report["negative_controls_rejected"] = negative_controls(data, source)
        path.with_name("manufacturing-validation.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"{path.parent.name}: {len(report['parts'])} closed meshes, sizes/quantities/docs checked; 3 negative controls rejected")
    if paths:
        print(f"{len(paths)} actual browser manufacturing downloads validated; no physical manufacturing validation")
