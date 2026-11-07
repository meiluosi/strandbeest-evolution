//! Dyad workspace envelope analysis and distance extrema calculation.
//! Verifies triangle inequalities and prevents kinematic lockups.

use crate::kinematics::{solve_pose, LinkageSpec};
use serde::{Deserialize, Serialize};

/// Distance extrema for two joint centers across crank sweep.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DyadDistanceExtrema {
    pub d_min: f64,
    pub d_max: f64,
    pub valid_angles: usize,
    pub fully_assembled: bool,
}

/// Theoretical distance extrema [D_min, D_max] between two circle centers
/// with radii r0 and r1 such that the circles can intersect (triangle inequality):
/// |r0 - r1| <= D <= r0 + r1.
#[inline]
pub fn dyad_radii_envelope(r0: f64, r1: f64) -> (f64, f64) {
    let d_min = (r0 - r1).abs();
    let d_max = r0 + r1;
    (d_min, d_max)
}

/// Analyzes distance extrema D_min and D_max between two joints c1 and c2 across crank angles.
pub fn compute_linkage_distance_extrema(
    spec: &LinkageSpec,
    c1: &str,
    c2: &str,
    samples: usize,
) -> Option<DyadDistanceExtrema> {
    let mut d_min = f64::INFINITY;
    let mut d_max = f64::NEG_INFINITY;
    let mut valid = 0;

    for i in 0..samples {
        let theta = 2.0 * std::f64::consts::PI * (i as f64) / (samples as f64);
        if let Some(pose) = solve_pose(spec, theta) {
            if let (Some(p1), Some(p2)) = (pose.get(c1), pose.get(c2)) {
                let dx = p1.0 - p2.0;
                let dy = p1.1 - p2.1;
                let d = dx.hypot(dy);
                if d < d_min {
                    d_min = d;
                }
                if d > d_max {
                    d_max = d;
                }
                valid += 1;
            }
        }
    }

    if valid == 0 || !d_min.is_finite() || !d_max.is_finite() {
        None
    } else {
        Some(DyadDistanceExtrema {
            d_min,
            d_max,
            valid_angles: valid,
            fully_assembled: valid == samples,
        })
    }
}

/// Verifies triangle inequalities for dyad radii (r0, r1) spanning workspace distance extrema [D_min, D_max]
/// with safety margin epsilon:
/// r0 + r1 >= D_max * (1 + epsilon)
/// |r0 - r1| <= D_min * (1 - epsilon)
#[inline]
pub fn verify_triangle_inequalities(
    d_min: f64,
    d_max: f64,
    r0: f64,
    r1: f64,
    epsilon: f64,
) -> bool {
    let sum = r0 + r1;
    let diff = (r0 - r1).abs();
    sum >= d_max * (1.0 + epsilon) && diff <= d_min * (1.0 - epsilon)
}

/// Checks lockup risk (transmission singularity) by verifying that the transmission angle
/// between dyad links never drops below min_angle_deg (or exceeds 180 - min_angle_deg).
pub fn check_transmission_angle_safety(
    d_min: f64,
    d_max: f64,
    r0: f64,
    r1: f64,
    min_angle_deg: f64,
) -> bool {
    if !d_min.is_finite()
        || !d_max.is_finite()
        || !r0.is_finite()
        || !r1.is_finite()
        || r0 <= 0.0
        || r1 <= 0.0
    {
        return false;
    }
    let min_rad = min_angle_deg.to_radians();
    for &d in &[d_min, d_max] {
        let cos_gamma = (r0 * r0 + r1 * r1 - d * d) / (2.0 * r0 * r1);
        if cos_gamma.abs() > 1.0 {
            return false;
        }
        let gamma = cos_gamma.acos();
        if gamma < min_rad || gamma > std::f64::consts::PI - min_rad {
            return false;
        }
    }
    true
}
