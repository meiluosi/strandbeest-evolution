//! Checked, binding-independent public operations. Geometry that cannot assemble is data;
//! malformed topology, parameters, and sampling requests are errors.
use crate::{
    compute_gait_from_foot_path, solve_pose_checked, trace_checked, GaitMetrics, KinematicError,
    LinkageSpec, Pose,
};
use std::collections::HashSet;

pub fn validate_spec(spec: &LinkageSpec) -> Result<(), KinematicError> {
    let invalid = |message: &str| KinematicError::InvalidInput(message.into());
    if spec.params.values().any(|v| !v.is_finite()) {
        return Err(invalid("parameters must be finite"));
    }
    for r in [&spec.crank_x, &spec.crank_y, &spec.crank_length] {
        if !spec
            .val(r)
            .ok_or_else(|| KinematicError::MissingParam(format!("{:?}", r)))?
            .is_finite()
        {
            return Err(invalid("crank parameters must be finite"));
        }
    }
    if spec.crank().unwrap() <= 0.0 {
        return Err(invalid("crank length must be positive"));
    }
    let mut ids: HashSet<&str> = HashSet::from(["G", "C"]);
    for joint in &spec.joints {
        if joint.id.is_empty() || joint.id == "P" || ids.contains(joint.id.as_str()) {
            return Err(invalid(
                "joint ids must be unique and cannot replace G, C, or P",
            ));
        }
        if joint.side != 1 && joint.side != -1 {
            return Err(invalid("side must be -1 or 1"));
        }
        for center in [&joint.centers.0, &joint.centers.1] {
            if !ids.contains(center.as_str()) {
                return Err(KinematicError::UnknownJointCenter {
                    joint: joint.id.clone(),
                    center: center.clone(),
                });
            }
        }
        if joint.centers.0 == joint.centers.1 {
            return Err(invalid("joint centers must be distinct"));
        }
        for r in [&joint.radii.0, &joint.radii.1] {
            let value = spec
                .val(r)
                .ok_or_else(|| KinematicError::MissingParam(format!("{:?}", r)))?;
            if !value.is_finite() || value <= 0.0 {
                return Err(invalid("joint radii must be finite and positive"));
            }
        }
        ids.insert(&joint.id);
    }
    if !ids.contains(spec.foot.as_str()) || spec.foot == "G" {
        return Err(KinematicError::MissingFoot(spec.foot.clone()));
    }
    Ok(())
}

pub fn pose(spec: &LinkageSpec, theta: f64) -> Result<Option<Pose>, KinematicError> {
    validate_spec(spec)?;
    if !theta.is_finite() {
        return Err(KinematicError::InvalidInput("theta must be finite".into()));
    }
    match solve_pose_checked(spec, theta) {
        Ok(pose) => Ok(Some(pose)),
        Err(KinematicError::AssemblyFailed { .. }) => Ok(None),
        Err(error) => Err(error),
    }
}

pub fn gait(spec: &LinkageSpec, samples: usize, tol: f64) -> Result<GaitMetrics, KinematicError> {
    let path = trace_checked(spec, samples)?;
    path_gait(&path.points, tol)
}

pub fn path_gait(points: &[(f64, f64)], tol: f64) -> Result<GaitMetrics, KinematicError> {
    if !tol.is_finite() || tol < 0.0 || points.iter().any(|p| !p.0.is_finite() || !p.1.is_finite())
    {
        return Err(KinematicError::InvalidInput(
            "points must be finite and tolerance finite and nonnegative".into(),
        ));
    }
    Ok(compute_gait_from_foot_path(points, tol))
}
