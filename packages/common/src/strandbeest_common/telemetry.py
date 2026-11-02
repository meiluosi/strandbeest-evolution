"""Telemetry storage and layered columnar retrieval using Apache Arrow and Parquet (ADR-0006, E6-01).

Provides high-throughput, structured storage for simulation time-series and replay frames:
- Columnar layout enables lazy column-level reads (e.g. foot trajectory without loading full body meshes/poses)
- Schema metadata preserves multidimensional array shapes (e.g. (F, B, 3) body coordinates)
- Bidirectional converter with legacy NumPy NPZ archives
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

_SHAPES_META_KEY = b"_strandbeest_shapes"
_DTYPES_META_KEY = b"_strandbeest_dtypes"


def _array_to_arrow(arr: np.ndarray) -> tuple[pa.Array, list[int], str]:
    """Convert a numpy array (1D or multi-D) into a pyarrow array, capturing its shape and dtype."""
    shape = list(arr.shape)
    dtype_str = str(arr.dtype)

    if arr.ndim == 1:
        arrow_arr = pa.array(arr)
    else:
        # Flatten all dimensions beyond the first (batch/time dimension)
        sub_len = int(np.prod(shape[1:])) if len(shape) > 1 else 1
        flat = arr.reshape(shape[0], sub_len)
        arrow_sub = pa.array(flat.ravel())
        arrow_arr = pa.FixedSizeListArray.from_arrays(arrow_sub, sub_len)

    return arrow_arr, shape, dtype_str


def _arrow_to_array(field_name: str, chunked_arr: pa.ChunkedArray, shapes: dict[str, list[int]], dtypes: dict[str, str]) -> np.ndarray:
    """Reconstruct a numpy ndarray from a PyArrow ChunkedArray, restoring multi-D shapes if known."""
    orig_shape = shapes.get(field_name)
    orig_dtype = dtypes.get(field_name)

    combined = chunked_arr.combine_chunks()
    curr: pa.Array = combined
    # Unpack nested list / fixed-size list arrays down to the flat leaf array directly
    while isinstance(curr, (pa.FixedSizeListArray, pa.ListArray, pa.LargeListArray)):
        curr = curr.values

    arr = curr.to_numpy(zero_copy_only=False)
    # Fallback only if still an object array (e.g. non-standard types)
    if arr.dtype == object and len(arr) > 0 and isinstance(arr[0], (list, np.ndarray)):
        arr = np.array(arr.tolist())

    if orig_shape is not None:
        arr = arr.reshape(orig_shape)
    if orig_dtype is not None:
        arr = arr.astype(orig_dtype, copy=False)

    return arr


def save_parquet(path: str | Path, arrays: Mapping[str, np.ndarray], compression: str = "snappy") -> None:
    """Save a dictionary of numpy arrays to a Parquet file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    arrow_arrays = []
    names = []
    shapes = {}
    dtypes = {}

    for name, arr in arrays.items():
        arr_np = np.asarray(arr)
        pa_arr, shp, dt = _array_to_arrow(arr_np)
        arrow_arrays.append(pa_arr)
        names.append(name)
        shapes[name] = shp
        dtypes[name] = dt

    metadata = {
        _SHAPES_META_KEY: json.dumps(shapes).encode("utf-8"),
        _DTYPES_META_KEY: json.dumps(dtypes).encode("utf-8"),
    }

    table = pa.Table.from_arrays(arrow_arrays, names=names)
    existing_meta = table.schema.metadata or {}
    table = table.replace_schema_metadata({**existing_meta, **metadata})

    pq.write_table(table, path, compression=compression)


def load_parquet(path: str | Path, columns: Sequence[str] | None = None) -> dict[str, np.ndarray]:
    """Load numpy arrays from a Parquet file, optionally projecting specific columns."""
    path = Path(path)
    col_filter = list(columns) if columns is not None else None
    table = pq.read_table(path, columns=col_filter)

    meta = table.schema.metadata or {}
    shapes: dict[str, list[int]] = {}
    dtypes: dict[str, str] = {}
    if _SHAPES_META_KEY in meta:
        shapes = json.loads(meta[_SHAPES_META_KEY].decode("utf-8"))
    if _DTYPES_META_KEY in meta:
        dtypes = json.loads(meta[_DTYPES_META_KEY].decode("utf-8"))

    result = {}
    for name in table.column_names:
        result[name] = _arrow_to_array(name, table[name], shapes, dtypes)
    return result


