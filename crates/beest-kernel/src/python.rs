//! Optional Python adapter; all numerical work lives in the pure kernel.
use crate::*;
use pyo3::prelude::*;
use std::collections::HashMap;

fn parse_spec_arg(arg: &Bound<'_, PyAny>) -> PyResult<LinkageSpec> {
    if let Ok(s) = arg.extract::<String>() {
        parse_spec(&s).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!(
                "failed to parse LinkageSpec JSON: {}",
                e
            ))
        })
    } else {
        let py = arg.py();
        let json_mod = py.import("json")?;
        let json_str: String = json_mod.getattr("dumps")?.call1((arg,))?.extract()?;
        parse_spec(&json_str).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!(
                "failed to parse LinkageSpec object: {}",
                e
            ))
        })
    }
}

/// Solves all joint positions for crank angle `theta` (radians). Returns None if assembly fails.
#[pyfunction]
#[pyo3(name = "solve_pose")]
pub fn py_solve_pose(
    spec_json: &Bound<'_, PyAny>,
    theta: f64,
) -> PyResult<Option<HashMap<String, (f64, f64)>>> {
    let spec = parse_spec_arg(spec_json)?;
    api::pose(&spec, theta).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// Traces the foot trajectory over `samples` steps across crank angle [0, 2pi).
#[pyfunction]
#[pyo3(name = "trace_trajectory")]
pub fn py_trace_trajectory(spec_json: &Bound<'_, PyAny>, samples: usize) -> PyResult<Trajectory> {
    let spec = parse_spec_arg(spec_json)?;
    trace_checked(&spec, samples)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// Verifies whether the linkage can assemble at every sampled angle across [0, 2pi).
#[pyfunction]
#[pyo3(name = "check_assemblability")]
pub fn py_check_assemblability(spec_json: &Bound<'_, PyAny>, samples: usize) -> PyResult<bool> {
    let spec = parse_spec_arg(spec_json)?;
    Ok(trace_checked(&spec, samples)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?
        .assembled)
}

/// Computes theoretical distance extrema [D_min, D_max] between two circle centers
/// with radii r0 and r1 such that the circles can intersect: |r0 - r1| <= D <= r0 + r1.
#[pyfunction]
#[pyo3(name = "compute_dyad_envelope")]
pub fn py_compute_dyad_envelope(r0: f64, r1: f64) -> PyResult<(f64, f64)> {
    Ok(dyad_radii_envelope(r0, r1))
}

/// Computes exact gait metrics for `spec_json` evaluated at `samples` crank angles.
#[pyfunction]
#[pyo3(name = "compute_gait", signature = (spec_json, samples, tol=0.015))]
pub fn py_compute_gait(
    spec_json: &Bound<'_, PyAny>,
    samples: usize,
    tol: f64,
) -> PyResult<GaitMetrics> {
    let spec = parse_spec_arg(spec_json)?;
    api::gait(&spec, samples, tol)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

#[pyfunction]
#[pyo3(name = "circle_intersection")]
fn py_circle_intersection(
    p0: (f64, f64),
    r0: f64,
    p1: (f64, f64),
    r1: f64,
    side: i32,
) -> Option<(f64, f64)> {
    circle_intersection(p0, r0, p1, r1, side)
}

/// PyO3 C-extension module entry point.
#[pymodule]
fn beest_kernel(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<NativeLinkage>()?;
    m.add_class::<Trajectory>()?;
    m.add_class::<TrajectoryIter>()?;
    m.add_class::<GaitMetrics>()?;

    m.add_function(wrap_pyfunction!(py_solve_pose, m)?)?;
    m.add_function(wrap_pyfunction!(py_circle_intersection, m)?)?;
    m.add_function(wrap_pyfunction!(py_trace_trajectory, m)?)?;
    m.add_function(wrap_pyfunction!(py_check_assemblability, m)?)?;
    m.add_function(wrap_pyfunction!(py_compute_dyad_envelope, m)?)?;
    m.add_function(wrap_pyfunction!(py_compute_gait, m)?)?;

    Ok(())
}

/// Owns a validated parsed spec; Python adapters replace this when the input fingerprint changes.
#[pyclass(name = "Linkage")]
struct NativeLinkage {
    spec: LinkageSpec,
}

#[pymethods]
impl NativeLinkage {
    #[new]
    fn new(spec_json: &Bound<'_, PyAny>) -> PyResult<Self> {
        let spec = parse_spec_arg(spec_json)?;
        api::validate_spec(&spec)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        Ok(Self { spec })
    }

    fn solve_pose(&self, theta: f64) -> PyResult<Option<Pose>> {
        api::pose(&self.spec, theta)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
    }

    fn trace_trajectory(&self, samples: usize) -> PyResult<Trajectory> {
        trace_checked(&self.spec, samples)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
    }

    #[pyo3(signature = (samples, tol=0.015))]
    fn compute_gait(&self, samples: usize, tol: f64) -> PyResult<GaitMetrics> {
        api::gait(&self.spec, samples, tol)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
    }

    /// Geometry-only diagnostic; explicit owner and physical inputs, no fallback.
    fn stride_reference_json(&self, options_json: &str) -> PyResult<String> {
        let options = serde_json::from_str(options_json)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        let result = stride::stride_reference(&self.spec, &options)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        serde_json::to_string(&result)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
    }
}
