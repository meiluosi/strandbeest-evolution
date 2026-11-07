//! Planar dyad circle-circle intersection and linkage forward kinematics solver.

#[cfg(feature = "python")]
use pyo3::prelude::*;
use serde::{Deserialize, Deserializer, Serialize};
use std::collections::HashMap;

/// Assembly branch for circle-circle intersection.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Branch {
    Left = 1,
    Right = -1,
}

/// A numeric literal or named reference in `LinkageSpec.params`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum ParamRef {
    Value(f64),
    Named(String),
}

impl ParamRef {
    pub fn resolve(&self, params: &HashMap<String, f64>) -> Option<f64> {
        match self {
            ParamRef::Value(v) => Some(*v),
            ParamRef::Named(name) => params.get(name).copied(),
        }
    }
}

impl From<f64> for ParamRef {
    fn from(v: f64) -> Self {
        ParamRef::Value(v)
    }
}

impl From<i32> for ParamRef {
    fn from(v: i32) -> Self {
        ParamRef::Value(v as f64)
    }
}

impl From<&str> for ParamRef {
    fn from(s: &str) -> Self {
        ParamRef::Named(s.to_string())
    }
}

impl From<String> for ParamRef {
    fn from(s: String) -> Self {
        ParamRef::Named(s)
    }
}

/// A joint defined as the circle-circle intersection of two base points.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct JointDef {
    pub id: String,
    pub centers: (String, String),
    pub radii: (ParamRef, ParamRef),
    pub side: i32,
}

/// Complete geometric specification of a planar linkage.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct LinkageSpec {
    pub params: HashMap<String, f64>,
    pub crank_x: ParamRef,
    pub crank_y: ParamRef,
    pub crank_length: ParamRef,
    pub joints: Vec<JointDef>,
    pub foot: String,
}

#[derive(Deserialize)]
struct CrankSubObject {
    x: ParamRef,
    y: ParamRef,
    length: ParamRef,
}

#[derive(Deserialize)]
struct LinkageSpecHelper {
    params: HashMap<String, f64>,
    #[serde(default)]
    crank: Option<CrankSubObject>,
    #[serde(default)]
    crank_x: Option<ParamRef>,
    #[serde(default)]
    crank_y: Option<ParamRef>,
    #[serde(default)]
    crank_length: Option<ParamRef>,
    joints: Vec<JointDef>,
    foot: String,
}

impl<'de> Deserialize<'de> for LinkageSpec {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let helper = LinkageSpecHelper::deserialize(deserializer)?;
        let (cx, cy, cl) = if let Some(c) = helper.crank {
            (c.x, c.y, c.length)
        } else if let (Some(x), Some(y), Some(l)) =
            (helper.crank_x, helper.crank_y, helper.crank_length)
        {
            (x, y, l)
        } else {
            return Err(serde::de::Error::custom(
                "LinkageSpec requires either 'crank' {x, y, length} or 'crank_x', 'crank_y', 'crank_length'",
            ));
        };

        Ok(LinkageSpec {
            params: helper.params,
            crank_x: cx,
            crank_y: cy,
            crank_length: cl,
            joints: helper.joints,
            foot: helper.foot,
        })
    }
}

impl LinkageSpec {
    #[inline]
    pub fn val(&self, r: &ParamRef) -> Option<f64> {
        r.resolve(&self.params)
    }

    #[inline]
    pub fn pivot(&self) -> Option<(f64, f64)> {
        Some((self.val(&self.crank_x)?, self.val(&self.crank_y)?))
    }

    #[inline]
    pub fn crank(&self) -> Option<f64> {
        self.val(&self.crank_length)
    }
}

/// Kinematic error encountered when solving linkage pose.
#[derive(Debug, Clone, PartialEq)]
pub enum KinematicError {
    InvalidInput(String),
    MissingParam(String),
    UnknownJointCenter { joint: String, center: String },
    AssemblyFailed { joint: String },
    MissingFoot(String),
}

