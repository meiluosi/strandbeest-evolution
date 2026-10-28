import pytest

from strandbeest_common.hashing import (
    canonical_json,
    content_hash,
    run_input_key,
)


def test_key_order_and_float_format_do_not_change_hash():
    a = {"b": 1, "a": 1.0, "nested": {"z": -0.0, "y": [3, 3.0, 2.5000000000000004]}}
    b = {"nested": {"y": [3.0, 3, 2.5], "z": 0}, "a": 1, "b": 1.0}
    assert canonical_json(a) == canonical_json(b)
    assert content_hash(a) == content_hash(b)
    assert content_hash(a).startswith("sha256:") and len(content_hash(a)) == 7 + 64


def test_semantic_hash_ignores_display_metadata_but_changes_on_affecting_fields():
    d1 = {
        "id": "01K00000000000000000000001",
        "name": "walker-a",
        "notes": "first note",
        "aliases": ["old-a"],
        "parent": {"id": "01K00000000000000000000000"},
        "linkage": {"params": {"a": 38.0, "b": 41.5}},
    }
    d2 = {
        "id": "01K00000000000000000000002",
        "name": "renamed-walker",
        "notes": "different note",
        "linkage": {"params": {"b": 41.5, "a": 38}},
    }
    # Full asset hash differs because id/name differ, but semantic_only hash is identical
    assert content_hash(d1, semantic_only=False) != content_hash(d2, semantic_only=False)
    assert content_hash(d1, semantic_only=True) == content_hash(d2, semantic_only=True)

    # Changing a physical parameter changes the semantic hash
    d3 = {**d2, "linkage": {"params": {"a": 38.1, "b": 41.5}}}
    assert content_hash(d1, semantic_only=True) != content_hash(d3, semantic_only=True)


def test_run_input_key_changes_when_any_of_the_five_inputs_changes():
    design = {"name": "w1", "linkage": {"params": {"a": 38.0}}}
    world = {"world": {"gravity_m_s2": 9.81}, "entities": []}
    base = run_input_key(design, world, backend="mujoco", backend_version="3.2.0", platform_tag="darwin-arm64", seed=42)

    # Same inputs with renamed design or reordered keys -> identical key
    design_renamed = {"name": "w1-renamed", "notes": "ignore me", "linkage": {"params": {"a": 38}}}
    same = run_input_key(design_renamed, world, backend="mujoco", backend_version="3.2.0", platform_tag="darwin-arm64", seed=42)
    assert same["key"] == base["key"]

    # Mutate each of the 5 inputs and verify the key changes
    k_design = run_input_key({"linkage": {"params": {"a": 39.0}}}, world, backend="mujoco", backend_version="3.2.0", platform_tag="darwin-arm64", seed=42)
    k_world = run_input_key(design, {"world": {"gravity_m_s2": 3.71}, "entities": []}, backend="mujoco", backend_version="3.2.0", platform_tag="darwin-arm64", seed=42)
    k_backend = run_input_key(design, world, backend="k2", backend_version="0.1.0", platform_tag="darwin-arm64", seed=42)
    k_plat = run_input_key(design, world, backend="mujoco", backend_version="3.2.0", platform_tag="linux-x86_64", seed=42)
    k_seed = run_input_key(design, world, backend="mujoco", backend_version="3.2.0", platform_tag="darwin-arm64", seed=43)

    keys = {base["key"], k_design["key"], k_world["key"], k_backend["key"], k_plat["key"], k_seed["key"]}
    assert len(keys) == 6


def test_non_finite_float_raises():
    with pytest.raises(ValueError, match="non-finite"):
        canonical_json({"x": float("nan")})
