"""E2-01: ULIDs and legacy ids. The contract vectors are shared with packages/core/src/ids.test.ts."""
import json
from pathlib import Path

import pytest
from strandbeest_common.ids import (
    UlidGenerator,
    decode_ulid,
    encode_ulid,
    is_ulid,
    legacy_ulid,
    new_ulid,
    ulid_time_ms,
)

ROOT = Path(__file__).resolve().parents[3]
VECTORS = json.loads((Path(__file__).resolve().parents[3] / "contracts" / "ids" / "ulid-vectors.json").read_text())


def test_contract_vectors_encode_and_decode():
    for row in VECTORS["ulid"]:
        rand = int(row["random_hex"], 16)
        assert encode_ulid(row["time_ms"], rand) == row["ulid"]
        assert decode_ulid(row["ulid"]) == (row["time_ms"], rand)


def test_contract_vectors_legacy():
    for row in VECTORS["legacy"]:
        assert legacy_ulid(row["kind"], row["key"]) == row["ulid"]


def test_spec_reference_example():
    # published examples of the ULID reference implementation (an independent check of the encoding)
    assert ulid_time_ms("01ARZ3NDEKTSV4RRFFQ69G5FAV") == 1469922850259
    assert encode_ulid(1469918176385, 0).startswith("01ARYZ6S41")


def test_generated_ids_are_valid_unique_and_sort_by_creation():
    ids = [new_ulid() for _ in range(5000)]
    assert all(is_ulid(i) for i in ids)
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_monotonic_within_a_millisecond_and_clock_going_backwards():
    now = [1_800_000_000_000]
    g = UlidGenerator(clock=lambda: now[0], rng=lambda n: bytes(n))
    a = g.new()
    b = g.new()
    now[0] -= 5000
    c = g.new()
    assert a < b < c
    assert ulid_time_ms(a) == 1_800_000_000_000 == ulid_time_ms(c)


@pytest.mark.parametrize("bad", ["", "abc", "8ZZZZZZZZZZZZZZZZZZZZZZZZZ", "01ARZ3NDEKTSV4RRFFQ69G5FAI", "01arz3ndektsv4rrffq69g5fav", None, 5])
def test_malformed_ids_are_rejected(bad):
    assert not is_ulid(bad)
    with pytest.raises(ValueError):
        decode_ulid(bad)  # type: ignore[arg-type]


def test_legacy_ids_are_deterministic_valid_and_distinguish_kind_and_name():
    a = legacy_ulid("design", "x")
    assert a == legacy_ulid("design", "x") and is_ulid(a)
    assert a != legacy_ulid("run", "x") and a != legacy_ulid("design", "y")
    assert ulid_time_ms(a) == 0


def test_shared_schema_definitions_are_identical_everywhere():
    """Ulid (and AssetRef) are copied into each schema that uses them; the copies must never drift."""
    schemas = {n: json.loads((ROOT / "schemas" / f"{n}.schema.json").read_text()) for n in ("design", "run", "measurement", "profile")}
    for name in ("Ulid", "AssetRef"):
        copies = {n: s["$defs"][name] for n, s in schemas.items() if name in s.get("$defs", {})}
        assert len(copies) >= 1
        first = next(iter(copies.values()))
        assert all(c == first for c in copies.values()), (name, list(copies))
    # and the pattern in the schema is exactly the one the library enforces
    from strandbeest_common.ids import ULID_RE

    assert schemas["design"]["$defs"]["Ulid"]["pattern"] == ULID_RE.pattern