def read_parquet_columns(path: str | Path, columns: Sequence[str]) -> dict[str, np.ndarray]:
    """Selective columnar read: loads only the specified columns without scanning the rest."""
    return load_parquet(path, columns=columns)


def npz_to_parquet(npz_path: str | Path, parquet_path: str | Path, compression: str = "snappy") -> None:
    """Convert an existing NumPy NPZ archive to Parquet."""
    with np.load(npz_path) as npz:
        data = {k: npz[k] for k in npz.files}
    save_parquet(parquet_path, data, compression=compression)


def parquet_to_npz(parquet_path: str | Path, npz_path: str | Path, compressed: bool = True) -> None:
    """Export a Parquet file back to a NumPy NPZ archive."""
    data = load_parquet(parquet_path)
    saver = np.savez_compressed if compressed else np.savez
    saver(npz_path, **data)


def build_telemetry_table(
    folder: str | Path,
    max_frames: int = 240,
    layers: Sequence[str] | set[str] | None = None,
) -> pa.Table:
    """Build a PyArrow Table for streaming IPC telemetry (ADR-0006, M6-01).

    Reads frame columns and time-series arrays directly from Parquet (with NPZ fallback)
    and serializes run metadata into the Table schema metadata.
    """
    folder = Path(folder)
    has_frames_parquet = (folder / "frames.parquet").exists()
    has_frames_npz = (folder / "frames.npz").exists()
    if not (has_frames_parquet or has_frames_npz):
        raise FileNotFoundError(f"Run folder {folder} has no recorded frames")

    active_layers = set(layers) if layers is not None else {"poses", "feet", "series", "energy", "events", "scene"}

    # Determine needed frame columns based on layers
    needed_fr: set[str] = {"t"}
    if "poses" in active_layers:
        needed_fr.update({"pos", "quat", "contact"})
    if "feet" in active_layers:
        needed_fr.update({"foot_pos", "foot_force", "foot_slip", "com"})

    # Read frames
    if has_frames_parquet:
        schema = pq.read_schema(folder / "frames.parquet")
        available = set(schema.names)
        actual_cols = [c for c in needed_fr if c in available]
        fr = read_parquet_columns(folder / "frames.parquet", actual_cols)
    else:
        with np.load(folder / "frames.npz") as npz:
            actual_cols = [c for c in needed_fr if c in npz.files]
            fr = {c: npz[c] for c in actual_cols}

    t_all = fr["t"]
    step = max(1, len(t_all) // max_frames)
    sliced_fr: dict[str, np.ndarray] = {}
    for c in actual_cols:
        arr = fr[c][::step]
        if c == "contact" and arr.dtype == bool:
            arr = arr.astype(np.uint8)
        sliced_fr[c] = arr

    t_sliced = sliced_fr["t"]

    # Read series / energy from arrays if requested
    needed_ar: set[str] = set()
    if "series" in active_layers:
        needed_ar.update({"t", "psi", "x", "torque"})
    if "energy" in active_layers:
        needed_ar.update({"t", "e_in", "e_contact", "e_loops", "e_friction", "kinetic", "potential", "loop_residual", "penetration"})

    ar: dict[str, np.ndarray] = {}
    if needed_ar:
        if (folder / "arrays.parquet").exists():
            ar_schema = pq.read_schema(folder / "arrays.parquet")
            ar_available = set(ar_schema.names)
            ar_cols = [c for c in needed_ar if c in ar_available]
            ar = read_parquet_columns(folder / "arrays.parquet", ar_cols)
        elif (folder / "arrays.npz").exists():
            with np.load(folder / "arrays.npz") as npz:
                ar_cols = [c for c in needed_ar if c in npz.files]
                ar = {c: npz[c] for c in ar_cols}

    # Interpolate/resample 1D series onto frame timestamps
    sliced_ar: dict[str, np.ndarray] = {}
    series_dict: dict[str, Any] | None = None
    energy_dict: dict[str, Any] | None = None

    if "t" in ar and len(ar["t"]) > 0 and len(t_sliced) > 0:
        ar_t = ar["t"]
        if "series" in active_layers:
            for c in ("psi", "x", "torque"):
                if c in ar and ar[c].ndim == 1:
                    sliced_ar[c] = np.interp(t_sliced, ar_t, ar[c]).astype(np.float32)
            sstep = max(1, len(ar_t) // 500)
            series_dict = {k: np.round(ar[k][::sstep], 5).tolist() for k in ("t", "psi", "x", "torque") if k in ar}

        if "energy" in active_layers:
            for c in ("e_in", "e_contact", "e_loops", "e_friction", "kinetic", "potential", "loop_residual", "penetration"):
                if c in ar and ar[c].ndim == 1:
                    sliced_ar[c] = np.interp(t_sliced, ar_t, ar[c]).astype(np.float32)
            sstep = max(1, len(ar_t) // 500)
            energy_dict = {k: np.round(ar[k][::sstep], 7).tolist() for k in ("t", "e_in", "e_contact", "e_loops", "e_friction", "kinetic", "potential", "loop_residual", "penetration") if k in ar}

    # Read run metadata
    run_doc: dict[str, Any] = {}
    if (folder / "run.json").exists():
        try:
            run_doc = json.loads((folder / "run.json").read_text())
        except Exception:
            run_doc = {}

    from strandbeest_common.scenario import flatten as flatten_scenario

    sc = flatten_scenario(run_doc["scenario"]) if "scenario" in run_doc else {}
    from strandbeest_common.linkage import load_spec
    from strandbeest_common.gait import gait_metrics

    spec_dict = sc.get("linkage", {}).get("spec") if isinstance(sc.get("linkage"), dict) else None
    g = gait_metrics(load_spec(spec_dict)) if isinstance(spec_dict, dict) else None
    nominal = None
    if g and g.duty > 0 and "walker" in sc and isinstance(sc["walker"], dict):
        nominal = float(g.stroke_length / g.duty * sc["walker"].get("unit", 1.0))

    revolutions = None
    if "psi" in ar and len(ar["psi"]) > 0:
        revolutions = float(ar["psi"][-1] / (2 * np.pi))

    run_meta: dict[str, Any] = {
        "t": np.round(t_sliced, 4).tolist(),
        "events": run_doc.get("events", []) if ("events" in active_layers or layers is None) else [],
        "diagnosis": run_doc.get("diagnosis", []),
        "metrics": run_doc.get("metrics", {}),
        "stalled": run_doc.get("stalled", False),
        "nominal_stride_m": nominal,
        "kinematic_duty": g.duty if g else None,
        "revolutions": revolutions,
        "info": {
            "terrain": sc.get("terrain"),
            "drive": sc.get("drive", {}).get("kind", "motor") if isinstance(sc.get("drive"), dict) else sc.get("drive"),
            "wind": sc.get("wind"),
            "environment": sc.get("environment"),
            "legs": sc.get("walker", {}).get("legs", 6) if isinstance(sc.get("walker"), dict) else 6,
            "max_torque": sc.get("drive", {}).get("max_torque") if isinstance(sc.get("drive"), dict) else None,
        },
    }

    if "scene" in active_layers and (folder / "scene.json").exists():
        try:
            run_meta["scene"] = json.loads((folder / "scene.json").read_text())
        except Exception:
            pass

    if series_dict is not None and "series" in active_layers:
        run_meta["series"] = series_dict
    if energy_dict is not None and "energy" in active_layers:
        run_meta["energy"] = energy_dict

    # Convert all sliced arrays into Arrow arrays
    arrow_arrays: list[pa.Array] = []
    names: list[str] = []
    shapes: dict[str, list[int]] = {}
    dtypes: dict[str, str] = {}

    all_arrays = {**sliced_fr, **sliced_ar}
    for name, arr in all_arrays.items():
        pa_arr, shp, dt = _array_to_arrow(arr)
        arrow_arrays.append(pa_arr)
        names.append(name)
        shapes[name] = shp
        dtypes[name] = dt

    run_meta["shapes"] = shapes
    run_meta["dtypes"] = dtypes

    table = pa.Table.from_arrays(arrow_arrays, names=names)
    metadata = {
        b"meta": json.dumps(run_meta).encode("utf-8"),
        _SHAPES_META_KEY: json.dumps(shapes).encode("utf-8"),
        _DTYPES_META_KEY: json.dumps(dtypes).encode("utf-8"),
    }
    existing_meta = table.schema.metadata or {}
    table = table.replace_schema_metadata({**existing_meta, **metadata})
    return table


def serialize_table_to_arrow_stream(table: pa.Table) -> bytes:
    """Serialize a PyArrow Table into an IPC stream byte buffer."""
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()
