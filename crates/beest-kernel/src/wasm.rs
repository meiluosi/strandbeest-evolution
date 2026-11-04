//! Web binding uses JSON for an explicit stable data boundary; no browser APIs in the kernel.
use crate::{api, parse_spec, trace_checked, LinkageSpec, Pose};
use wasm_bindgen::prelude::*;

fn error(e: impl std::fmt::Display) -> JsValue {
    JsValue::from_str(&e.to_string())
}

#[wasm_bindgen]
pub fn solve_pose_json(spec: &str, theta: f64) -> Result<String, JsValue> {
    let spec = parse_spec(spec).map_err(error)?;
    serde_json::to_string(&api::pose(&spec, theta).map_err(error)?).map_err(error)
}

#[wasm_bindgen]
pub fn trace_json(spec: &str, samples: usize) -> Result<String, JsValue> {
    let spec = parse_spec(spec).map_err(error)?;
    serde_json::to_string(&trace_checked(&spec, samples).map_err(error)?).map_err(error)
}

#[wasm_bindgen]
pub fn gait_json(points: &str, tol: f64) -> Result<String, JsValue> {
    let points: Vec<(f64, f64)> = serde_json::from_str(points).map_err(error)?;
    serde_json::to_string(&api::path_gait(&points, tol).map_err(error)?).map_err(error)
}

#[wasm_bindgen]
pub fn kernel_version() -> String {
    env!("CARGO_PKG_VERSION").into()
}

/// An owned parsed spec. JS frees the previous handle whenever any input field changes.
#[wasm_bindgen(js_name = Linkage)]
pub struct WasmLinkage {
    spec: LinkageSpec,
}

impl WasmLinkage {
    fn pack_pose(&self, pose: &Pose, output: &mut Vec<f64>) {
        for id in ["G", "C"]
            .into_iter()
            .chain(self.spec.joints.iter().map(|j| j.id.as_str()))
        {
            let point = pose[id];
            output.extend([point.0, point.1]);
        }
    }
}

#[wasm_bindgen(js_class = Linkage)]
impl WasmLinkage {
    #[wasm_bindgen(constructor)]
    pub fn new(spec_json: &str) -> Result<WasmLinkage, JsValue> {
        let spec = parse_spec(spec_json).map_err(error)?;
        api::validate_spec(&spec).map_err(error)?;
        Ok(Self { spec })
    }

    pub fn solve(&self, theta: f64) -> Result<Vec<f64>, JsValue> {
        let mut output = Vec::with_capacity((self.spec.joints.len() + 2) * 2);
        if let Some(pose) = api::pose(&self.spec, theta).map_err(error)? {
            self.pack_pose(&pose, &mut output);
        }
        Ok(output)
    }

    /// [max_step, all coordinates in sample-major, G/C/joint order]; empty means non-assembly.
    pub fn trace(&self, samples: usize) -> Result<Vec<f64>, JsValue> {
        let trajectory = trace_checked(&self.spec, samples).map_err(error)?;
        if !trajectory.assembled {
            return Ok(vec![]);
        }
        let mut output = Vec::with_capacity(1 + samples * (self.spec.joints.len() + 2) * 2);
        output.push(trajectory.max_step);
        for pose in trajectory.poses {
            self.pack_pose(&pose, &mut output);
        }
        Ok(output)
    }

    /// Shares the exact native implementation; JSON preserves integer validation.
    pub fn stride_reference_json(&self, options_json: &str) -> Result<String, JsValue> {
        let options = serde_json::from_str(options_json).map_err(error)?;
        let result = crate::stride::stride_reference(&self.spec, &options).map_err(error)?;
        serde_json::to_string(&result).map_err(error)
    }
}

#[wasm_bindgen]
pub fn gait_flat(coordinates: &[f64], tol: f64) -> Result<Vec<f64>, JsValue> {
    if coordinates.len() % 2 != 0 {
        return Err(error("expected x/y coordinate pairs"));
    }
    let path: Vec<_> = coordinates.chunks_exact(2).map(|p| (p[0], p[1])).collect();
    let gait = api::path_gait(&path, tol).map_err(error)?;
    Ok(vec![gait.width, gait.lift, gait.stroke_length, gait.duty])
}