impl std::fmt::Display for KinematicError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            KinematicError::InvalidInput(message) => write!(f, "{}", message),
            KinematicError::MissingParam(p) => write!(f, "missing param: {}", p),
            KinematicError::UnknownJointCenter { joint, center } => {
                write!(
                    f,
                    "joint '{}' references unknown center '{}'",
                    joint, center
                )
            }
            KinematicError::AssemblyFailed { joint } => {
                write!(f, "kinematic assembly failed at joint '{}'", joint)
            }
            KinematicError::MissingFoot(foot) => write!(f, "foot '{}' not found in pose", foot),
        }
    }
}

impl std::error::Error for KinematicError {}

pub type Pose = HashMap<String, (f64, f64)>;

/// Planar dyad circle-circle intersection.
///
/// Given circles centered at `p0` with radius `r0`, and `p1` with radius `r1`,
/// `side` specifies the branch: +1 is to the left of the directed vector p0 -> p1, -1 to the right.
/// Returns None when circles do not intersect or are coincident.
#[inline]
pub fn circle_intersection(
    p0: (f64, f64),
    r0: f64,
    p1: (f64, f64),
    r1: f64,
    side: i32,
) -> Option<(f64, f64)> {
    let dx = p1.0 - p0.0;
    let dy = p1.1 - p0.1;
    let d = dx.hypot(dy);
    if !d.is_finite()
        || !r0.is_finite()
        || !r1.is_finite()
        || d == 0.0
        || d > r0 + r1
        || d < (r0 - r1).abs()
    {
        return None;
    }
    let a = (r0 * r0 - r1 * r1 + d * d) / (2.0 * d);
    let h = (r0 * r0 - a * a).max(0.0).sqrt();
    let mx = p0.0 + a * dx / d;
    let my = p0.1 + a * dy / d;
    let res_x = mx - (side as f64) * h * dy / d;
    let res_y = my + (side as f64) * h * dx / d;
    if !res_x.is_finite() || !res_y.is_finite() {
        return None;
    }
    Some((res_x, res_y))
}

/// Solves all joint positions for crank angle `theta` (radians). Returns None if assembly fails.
pub fn solve_pose(spec: &LinkageSpec, theta: f64) -> Option<Pose> {
    solve_pose_checked(spec, theta).ok()
}

/// Solves all joint positions returning a detailed `KinematicError` on failure.
pub fn solve_pose_checked(spec: &LinkageSpec, theta: f64) -> Result<Pose, KinematicError> {
    let px = spec
        .val(&spec.crank_x)
        .ok_or_else(|| KinematicError::MissingParam(format!("{:?}", spec.crank_x)))?;
    let py = spec
        .val(&spec.crank_y)
        .ok_or_else(|| KinematicError::MissingParam(format!("{:?}", spec.crank_y)))?;
    let crank = spec
        .val(&spec.crank_length)
        .ok_or_else(|| KinematicError::MissingParam(format!("{:?}", spec.crank_length)))?;

    let mut pose = HashMap::with_capacity(spec.joints.len() + 2);
    pose.insert("G".to_string(), (0.0, 0.0));
    pose.insert(
        "C".to_string(),
        (px + crank * theta.cos(), py + crank * theta.sin()),
    );

    for j in &spec.joints {
        let p0 = *pose
            .get(&j.centers.0)
            .ok_or_else(|| KinematicError::UnknownJointCenter {
                joint: j.id.clone(),
                center: j.centers.0.clone(),
            })?;
        let p1 = *pose
            .get(&j.centers.1)
            .ok_or_else(|| KinematicError::UnknownJointCenter {
                joint: j.id.clone(),
                center: j.centers.1.clone(),
            })?;
        let r0 = spec
            .val(&j.radii.0)
            .ok_or_else(|| KinematicError::MissingParam(format!("{:?}", j.radii.0)))?;
        let r1 = spec
            .val(&j.radii.1)
            .ok_or_else(|| KinematicError::MissingParam(format!("{:?}", j.radii.1)))?;
        let p = circle_intersection(p0, r0, p1, r1, j.side).ok_or_else(|| {
            KinematicError::AssemblyFailed {
                joint: j.id.clone(),
            }
        })?;
        pose.insert(j.id.clone(), p);
    }

    Ok(pose)
}

