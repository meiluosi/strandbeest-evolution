"""Validate staged API gallery output against raw runs and preserve old/new evidence.

Usage: .venv/bin/python scripts/check-gallery-bake.py BAKE_ROOT REPORT.json
BAKE_ROOT contains old-gallery/, new-gallery/, and api-data/. Never installs
files or changes scenarios. Requires the single-worker local bake to finish.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from jsonschema import Draft202012Validator

from strandbeest_sim import load_scenario


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def summary(replay):
    energy = replay.get("energy", {})
    return {
        "first_frame_t": replay["t"][0], "last_frame_t": replay["t"][-1],
        "frame_count": len(replay["t"]),
        "first_series_t": replay["series"]["t"][0], "last_series_t": replay["series"]["t"][-1],
        "first_psi": replay["series"]["psi"][0],
        "energy_keys": sorted(energy),
        "initial_energy": {k: v[0] for k, v in energy.items()},
        "final_energy": {k: v[-1] for k, v in energy.items()},
        "metrics": replay["metrics"], "stalled": replay["stalled"],
        "geometry": {"bodies": len(replay["scene"]["bodies"]), "geoms": len(replay["scene"]["geoms"]),
                     "torso_name": next(g["name"] for g in replay["scene"]["geoms"] if g["body"] == 0),
                     "foot_count": sum(g.get("foot", False) for g in replay["scene"]["geoms"])},
    }


def main():
    root, output = Path(sys.argv[1]), Path(sys.argv[2])
    if output.exists():
        raise FileExistsError(output)
    manifest = read(root / "new-gallery/provenance.json")
    old_manifest_path = root / "old-gallery/provenance.json"
    old_manifest = read(old_manifest_path) if old_manifest_path.exists() else None
    assert manifest["complete"] and not manifest["sources_changed_during_bake"]
    assert manifest["api_workers"] == 1
    index = read(root / "new-gallery/index.json")
    scenario_validator = Draft202012Validator(read(Path("schemas/scenario.schema.json")))
    expected = list(read(Path("contracts/scenes.json"))["scenes"])
    assert index["scenes"] == expected and set(manifest["scenes"]) == set(expected)
    rows = []
    for scene in expected:
        old_path, new_path = root / f"old-gallery/{scene}.json", root / f"new-gallery/{scene}.json"
        old, new = read(old_path), read(new_path)
        entry = manifest["scenes"][scene]
        old_entry = old_manifest["scenes"][scene] if old_manifest else None
        if old_entry:
            assert old_entry["replay_sha256"] == sha(old_path)
        run_dir = root / "api-data/runs" / entry["run_id"]
        doc = read(run_dir / "run.json")
        scenario_validator.validate(doc["scenario"])
        load_scenario(doc["scenario"])
        assert sha(new_path) == entry["replay_sha256"]
        assert new["metrics"] == doc["metrics"] and new["stalled"] == doc["stalled"]
        assert new["scene"] == read(run_dir / "scene.json")
        old_info, new_info = old["info"], json.loads(json.dumps(new["info"]))
        added_info = {}
        # Current schemas expose the inactive water-level default explicitly.
        # Verify and report it; all previously stored physical values must match.
        if "water_level_m" not in old_info["terrain"] and "water_level_m" in new_info["terrain"]:
            added_info["terrain.water_level_m"] = new_info["terrain"].pop("water_level_m")
            assert added_info["terrain.water_level_m"] is None
        assert old_info == new_info, f"{scene}: physical scene settings changed"
        with np.load(run_dir / "arrays.npz") as raw:
            step = max(1, len(raw["t"]) // 500)
            for k, arr in new["series"].items():
                np.testing.assert_array_equal(arr, np.round(raw[k][::step], 5), err_msg=f"{scene}.series.{k}")
            for k, arr in new["energy"].items():
                np.testing.assert_array_equal(arr, np.round(raw[k][::step], 7), err_msg=f"{scene}.energy.{k}")
        with np.load(run_dir / "frames.npz") as raw:
            step = max(1, len(raw["t"]) // 240)
            for k in ("t", "pos", "quat", "contact", "foot_pos", "foot_force", "foot_slip", "com"):
                value = raw[k][::step].astype(int) if k == "contact" else np.round(raw[k][::step], 3 if k == "foot_force" else 4)
                # Frame sources can be float32; the API rounds after Parquet
                # reads promote them to float64, so compare published precision.
                np.testing.assert_allclose(new[k], value, rtol=0, atol=5e-7, err_msg=f"{scene}.frames.{k}")
        assert new["t"][0] == new["series"]["t"][0] == new["energy"]["t"][0] == 0
        assert all(new["energy"][k][0] == 0 for k in ("e_in", "e_contact", "e_loops", "e_friction"))
        assert any(g["name"] == "torso_geom" for g in new["scene"]["geoms"])
        rows.append({"scene": scene, "run_id": entry["run_id"], "wall_s": entry["wall_s"],
                     "old_sha256": sha(old_path), "new_sha256": sha(new_path),
                     "old_run_provenance": old_entry["run_provenance"] if old_entry else None,
                     "old_version_status": "recorded in old_run_provenance" if old_entry else "not recorded in legacy artifact",
                     "new_run_provenance": doc["provenance"],
                     "old": summary(old), "new": summary(new), "added_inactive_info_fields": added_info, "validation": "passed",
                     "checks": ["saved scenario validates and reloads", "same physical scene info", "current time and work origin", "current geometry identity",
                                "metrics equal raw run document", "series and energy equal raw arrays",
                                "frames equal raw poses/contacts/loads", "fresh replay hash matches provenance"]})
        print(scene, "PASS", entry["wall_s"], flush=True)
    report = {"study": "H2 gallery rebake", "definition": manifest["definition"], "scene_count": len(rows), "all_passed": True,
              "checker_sha256": sha(Path(__file__)),
              "single_simulation_worker": True, "wall_s": manifest["wall_s"],
              "backup_directory": str(root / "old-gallery"), "temporary_api_data": str(root / "api-data"),
              "provenance_sha256": sha(root / "new-gallery/provenance.json"),
              "old_provenance_sha256": sha(old_manifest_path) if old_manifest else None,
              "legacy_version_limit": None if old_manifest else "Original gallery files did not record actual engine/code versions; do not infer them from dependency constraints.",
              "run_source_sha256": manifest["source_sha256"], "scenes": rows,
              "published": False, "physical_defaults_changed": False}
    with output.open("x") as f:
        json.dump(report, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
