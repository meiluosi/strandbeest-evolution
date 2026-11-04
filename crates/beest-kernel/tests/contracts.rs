use beest_kernel::{api, parse_spec, trace_checked};
use serde_json::Value;
use std::{fs, path::Path};

#[test]
fn all_shared_kinematics_contracts_and_link_invariants() {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../contracts/kinematics");
    let mut count = 0;
    for entry in fs::read_dir(dir).unwrap() {
        let text = fs::read_to_string(entry.unwrap().path()).unwrap();
        let doc: Value = serde_json::from_str(&text).unwrap();
        let spec = parse_spec(&text).unwrap();
        for sample in doc["samples"].as_array().unwrap() {
            let pose = api::pose(&spec, sample["theta"].as_f64().unwrap())
                .unwrap()
                .unwrap();
            for (id, point) in sample["points"].as_object().unwrap() {
                assert!(
                    (pose[id].0 - point[0].as_f64().unwrap()).abs() < 1e-9,
                    "{} {id}",
                    doc["name"]
                );
                assert!((pose[id].1 - point[1].as_f64().unwrap()).abs() < 1e-9);
            }
        }
        let trajectory = trace_checked(&spec, 180).unwrap();
        assert_eq!(trajectory.poses.len(), 180);
        for pose in trajectory.poses {
            for joint in &spec.joints {
                for (center, radius) in [
                    (&joint.centers.0, &joint.radii.0),
                    (&joint.centers.1, &joint.radii.1),
                ] {
                    let a = pose[&joint.id];
                    let b = pose[center];
                    assert!(
                        ((a.0 - b.0).hypot(a.1 - b.1) - spec.val(radius).unwrap()).abs() < 1e-9
                    );
                }
            }
        }
        let gait = serde_json::to_value(
            api::gait(
                &spec,
                doc["gait"]["samples"].as_u64().unwrap() as usize,
                0.015,
            )
            .unwrap(),
        )
        .unwrap();
        for key in ["width", "lift", "stroke_length", "duty"] {
            assert!(
                (gait[key].as_f64().unwrap() - doc["gait"][key].as_f64().unwrap()).abs() < 1e-6
            );
        }
        count += 1;
    }
    assert!(count >= 4);
}

#[test]
fn shared_invalid_and_degenerate_geometry_contract() {
    let corpus: Value =
        serde_json::from_str(include_str!("../../../contracts/kernel-boundaries.json")).unwrap();
    for case in corpus["cases"].as_array().unwrap() {
        let spec = parse_spec(&case["spec"].to_string()).unwrap();
        let samples = case["samples"].as_u64().unwrap_or(180) as usize;
        let result = trace_checked(&spec, samples);
        match case["outcome"].as_str().unwrap() {
            "error" => assert!(result.is_err(), "{}", case["name"]),
            "unassembled" => {
                let result = result.unwrap();
                assert!(!result.assembled);
                assert!(result.points.is_empty());
                assert!(result.poses.is_empty());
                assert!(!api::gait(&spec, 180, 0.015).unwrap().assembled);
            }
            "assembled" => assert!(result.unwrap().assembled, "{}", case["name"]),
            _ => panic!("unknown outcome"),
        }
    }
}

#[test]
fn invalid_sampling_nonfinite_inputs_and_empty_paths_are_explicit() {
    let spec = beest_kernel::jansen_classic_spec();
    assert!(trace_checked(&spec, 0).is_err());
    assert!(trace_checked(&spec, 1_000_001).is_err());
    assert!(api::pose(&spec, f64::NAN).is_err());
    assert!(api::gait(&spec, 180, -1.0).is_err());
    assert!(api::path_gait(&[(0.0, f64::INFINITY)], 0.015).is_err());
    let empty = api::path_gait(&[], 0.015).unwrap();
    assert!(!empty.assembled);
    assert_eq!(empty.duty, 0.0);
}