/// Foot trajectory over crank sweep.
#[cfg_attr(feature = "python", pyclass(get_all))]
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Trajectory {
    pub points: Vec<(f64, f64)>,
    pub angles: Vec<f64>,
    pub assembled: bool,
    pub poses: Vec<Pose>,
    pub max_step: f64,
}

#[cfg(feature = "python")]
#[pymethods]
impl Trajectory {
    fn __len__(&self) -> usize {
        self.points.len()
    }

    fn __getitem__(&self, idx: isize) -> PyResult<(f64, f64)> {
        let len = self.points.len() as isize;
        let actual = if idx < 0 { len + idx } else { idx };
        if actual < 0 || actual >= len {
            Err(pyo3::exceptions::PyIndexError::new_err(
                "index out of range",
            ))
        } else {
            Ok(self.points[actual as usize])
        }
    }

    fn __iter__(slf: PyRef<Self>) -> TrajectoryIter {
        TrajectoryIter {
            points: slf.points.clone(),
            idx: 0,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "Trajectory(samples={}, assembled={})",
            self.points.len(),
            self.assembled
        )
    }
}

#[cfg(feature = "python")]
#[pyclass]
pub struct TrajectoryIter {
    points: Vec<(f64, f64)>,
    idx: usize,
}

#[cfg(feature = "python")]
#[pymethods]
impl TrajectoryIter {
    fn __iter__(slf: PyRef<Self>) -> PyRef<Self> {
        slf
    }

    fn __next__(&mut self) -> Option<(f64, f64)> {
        if self.idx < self.points.len() {
            let pt = self.points[self.idx];
            self.idx += 1;
            Some(pt)
        } else {
            None
        }
    }
}

/// Traces the foot trajectory over `samples` steps across crank angle [0, 2pi).
pub fn trace(spec: &LinkageSpec, samples: usize) -> Trajectory {
    trace_checked(spec, samples).unwrap_or_else(|_| empty_trajectory())
}

fn empty_trajectory() -> Trajectory {
    Trajectory {
        points: vec![],
        angles: vec![],
        poses: vec![],
        assembled: false,
        max_step: 0.0,
    }
}

/// A geometric failure clears the whole path; malformed inputs are errors, never zero placeholders.
pub fn trace_checked(spec: &LinkageSpec, samples: usize) -> Result<Trajectory, KinematicError> {
    crate::api::validate_spec(spec)?;
    if samples == 0 || samples > 1_000_000 {
        return Err(KinematicError::InvalidInput(
            "samples must be in 1..=1000000".into(),
        ));
    }
    let mut points = Vec::with_capacity(samples);
    let mut angles = Vec::with_capacity(samples);
    let mut poses = Vec::with_capacity(samples);

    for i in 0..samples {
        let theta = 2.0 * std::f64::consts::PI * (i as f64) / (samples as f64);
        angles.push(theta);
        match solve_pose_checked(spec, theta) {
            Ok(pose) => {
                points.push(
                    *pose
                        .get(&spec.foot)
                        .ok_or_else(|| KinematicError::MissingFoot(spec.foot.clone()))?,
                );
                poses.push(pose);
            }
            Err(KinematicError::AssemblyFailed { .. }) => return Ok(empty_trajectory()),
            Err(error) => return Err(error),
        }
    }
    let mut max_step: f64 = 0.0;
    for i in 0..samples {
        let a = points[i];
        let b = points[(i + 1) % samples];
        max_step = max_step.max((a.0 - b.0).hypot(a.1 - b.1));
    }
    Ok(Trajectory {
        points,
        angles,
        poses,
        assembled: true,
        max_step,
    })
}

