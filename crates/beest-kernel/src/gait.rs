//! Exact kinematic gait metrics of foot path and ground plane contact.

use crate::kinematics::{solve_pose, trace, LinkageSpec};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use serde::{Deserialize, Serialize};

/// Exact kinematic gait metrics of a linkage's foot trajectory.
#[pyclass]
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GaitMetrics {
    /// Horizontal extent of the entire foot trajectory
    #[pyo3(get)]
    pub width: f64,
    /// Vertical extent of the foot trajectory (step height / vertical lift)
    #[pyo3(get)]
    pub lift: f64,
    /// Horizontal span covered during flat ground contact stroke
    #[pyo3(get)]
    pub stroke_length: f64,
    /// Fraction of cycle spent on ground stroke (duty factor)
    #[pyo3(get)]
    pub duty: f64,
    /// Alias for duty factor
    #[pyo3(get)]
    pub duty_factor: f64,
    /// Alias for vertical lift
    #[pyo3(get)]
    pub step_height: f64,
    /// Maximum foot clearance above ground plane
    #[pyo3(get)]
    pub clearance: f64,
    /// Whether linkage assembled across all sampled crank angles
    #[pyo3(get)]
    pub assembled: bool,
}

#[pymethods]
impl GaitMetrics {
    pub fn asdict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new(py);
        dict.set_item("width", self.width)?;
        dict.set_item("lift", self.lift)?;
        dict.set_item("stroke_length", self.stroke_length)?;
        dict.set_item("duty", self.duty)?;
        dict.set_item("duty_factor", self.duty_factor)?;
        dict.set_item("step_height", self.step_height)?;
        dict.set_item("clearance", self.clearance)?;
        dict.set_item("assembled", self.assembled)?;
        Ok(dict)
    }

    fn __repr__(&self) -> String {
        format!(
            "GaitMetrics(width={:.4}, lift={:.4}, stroke_length={:.4}, duty={:.4}, assembled={})",
            self.width, self.lift, self.stroke_length, self.duty, self.assembled
        )
    }
}

/// Computes gait metrics for `spec` evaluated at `samples` crank angles with contact threshold `tol`.
pub fn compute_gait(spec: &LinkageSpec, samples: usize, tol: f64) -> GaitMetrics {
    let traj = trace(spec, samples);
    if !traj.assembled {
        return GaitMetrics {
            width: 0.0,
            lift: 0.0,
            stroke_length: 0.0,
            duty: 0.0,
            duty_factor: 0.0,
            step_height: 0.0,
            clearance: 0.0,
            assembled: false,
        };
    }
    compute_gait_from_foot_path(&traj.points, tol)
}

/// Evaluates gait metrics from an array of (x, y) foot path coordinates.
pub fn compute_gait_from_foot_path(path: &[(f64, f64)], tol: f64) -> GaitMetrics {
    let n = path.len();
    if n == 0 {
        return GaitMetrics {
            width: 0.0,
            lift: 0.0,
            stroke_length: 0.0,
            duty: 0.0,
            duty_factor: 0.0,
            step_height: 0.0,
            clearance: 0.0,
            assembled: false,
        };
    }

    let mut min_x = f64::INFINITY;
    let mut max_x = f64::NEG_INFINITY;
    let mut min_y = f64::INFINITY;
    let mut max_y = f64::NEG_INFINITY;

    for &(x, y) in path {
        if x < min_x {
            min_x = x;
        }
        if x > max_x {
            max_x = x;
        }
        if y < min_y {
            min_y = y;
        }
        if y > max_y {
            max_y = y;
        }
    }

    let width = max_x - min_x;
    let lift = max_y - min_y;
    let limit = min_y + tol * width;

    let on: Vec<bool> = path.iter().map(|&(_, y)| y <= limit).collect();
    if on.iter().all(|&b| b) {
        return GaitMetrics {
            width,
            lift,
            stroke_length: width,
            duty: 1.0,
            duty_factor: 1.0,
            step_height: lift,
            clearance: lift,
            assembled: true,
        };
    }

    let mut best = 0;
    let mut best_start = 0;
    let mut run = 0;
    let mut run_start = 0;

    // Walk loop twice so a run crossing index 0 is counted whole
    for i in 0..(2 * n) {
        if on[i % n] {
            if run == 0 {
                run_start = i;
            }
            run += 1;
            if run > best && run <= n {
                best = run;
                best_start = run_start;
            }
        } else {
            run = 0;
        }
    }

    if best == 0 {
        return GaitMetrics {
            width,
            lift,
            stroke_length: 0.0,
            duty: 0.0,
            duty_factor: 0.0,
            step_height: lift,
            clearance: lift,
            assembled: true,
        };
    }

    let mut seg_min_x = f64::INFINITY;
    let mut seg_max_x = f64::NEG_INFINITY;
    for i in 0..best {
        let x = path[(best_start + i) % n].0;
        if x < seg_min_x {
            seg_min_x = x;
        }
        if x > seg_max_x {
            seg_max_x = x;
        }
    }

    let stroke = seg_max_x - seg_min_x;
    let duty = (best as f64) / (n as f64);

    GaitMetrics {
        width,
        lift,
        stroke_length: stroke,
        duty,
        duty_factor: duty,
        step_height: lift,
        clearance: lift,
        assembled: true,
    }
}

/// Instantaneous kinematic mechanical advantage: ratio of crank tangential velocity to foot velocity.
/// MA = v_crank / v_foot = r_crank / ||dp_foot / d_theta||
pub fn instantaneous_mechanical_advantage(spec: &LinkageSpec, theta: f64) -> Option<f64> {
    let r_crank = spec.crank()?;
    let delta = 1e-6;
    let p_plus = solve_pose(spec, theta + delta)?.get(&spec.foot).copied()?;
    let p_minus = solve_pose(spec, theta - delta)?.get(&spec.foot).copied()?;
    let dx_dtheta = (p_plus.0 - p_minus.0) / (2.0 * delta);
    let dy_dtheta = (p_plus.1 - p_minus.1) / (2.0 * delta);
    let foot_vel = dx_dtheta.hypot(dy_dtheta);
    if foot_vel < 1e-9 {
        None
    } else {
        Some(r_crank / foot_vel)
    }
}

/// Mean mechanical advantage during ground contact stroke.
pub fn ground_stroke_mechanical_advantage(
    spec: &LinkageSpec,
    samples: usize,
    tol: f64,
) -> Option<f64> {
    let traj = trace(spec, samples);
    if !traj.assembled || traj.points.is_empty() {
        return None;
    }
    let gait = compute_gait_from_foot_path(&traj.points, tol);
    if gait.duty == 0.0 {
        return None;
    }

    let mut min_y = f64::INFINITY;
    for &(_, y) in &traj.points {
        if y < min_y {
            min_y = y;
        }
    }
    let limit = min_y + tol * gait.width;

    let mut ma_sum = 0.0;
    let mut count = 0;
    for (i, &theta) in traj.angles.iter().enumerate() {
        if traj.points[i].1 <= limit {
            if let Some(ma) = instantaneous_mechanical_advantage(spec, theta) {
                ma_sum += ma;
                count += 1;
            }
        }
    }

    if count == 0 {
        None
    } else {
        Some(ma_sum / (count as f64))
    }
}
