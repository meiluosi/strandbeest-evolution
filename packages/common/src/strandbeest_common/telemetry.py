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
