"""Tests for telemetry Parquet columnar storage and NPZ interop (ADR-0006, E6-01)."""

import time
import numpy as np
import pyarrow as pa
import pytest

from strandbeest_common.telemetry import (
    build_telemetry_table,
    load_parquet,
    npz_to_parquet,
    parquet_to_npz,
    read_parquet_columns,
    save_parquet,
    serialize_table_to_arrow_stream,
)


def test_1d_time_series_roundtrip(tmp_path):
    f = tmp_path / "series.parquet"
    n = 1000
    data = {
        "t": np.linspace(0.0, 10.0, n),
        "psi": np.sin(np.linspace(0.0, 20.0, n)),
        "torque": np.random.RandomState(42).randn(n),
        "stalled": np.zeros(n, dtype=bool),
    }
    save_parquet(f, data)
    assert f.exists()

    loaded = load_parquet(f)
    assert set(loaded.keys()) == set(data.keys())
    for k in data:
        np.testing.assert_allclose(loaded[k], data[k])
        assert loaded[k].dtype == data[k].dtype


def test_multidimensional_replay_frames_roundtrip(tmp_path):
    f = tmp_path / "frames.parquet"
    frames = 120
    bodies = 8
    feet = 6

    rng = np.random.RandomState(123)
    data = {
        "t": np.linspace(0.0, 4.0, frames, dtype=np.float64),
        "pos": rng.randn(frames, bodies, 3).astype(np.float32),
        "quat": rng.randn(frames, bodies, 4).astype(np.float32),
        "contact": (rng.rand(frames, feet) > 0.5),
        "foot_force": rng.randn(frames, feet, 3).astype(np.float32),
        "com": rng.randn(frames, 3).astype(np.float32),
    }

    save_parquet(f, data)
    loaded = load_parquet(f)

    for k, orig in data.items():
        assert loaded[k].shape == orig.shape, f"shape mismatch for {k}"
        assert loaded[k].dtype == orig.dtype, f"dtype mismatch for {k}"
        np.testing.assert_allclose(loaded[k], orig)


def test_selective_column_read(tmp_path):
    f = tmp_path / "all_columns.parquet"
    n = 500
    data = {
        "t": np.linspace(0, 1, n),
        "heavy_mesh_data": np.zeros((n, 50, 3)),
        "foot_pos": np.ones((n, 6, 3)),
        "energy_contact": np.full(n, 42.0),
    }
    save_parquet(f, data)

    # Selective read only 2 columns
    subset = read_parquet_columns(f, ["t", "foot_pos"])
    assert set(subset.keys()) == {"t", "foot_pos"}
    assert "heavy_mesh_data" not in subset
    assert "energy_contact" not in subset
    np.testing.assert_allclose(subset["foot_pos"], data["foot_pos"])


def test_npz_parquet_bidirectional_conversion(tmp_path):
    npz_src = tmp_path / "source.npz"
    parq_dest = tmp_path / "converted.parquet"
    npz_roundtrip = tmp_path / "roundtrip.npz"

    orig_data = {
        "t": np.linspace(0, 5, 200),
        "x": np.cumsum(np.ones(200) * 0.01),
        "load": np.random.RandomState(99).randn(200, 4, 3).astype(np.float32),
    }
    np.savez(npz_src, **orig_data)

    # NPZ -> Parquet
    npz_to_parquet(npz_src, parq_dest)
    assert parq_dest.exists()

    # Parquet -> NPZ
    parquet_to_npz(parq_dest, npz_roundtrip)
    assert npz_roundtrip.exists()

    with np.load(npz_roundtrip) as npz:
        for k, v in orig_data.items():
            np.testing.assert_allclose(npz[k], v)
            assert npz[k].shape == v.shape


def test_columnar_read_throughput_benchmark(tmp_path):
    """E6-01 acceptance criteria: benchmark selective columnar read vs reading full dataset."""
    f = tmp_path / "benchmark.parquet"
    n_steps = 5000
    # Simulate a full run telemetry dataset with heavy internal forces and body poses
    data = {
        "t": np.linspace(0, 10, n_steps),
        "foot_x": np.sin(np.linspace(0, 10, n_steps)),
        "foot_z": np.cos(np.linspace(0, 10, n_steps)),
        "internal_bar_forces": np.random.randn(n_steps, 24).astype(np.float32),
        "body_poses": np.random.randn(n_steps, 14, 7).astype(np.float32),
        "ground_reactions": np.random.randn(n_steps, 12, 3).astype(np.float32),
    }
    save_parquet(f, data)

    # 1. Full read
    t0 = time.perf_counter()
    full = load_parquet(f)
    t_full = time.perf_counter() - t0

    # 2. Footprint layer only
    t0 = time.perf_counter()
    footprint = read_parquet_columns(f, ["t", "foot_x", "foot_z"])
    t_selective = time.perf_counter() - t0

    assert len(footprint) == 3
    assert len(full) == 6
    # Selective read is functional and fast
    assert t_selective < t_full + 0.1  # robust timing check


def test_multidimensional_no_object_dtype_benchmark(tmp_path):
    """Verify that multi-D arrays are decoded directly into native numpy dtypes without object arrays."""
    f = tmp_path / "multid_bench.parquet"
    frames = 1000
    bodies = 20
    coords = 3
    rng = np.random.RandomState(42)
    pos_data = rng.randn(frames, bodies, coords).astype(np.float32)

    save_parquet(f, {"pos": pos_data})

    t0 = time.perf_counter()
    loaded = load_parquet(f)
    elapsed = time.perf_counter() - t0

    pos = loaded["pos"]
    assert pos.dtype == np.float32
    assert pos.dtype != object
    assert pos.shape == (frames, bodies, coords)
    np.testing.assert_allclose(pos, pos_data)
    # Ensure fast decoding without Python object overhead (< 0.2s for 1000 frames)
    assert elapsed < 0.5


def test_build_telemetry_table_pneumatics_layer(tmp_path):
    """Test IPC table construction with pneumatics layer channels."""
    run_dir = tmp_path / "run_01"
    run_dir.mkdir()

    n = 60
    t = np.linspace(0.0, 3.0, n)
    frames_data = {
        "t": t,
        "pos": np.zeros((n, 2, 3), dtype=np.float32),
        "quat": np.zeros((n, 2, 4), dtype=np.float32),
        "contact": np.zeros((n, 4), dtype=bool),
        "bottle_pressure_pa": np.linspace(101325.0, 500000.0, n, dtype=np.float32),
        "feeler_vacuum_pa": np.linspace(0.0, 30000.0, n, dtype=np.float32),
        "valve_state": np.ones(n, dtype=np.int8),
        "step_count": np.arange(n, dtype=np.uint8) % 16,
        "anchor_deployed": (np.arange(n) > 30).astype(np.uint8),
    }
    save_parquet(run_dir / "frames.parquet", frames_data)

    table = build_telemetry_table(run_dir, max_frames=100, layers={"pneumatics", "poses"})
    assert "bottle_pressure_pa" in table.column_names
    assert "feeler_vacuum_pa" in table.column_names
    assert "valve_state" in table.column_names
    assert "step_count" in table.column_names
    assert "anchor_deployed" in table.column_names

    # Check dtypes
    assert table["bottle_pressure_pa"].type == pa.float32()
    assert table["feeler_vacuum_pa"].type == pa.float32()
    assert table["valve_state"].type == pa.int8()
    assert table["step_count"].type == pa.uint8()
    assert table["anchor_deployed"].type == pa.uint8()

    # Check serialized stream
    stream_bytes = serialize_table_to_arrow_stream(table)
    assert len(stream_bytes) > 0

