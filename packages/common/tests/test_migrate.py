"""E2-02: v1 -> v2 migration. contracts/migration/v1 holds the v1 documents; schemas/examples holds their migrated form."""
import copy
import json
from pathlib import Path

import pytest
from strandbeest_common import Design
from strandbeest_common.ids import is_ulid, legacy_ulid
from strandbeest_common.migrate import detect_kind, main, migrate_any, migrate_doc, plan
from strandbeest_common.schemas import validate

ROOT = Path(__file__).resolve().parents[3]
V1 = ROOT / "contracts" / "migration" / "v1"
EXAMPLES = ROOT / "schemas" / "examples"
FILES = {
    "design": "design-jansen-small-6leg.json",
    "run": "run-example.json",
    "measurement": "measurement-example.json",
    "profile": "profile-example.json",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text())


@pytest.mark.parametrize("kind", FILES)
def test_v1_fixture_migrates_to_the_checked_in_v2_example(kind):
    v1 = load(V1 / FILES[kind])
    assert v1["schema_version"] == 1
    v2 = migrate_doc(kind, v1)
    assert v2 == load(EXAMPLES / FILES[kind])
    validate(kind, v2)


def test_the_rig_example_migrates_too():
    v2 = migrate_doc("measurement", load(V1 / "measurement-rig-example.json"))
    assert v2 == load(EXAMPLES / "measurement-rig-example.json")


@pytest.mark.parametrize("kind", FILES)
def test_migration_is_idempotent_deterministic_and_does_not_mutate_its_input(kind):
    v1 = load(V1 / FILES[kind])
    before = copy.deepcopy(v1)
    once = migrate_doc(kind, v1)
    assert v1 == before
    assert migrate_doc(kind, once) == once
    assert migrate_doc(kind, load(V1 / FILES[kind])) == once


def test_references_resolve_by_id_after_migration():
    design = migrate_doc("design", load(V1 / FILES["design"]))
    run = migrate_doc("run", load(V1 / FILES["run"]))
    meas = migrate_doc("measurement", load(V1 / FILES["measurement"]))
    profile = migrate_doc("profile", load(V1 / FILES["profile"]))
    assert run["design_id"] == design["id"] == meas["design_id"]
    assert profile["provenance"]["measurement_ids"] == [meas["id"]]
    # the old labels still resolve: they are kept as aliases and as the display name
    assert run["aliases"] == ["example-run"] and meas["name"] == "example-motor-no-wind" and meas["aliases"] == ["example-motor-no-wind"]
    assert all(is_ulid(x) for x in (design["id"], run["id"], meas["id"], profile["id"]))


def test_old_design_files_stay_readable_with_a_stable_id():
    a = Design.load(V1 / FILES["design"])
    b = Design.load(V1 / FILES["design"])
    assert a.id == b.id == legacy_ulid("design", "jansen-small-6leg")
    assert Design.load(EXAMPLES / FILES["design"]).id == a.id


def test_renaming_a_design_keeps_its_identity():
    doc = load(EXAMPLES / FILES["design"])
    renamed = {**doc, "name": "something else"}
    assert Design(renamed).id == Design(doc).id


def test_unknown_versions_and_kinds_are_refused():
    with pytest.raises(ValueError, match="schema_version"):
        migrate_doc("design", {"schema_version": 7, "name": "x"})
    with pytest.raises(ValueError):
        migrate_doc("planet", {})
    with pytest.raises(ValueError):
        migrate_any({"hello": 1})


def test_kind_detection():
    for kind, f in FILES.items():
        assert detect_kind(load(EXAMPLES / f)) == kind


def make_data_folder(root: Path) -> None:
    (root / "designs").mkdir(parents=True)
    (root / "designs" / "jansen-small-6leg.json").write_text((V1 / FILES["design"]).read_text())
    run = load(V1 / FILES["run"])
    run["id"] = "25844b8f5918"
    (root / "runs" / "25844b8f5918").mkdir(parents=True)
    (root / "runs" / "25844b8f5918" / "run.json").write_text(json.dumps(run))
    (root / "runs" / "25844b8f5918" / "arrays.npz").write_bytes(b"not really an array")
    (root / "measurements").mkdir()
    (root / "measurements" / "example-motor-no-wind.json").write_text((V1 / FILES["measurement"]).read_text())
    (root / "profiles").mkdir()
    (root / "profiles" / "example-profile.json").write_text((V1 / FILES["profile"]).read_text())


def test_cli_dry_run_changes_nothing_then_write_migrates_a_data_folder_once(tmp_path, capsys):
    make_data_folder(tmp_path)
    snapshot = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert main([str(tmp_path)]) == 0
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == snapshot
    assert "4 document(s) to migrate" in capsys.readouterr().out

    assert main(["--write", str(tmp_path)]) == 0
    run_id = legacy_ulid("run", "25844b8f5918")
    meas_id = legacy_ulid("measurement", "example-motor-no-wind")
    run_json = tmp_path / "runs" / run_id / "run.json"
    assert run_json.exists() and (tmp_path / "runs" / run_id / "arrays.npz").exists()  # the folder moved with its files
    assert not (tmp_path / "runs" / "25844b8f5918").exists()
    assert (tmp_path / "measurements" / f"{meas_id}.json").exists()
    assert not (tmp_path / "measurements" / "example-motor-no-wind.json").exists()
    for kind, p in (("run", run_json), ("measurement", tmp_path / "measurements" / f"{meas_id}.json"),
                    ("design", tmp_path / "designs" / "jansen-small-6leg.json"), ("profile", tmp_path / "profiles" / "example-profile.json")):
        validate(kind, load(p))
    assert load(run_json)["aliases"] == ["25844b8f5918"]
    # originals were kept
    assert (tmp_path / "_backup_v1" / "runs" / "25844b8f5918" / "run.json").exists()
    assert (tmp_path / "_backup_v1" / "measurements" / "example-motor-no-wind.json").exists()

    # a second run finds nothing to do
    assert plan(tmp_path) == []
    capsys.readouterr()
    assert main(["--write", str(tmp_path)]) == 0
    assert "0 document(s) migrated" in capsys.readouterr().out


def test_cli_migrates_the_examples_folder_without_renaming_files(tmp_path):
    for f in list(FILES.values()) + ["measurement-rig-example.json"]:
        (tmp_path / f).write_text((V1 / f).read_text())
    assert main(["--write", "--no-backup", str(tmp_path)]) == 0
    for f in list(FILES.values()) + ["measurement-rig-example.json"]:
        assert load(tmp_path / f) == load(EXAMPLES / f)