/// Assemblability result over a full crank rotation.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AssemblabilityResult {
    pub assembled: bool,
    pub valid_samples: usize,
    pub total_samples: usize,
}

/// Verifies whether the linkage can assemble at every sampled angle across [0, 2pi).
pub fn check_assemblability(spec: &LinkageSpec, num_steps: usize) -> AssemblabilityResult {
    let mut valid = 0;
    for i in 0..num_steps {
        let theta = 2.0 * std::f64::consts::PI * (i as f64) / (num_steps as f64);
        if solve_pose(spec, theta).is_some() {
            valid += 1;
        }
    }
    AssemblabilityResult {
        assembled: valid == num_steps,
        valid_samples: valid,
        total_samples: num_steps,
    }
}

/// Parses a `LinkageSpec` from either raw spec JSON or a contract document containing `"spec"`.
pub fn parse_spec(input: &str) -> Result<LinkageSpec, serde_json::Error> {
    if let Ok(spec) = serde_json::from_str::<LinkageSpec>(input) {
        return Ok(spec);
    }
    #[derive(Deserialize)]
    struct Wrapper {
        spec: LinkageSpec,
    }
    if let Ok(wrapper) = serde_json::from_str::<Wrapper>(input) {
        return Ok(wrapper.spec);
    }
    serde_json::from_str::<LinkageSpec>(input)
}

/// Returns the classic Theo Jansen 11-number linkage spec.
pub fn jansen_classic_spec() -> LinkageSpec {
    let mut params = HashMap::new();
    params.insert("a".to_string(), 38.0);
    params.insert("b".to_string(), 41.5);
    params.insert("c".to_string(), 39.3);
    params.insert("d".to_string(), 40.1);
    params.insert("e".to_string(), 55.8);
    params.insert("f".to_string(), 39.4);
    params.insert("g".to_string(), 36.7);
    params.insert("h".to_string(), 65.7);
    params.insert("i".to_string(), 49.0);
    params.insert("j".to_string(), 50.0);
    params.insert("k".to_string(), 61.9);
    params.insert("l".to_string(), 7.8);
    params.insert("m".to_string(), 15.0);

    LinkageSpec {
        params,
        crank_x: ParamRef::Named("a".to_string()),
        crank_y: ParamRef::Named("l".to_string()),
        crank_length: ParamRef::Named("m".to_string()),
        joints: vec![
            JointDef {
                id: "K".to_string(),
                centers: ("G".to_string(), "C".to_string()),
                radii: (
                    ParamRef::Named("b".to_string()),
                    ParamRef::Named("j".to_string()),
                ),
                side: 1,
            },
            JointDef {
                id: "L".to_string(),
                centers: ("G".to_string(), "K".to_string()),
                radii: (
                    ParamRef::Named("d".to_string()),
                    ParamRef::Named("e".to_string()),
                ),
                side: 1,
            },
            JointDef {
                id: "M".to_string(),
                centers: ("G".to_string(), "C".to_string()),
                radii: (
                    ParamRef::Named("c".to_string()),
                    ParamRef::Named("k".to_string()),
                ),
                side: -1,
            },
            JointDef {
                id: "N".to_string(),
                centers: ("L".to_string(), "M".to_string()),
                radii: (
                    ParamRef::Named("f".to_string()),
                    ParamRef::Named("g".to_string()),
                ),
                side: -1,
            },
            JointDef {
                id: "F".to_string(),
                centers: ("M".to_string(), "N".to_string()),
                radii: (
                    ParamRef::Named("i".to_string()),
                    ParamRef::Named("h".to_string()),
                ),
                side: 1,
            },
        ],
        foot: "F".to_string(),
    }
}
