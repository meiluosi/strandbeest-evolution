//! Signed, geometry-only reference for a flat, rigid, nonrotating walker.
//!
//! The lowest equal-radius sphere supports the torso without slip. For its
//! owner angle beta (counterclockwise in the x/up plane), the contact constraint
//! integrates to dx_body = -(unit * dx_foot + radius * d_beta). This is an ideal
//! model, NOT a dynamical invariant: compliance, flight, and slip are absent.
//! Sampling can miss narrow support events. Compare resolutions independently;
//! convergence is evidence about this estimate, not a proof of event completeness.

use crate::{api::validate_spec, solve_pose_checked, KinematicError, LinkageSpec};
use serde::{Deserialize, Serialize};
use std::f64::consts::{PI, TAU};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StrideOptions {
    /// Actual sphere-owning bar's start, obtained from the built model. Its end
    /// is spec.foot. Choosing a convenient adjacent bar can change rolling.
    pub owner_start: String,
    pub phases_rad: Vec<f64>,
    pub direction: i32,
    pub unit_m: f64,
    pub radius_m: f64,
    /// Numerical resolution only; never a physical/contact tolerance.
    pub brackets: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum StrideStatus {
    Estimated,
    Unassembled,
    IncompatibleSupports,
    UnresolvedSampling,
}

#[derive(Debug, Clone, Serialize)]
pub struct StrideEstimate {
    pub point_stride_m_per_rev: f64,
    pub rolling_m_per_rev: f64,
    pub contact_stride_m_per_rev: f64,
    /// Sampled total variation, a lower estimate rather than an exact integral.
    pub sampled_absolute_contact_travel_m_per_rev: f64,
    /// None for exact zero stride or unrepresentable ratio; no denominator floor.
    pub cancellation_condition: Option<f64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct StrideReference {
    pub model: &'static str,
    pub status: StrideStatus,
    pub brackets: usize,
    pub support_switches: usize,
    pub max_support_displacement_conflict_m: f64,
    /// No plausible-looking displacement is returned for incompatible supports,
    /// unresolved angular winding, or sampled nonassembly.
    pub estimate: Option<StrideEstimate>,
}

#[derive(Clone, Copy)]
struct Sample {
    x: f64,
    y: f64,
    beta: f64,
}

fn invalid(message: &str) -> KinematicError {
    KinematicError::InvalidInput(message.into())
}

fn validate_options(options: &StrideOptions) -> Result<(), KinematicError> {
    if options.phases_rad.is_empty()
        || options.phases_rad.iter().any(|v| !v.is_finite())
        || !matches!(options.direction, -1 | 1)
        || !options.unit_m.is_finite()
        || options.unit_m <= 0.0
        || !options.radius_m.is_finite()
        || options.radius_m < 0.0
        || !(2..=1_000_000).contains(&options.brackets)
    {
        return Err(invalid("stride reference needs finite phases, direction +/-1, positive unit, nonnegative radius, and 2..=1000000 brackets"));
    }
    Ok(())
}

/// Validates topology and explicit derived inputs. Does not choose contact
/// parameters, infer a sphere owner, or alter the simulation/audit protocol.
pub fn stride_reference(
    spec: &LinkageSpec,
    options: &StrideOptions,
) -> Result<StrideReference, KinematicError> {
    validate_spec(spec)?;
    validate_options(options)?;
    if !spec.joints.iter().any(|j| {
        j.id == spec.foot
            && (j.centers.0 == options.owner_start || j.centers.1 == options.owner_start)
    }) {
        return Err(invalid(
            "owner_start must be an actual bar ending at the foot",
        ));
    }
    integrate(options, |theta| {
        let pose = solve_pose_checked(spec, theta)?;
        let (x, y) = pose[&spec.foot];
        let (sx, sy) = pose[&options.owner_start];
        if (x == sx && y == sy) || !x.is_finite() || !y.is_finite() {
            return Err(invalid("nonfinite geometry or zero-length sphere owner"));
        }
        Ok(Sample {
            x,
            y,
            beta: (y - sy).atan2(x - sx),
        })
    })
}

/// Neumaier summation retains tiny signed results when component travel cancels.
#[derive(Default)]
struct Sum {
    total: f64,
    correction: f64,
}
impl Sum {
    fn add(&mut self, value: f64) {
        let next = self.total + value;
        self.correction += if self.total.abs() >= value.abs() {
            (self.total - next) + value
        } else {
            (value - next) + self.total
        };
        self.total = next;
    }
    fn value(&self) -> f64 {
        self.total + self.correction
    }
}

fn angle_delta(a: f64, b: f64) -> f64 {
    (b - a).sin().atan2((b - a).cos())
}

fn lowest(samples: &[Sample]) -> usize {
    samples
        .iter()
        .enumerate()
        .min_by(|(ia, a), (ib, b)| a.y.total_cmp(&b.y).then(ia.cmp(ib)))
        .unwrap()
        .0
}

fn integrate(
    options: &StrideOptions,
    foot: impl Fn(f64) -> Result<Sample, KinematicError>,
) -> Result<StrideReference, KinematicError> {
    let mut output = StrideReference {
        model: "lowest-foot-sphere-v1",
        status: StrideStatus::Estimated,
        brackets: options.brackets,
        support_switches: 0,
        max_support_displacement_conflict_m: 0.0,
        estimate: None,
    };
    let phases: Vec<_> = options
        .phases_rad
        .iter()
        .map(|p| p.rem_euclid(TAU))
        .collect();
    let sample = |theta: f64| -> Result<Vec<Sample>, KinematicError> {
        phases
            .iter()
            .map(|p| {
                let value = foot(theta + p)?;
                if [value.x, value.y, value.beta]
                    .iter()
                    .any(|v| !v.is_finite())
                {
                    return Err(invalid("nonfinite sampled foot geometry"));
                }
                Ok(value)
            })
            .collect()
    };
    let result = (|| -> Result<(), KinematicError> {
        // Include every half-grid boundary in the integration, even without a
        // switch, to unwrap angle and test persistent support conflicts locally.
        let mut edges = vec![0.0];
        let mut previous = lowest(&sample(0.0)?);
        for i in 1..=2 * options.brackets {
            let mut a = TAU * (i - 1) as f64 / (2 * options.brackets) as f64;
            let mut b = TAU * i as f64 / (2 * options.brackets) as f64;
            let endpoint = b;
            let following = lowest(&sample(b)?);
            if previous != following {
                for _ in 0..48 {
                    let mid = 0.5 * (a + b);
                    if lowest(&sample(mid)?) == previous {
                        a = mid;
                    } else {
                        b = mid;
                    }
                }
                let switch = 0.5 * (a + b);
                if switch > *edges.last().unwrap() && switch < endpoint {
                    edges.push(switch);
                    output.support_switches += 1;
                }
            }
            edges.push(endpoint);
            previous = following;
        }
        let mut point = Sum::default();
        let mut rolling = Sum::default();
        let mut variation = Sum::default();
        for edge in edges.windows(2) {
            let a = sample(edge[0])?;
            let mid = sample(0.5 * (edge[0] + edge[1]))?;
            let b = sample(edge[1])?;
            let selected = lowest(&mid);
            let displacement = |leg: usize| {
                let first = angle_delta(a[leg].beta, mid[leg].beta);
                let second = angle_delta(mid[leg].beta, b[leg].beta);
                (
                    options.unit_m * (b[leg].x - a[leg].x),
                    options.radius_m * (first + second),
                    options.unit_m * (mid[leg].x - a[leg].x) + options.radius_m * first,
                    first.abs().max(second.abs()),
                )
            };
            let (dx, roll, first_half, angular_step) = displacement(selected);
            if options.radius_m > 0.0 && angular_step >= PI / 2.0 {
                output.status = StrideStatus::UnresolvedSampling;
            }
            // Exact or roundoff-level height ties must have compatible contact
            // displacements. This is a numerical equality test, not a slip band.
            for leg in 0..phases.len() {
                if leg == selected {
                    continue;
                }
                let tied = [&a, &mid, &b].iter().all(|samples| {
                    let scale = samples[leg].y.abs().max(samples[selected].y.abs());
                    (samples[leg].y - samples[selected].y).abs() <= 64.0 * f64::EPSILON * scale
                });
                if tied {
                    let (other_dx, other_roll, other_first, other_angle) = displacement(leg);
                    if options.radius_m > 0.0 && other_angle >= PI / 2.0 {
                        output.status = StrideStatus::UnresolvedSampling;
                    }
                    let difference = ((dx + roll) - (other_dx + other_roll))
                        .abs()
                        .max((first_half - other_first).abs());
                    output.max_support_displacement_conflict_m =
                        output.max_support_displacement_conflict_m.max(difference);
                    let scale = [&a, &mid, &b]
                        .iter()
                        .map(|samples| {
                            options.unit_m * samples[leg].x.abs().max(samples[selected].x.abs())
                        })
                        .fold(options.radius_m, f64::max);
                    if difference > 64.0 * f64::EPSILON * scale {
                        output.status = StrideStatus::IncompatibleSupports;
                    }
                }
            }
            point.add(-(options.direction as f64) * dx);
            rolling.add(-(options.direction as f64) * roll);
            variation.add(first_half.abs() + (dx + roll - first_half).abs());
        }
        let (point, rolling, variation) = (point.value(), rolling.value(), variation.value());
        let contact = point + rolling;
        if [
            point,
            rolling,
            variation,
            contact,
            output.max_support_displacement_conflict_m,
        ]
        .iter()
        .any(|v| !v.is_finite())
        {
            return Err(invalid("stride calculation exceeded finite numeric range"));
        }
        if output.status == StrideStatus::Estimated {
            let condition = variation / contact.abs();
            output.estimate = Some(StrideEstimate {
                point_stride_m_per_rev: point,
                rolling_m_per_rev: rolling,
                contact_stride_m_per_rev: contact,
                sampled_absolute_contact_travel_m_per_rev: variation,
                cancellation_condition: condition.is_finite().then_some(condition),
            });
        }
        Ok(())
    })();
    match result {
        Ok(()) => Ok(output),
        Err(KinematicError::AssemblyFailed { .. }) => {
            output.status = StrideStatus::Unassembled;
            output.estimate = None;
            Ok(output)
        }
        Err(error) => Err(error),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn options(n: usize, direction: i32, unit: f64, radius: f64) -> StrideOptions {
        StrideOptions {
            owner_start: "N".into(),
            phases_rad: (0..n).map(|i| TAU * i as f64 / n as f64).collect(),
            direction,
            unit_m: unit,
            radius_m: radius,
            brackets: 72,
        }
    }

    #[test]
    fn ellipse_closed_form_includes_signed_point_motion_and_full_sphere_rotation() {
        // Independent integral: N equal phases, x=A*cos(theta), y=sin(theta).
        // Lowest-foot arcs sum to 2*N*A*sin(pi/N); beta=theta winds once.
        for n in [1, 2, 4, 6, 12] {
            for direction in [-1, 1] {
                for amplitude in [0.0, 1e-10, 1.0] {
                    for radius in [0.0, 0.002] {
                        let opts = options(n, direction, 0.003, radius);
                        let result = integrate(&opts, |a| {
                            Ok(Sample {
                                x: amplitude * a.cos(),
                                y: a.sin(),
                                beta: a.sin().atan2(a.cos()),
                            })
                        })
                        .unwrap();
                        assert_eq!(result.status, StrideStatus::Estimated);
                        let estimate = result.estimate.unwrap();
                        let expected_point = if n == 1 {
                            0.0
                        } else {
                            -direction as f64
                                * 2.0
                                * n as f64
                                * amplitude
                                * opts.unit_m
                                * (PI / n as f64).sin()
                        };
                        let expected_rolling = -direction as f64 * TAU * radius;
                        assert!(
                            (estimate.point_stride_m_per_rev - expected_point).abs()
                                <= amplitude * 1e-15 + 1e-28
                        );
                        assert!((estimate.rolling_m_per_rev - expected_rolling).abs() < 1e-15);
                        if n > 1 && amplitude > 0.0 && radius == 0.0 {
                            assert_eq!(
                                estimate.contact_stride_m_per_rev.signum(),
                                -(direction as f64)
                            );
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn permanent_tied_opposing_supports_are_not_averaged_into_zero_stride() {
        let result = integrate(&options(2, 1, 1.0, 0.0), |a| {
            Ok(Sample {
                x: a.sin(),
                y: 0.0,
                beta: 0.0,
            })
        })
        .unwrap();
        assert_eq!(result.status, StrideStatus::IncompatibleSupports);
        assert!(result.estimate.is_none());
        assert!(result.max_support_displacement_conflict_m > 0.01);
    }

    #[test]
    fn duplicated_phases_are_compatible_and_do_not_multiply_motion() {
        let mut opts = options(2, -1, 1.0, 0.002);
        opts.phases_rad = vec![0.0, 0.0];
        let result = integrate(&opts, |a| {
            Ok(Sample {
                x: a.cos(),
                y: a.sin(),
                beta: a,
            })
        })
        .unwrap();
        assert_eq!(result.status, StrideStatus::Estimated);
        assert_eq!(result.max_support_displacement_conflict_m, 0.0);
        assert!((result.estimate.unwrap().contact_stride_m_per_rev - TAU * 0.002).abs() < 1e-14);
    }

    #[test]
    fn exact_zero_and_tiny_stride_are_not_replaced_by_a_positive_scale() {
        for amplitude in [0.0, 1e-30] {
            let result = integrate(&options(2, 1, 1.0, 0.0), |a| {
                Ok(Sample {
                    x: amplitude * a.cos(),
                    y: a.sin(),
                    beta: 0.0,
                })
            })
            .unwrap()
            .estimate
            .unwrap();
            if amplitude == 0.0 {
                assert_eq!(result.contact_stride_m_per_rev, 0.0);
                assert_eq!(result.cancellation_condition, None);
            } else {
                assert!((result.contact_stride_m_per_rev / (-4.0 * amplitude) - 1.0).abs() < 1e-12);
            }
        }
    }

    #[test]
    fn unresolved_angular_winding_and_nonassembly_have_no_estimate() {
        let mut opts = options(1, 1, 1.0, 0.002);
        opts.brackets = 2;
        let result = integrate(&opts, |a| {
            Ok(Sample {
                x: 0.0,
                y: 0.0,
                beta: 5.0 * a,
            })
        })
        .unwrap();
        assert_eq!(result.status, StrideStatus::UnresolvedSampling);
        assert!(result.estimate.is_none());
        let result = integrate(&opts, |_| {
            Err(KinematicError::AssemblyFailed { joint: "F".into() })
        })
        .unwrap();
        assert_eq!(result.status, StrideStatus::Unassembled);
        assert!(result.estimate.is_none());
    }

    #[test]
    fn rejects_invalid_requests_and_wrong_owner() {
        let spec = crate::jansen_classic_spec();
        for change in 0..8 {
            let mut opts = options(6, -1, 0.002, 0.002);
            match change {
                0 => opts.phases_rad.clear(),
                1 => opts.phases_rad[0] = f64::NAN,
                2 => opts.direction = 0,
                3 => opts.unit_m = 0.0,
                4 => opts.radius_m = -0.1,
                5 => opts.brackets = 0,
                6 => opts.brackets = 1_000_001,
                _ => opts.owner_start = "G".into(),
            }
            assert!(stride_reference(&spec, &opts).is_err());
        }
    }

    #[test]
    fn rejects_nonfinite_geometry_and_accumulation_overflow() {
        let opts = options(2, 1, 1.0, 0.0);
        assert!(integrate(&opts, |_| Ok(Sample {
            x: f64::INFINITY,
            y: 0.0,
            beta: 0.0
        }))
        .is_err());
        let mut huge = opts.clone();
        huge.unit_m = 1e308;
        assert!(integrate(&huge, |a| Ok(Sample {
            x: a.cos(),
            y: a.sin(),
            beta: 0.0
        }))
        .is_err());
        // Selected leg is stationary; overflow in a tied, incompatible leg's
        // displacement must also be an error, not a JSON null numeric field.
        assert!(integrate(&opts, |a| Ok(Sample {
            x: if a <= TAU {
                0.0
            } else {
                1e308 * (60.0 * a).sin()
            },
            y: 0.0,
            beta: 0.0,
        }))
        .is_err());
    }
}
