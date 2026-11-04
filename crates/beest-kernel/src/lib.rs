//! Unified Rust Kernel for Strandbeest Linkage Kinematics and Simulation (`beest-kernel`).

pub mod envelope;
pub mod gait;
pub mod kinematics;
pub mod stride;

pub mod api;
#[cfg(feature = "python")]
mod python;
#[cfg(feature = "wasm")]
mod wasm;

pub use envelope::{
    check_transmission_angle_safety, compute_linkage_distance_extrema, dyad_radii_envelope,
    verify_triangle_inequalities, DyadDistanceExtrema,
};
pub use gait::{
    compute_gait, compute_gait_from_foot_path, ground_stroke_mechanical_advantage,
    instantaneous_mechanical_advantage, GaitMetrics,
};
pub use kinematics::{
    check_assemblability, circle_intersection, jansen_classic_spec, parse_spec, solve_pose,
    solve_pose_checked, trace, trace_checked, AssemblabilityResult, Branch, JointDef,
    KinematicError, LinkageSpec, ParamRef, Pose, Trajectory,
};

#[cfg(feature = "python")]
pub use kinematics::TrajectoryIter;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_circle_intersection_geometric_cases() {
        // Two identical circles -> non-unique / coincident
        assert!(circle_intersection((0.0, 0.0), 5.0, (0.0, 0.0), 5.0, 1).is_none());
        // Too far apart
        assert!(circle_intersection((0.0, 0.0), 2.0, (10.0, 0.0), 2.0, 1).is_none());
        // One inside the other without touching
        assert!(circle_intersection((0.0, 0.0), 10.0, (1.0, 0.0), 2.0, 1).is_none());

        // Simple symmetric intersection: (0,0) r=5, (6,0) r=5
        // d = 6, a = 3, h = 4.
        let p_top = circle_intersection((0.0, 0.0), 5.0, (6.0, 0.0), 5.0, 1).unwrap();
        assert!((p_top.0 - 3.0).abs() < 1e-12);
        assert!((p_top.1 - 4.0).abs() < 1e-12);

        let p_bottom = circle_intersection((0.0, 0.0), 5.0, (6.0, 0.0), 5.0, -1).unwrap();
        assert!((p_bottom.0 - 3.0).abs() < 1e-12);
        assert!((p_bottom.1 - (-4.0)).abs() < 1e-12);
    }

    #[test]
    fn test_jansen_classic_eleven_numbers_exact_pose() {
        let spec = jansen_classic_spec();

        // At theta = 0.0, compare against contract baseline
        let pose0 = solve_pose(&spec, 0.0).expect("Jansen linkage must assemble at theta=0");

        let g = pose0["G"];
        assert_eq!(g, (0.0, 0.0));

        let c = pose0["C"];
        assert!((c.0 - 53.0).abs() < 1e-9);
        assert!((c.1 - 7.8).abs() < 1e-9);

        let k = pose0["K"];
        assert!(
            (k.0 - 13.986464902872).abs() < 1e-9,
            "K.x mismatch: {}",
            k.0
        );
        assert!(
            (k.1 - 39.072097454843).abs() < 1e-9,
            "K.y mismatch: {}",
            k.1
        );

        let l = pose0["L"];
        assert!(
            (l.0 - (-36.794365380936)).abs() < 1e-9,
            "L.x mismatch: {}",
            l.0
        );
        assert!(
            (l.1 - 15.943170205896).abs() < 1e-9,
            "L.y mismatch: {}",
            l.1
        );

        let m = pose0["M"];
        assert!(
            (m.0 - 11.047892968427).abs() < 1e-9,
            "M.x mismatch: {}",
            m.0
        );
        assert!(
            (m.1 - (-37.715170170081)).abs() < 1e-9,
            "M.y mismatch: {}",
            m.1
        );

        let n = pose0["N"];
        assert!(
            (n.0 - (-21.231514961415)).abs() < 1e-9,
            "N.x mismatch: {}",
            n.0
        );
        assert!(
            (n.1 - (-20.252930230748)).abs() < 1e-9,
            "N.y mismatch: {}",
            n.1
        );

        let f = pose0["F"];
        assert!(
            (f.0 - (-5.160110524105)).abs() < 1e-9,
            "F.x mismatch: {}",
            f.0
        );
        assert!(
            (f.1 - (-83.956932926123)).abs() < 1e-9,
            "F.y mismatch: {}",
            f.1
        );
    }

    #[test]
    fn test_jansen_invariants_across_cycle() {
        let spec = jansen_classic_spec();
        let samples = 72;

        let dist = |p1: (f64, f64), p2: (f64, f64)| (p1.0 - p2.0).hypot(p1.1 - p2.1);
        let pivot = (38.0, 7.8);

        for i in 0..samples {
            let theta = 2.0 * std::f64::consts::PI * (i as f64) / (samples as f64);
            let pose = solve_pose(&spec, theta).expect("Jansen must assemble throughout cycle");

            // Check link length invariants:
            // Crank length m = 15
            assert!((dist(pose["C"], pivot) - 15.0).abs() < 1e-9);
            // Joint K: dist(G, K) == b=41.5, dist(C, K) == j=50.0
            assert!((dist(pose["G"], pose["K"]) - 41.5).abs() < 1e-9);
            assert!((dist(pose["C"], pose["K"]) - 50.0).abs() < 1e-9);
            // Joint L: dist(G, L) == d=40.1, dist(K, L) == e=55.8
            assert!((dist(pose["G"], pose["L"]) - 40.1).abs() < 1e-9);
            assert!((dist(pose["K"], pose["L"]) - 55.8).abs() < 1e-9);
            // Joint M: dist(G, M) == c=39.3, dist(C, M) == k=61.9
            assert!((dist(pose["G"], pose["M"]) - 39.3).abs() < 1e-9);
            assert!((dist(pose["C"], pose["M"]) - 61.9).abs() < 1e-9);
            // Joint N: dist(L, N) == f=39.4, dist(M, N) == g=36.7
            assert!((dist(pose["L"], pose["N"]) - 39.4).abs() < 1e-9);
            assert!((dist(pose["M"], pose["N"]) - 36.7).abs() < 1e-9);
            // Foot F: dist(M, F) == i=49.0, dist(N, F) == h=65.7
            assert!((dist(pose["M"], pose["F"]) - 49.0).abs() < 1e-9);
            assert!((dist(pose["N"], pose["F"]) - 65.7).abs() < 1e-9);
        }
    }

    #[test]
    fn test_jansen_gait_metrics_match_contract() {
        let spec = jansen_classic_spec();
        let gait = compute_gait(&spec, 180, 0.015);

        assert!(gait.assembled);
        // From contracts/kinematics/jansen.json:
        // width: 67.89875413151022, lift: 22.45683436986971, stroke_length: 57.08132601641949, duty: 0.43333333333333335
        assert!((gait.width - 67.89875413151022).abs() < 1e-6);
        assert!((gait.lift - 22.45683436986971).abs() < 1e-6);
        assert!((gait.stroke_length - 57.08132601641949).abs() < 1e-6);
        assert!((gait.duty - 0.43333333333333335).abs() < 1e-6);
        assert_eq!(gait.duty_factor, gait.duty);
        assert_eq!(gait.step_height, gait.lift);
    }

    #[test]
    fn test_dyad_envelope_and_triangle_inequalities() {
        let (d_min, d_max) = dyad_radii_envelope(40.0, 30.0);
        assert_eq!(d_min, 10.0);
        assert_eq!(d_max, 70.0);

        // Valid dyad spanning distance [15, 60]
        assert!(verify_triangle_inequalities(15.0, 60.0, 40.0, 30.0, 0.0));
        // Invalid: exceeds d_max
        assert!(!verify_triangle_inequalities(15.0, 75.0, 40.0, 30.0, 0.0));
        // Invalid: violates d_min
        assert!(!verify_triangle_inequalities(5.0, 60.0, 40.0, 30.0, 0.0));
    }

    #[test]
    fn test_assemblability_check() {
        let spec = jansen_classic_spec();
        let res = check_assemblability(&spec, 180);
        assert!(res.assembled);
        assert_eq!(res.valid_samples, 180);
    }

    #[test]
    fn test_trace_and_mechanical_advantage() {
        let spec = jansen_classic_spec();
        let traj = trace(&spec, 180);
        assert_eq!(traj.points.len(), 180);
        assert!(traj.assembled);

        let ma = ground_stroke_mechanical_advantage(&spec, 180, 0.015);
        assert!(ma.is_some());
        let val = ma.unwrap();
        assert!(val > 0.0, "Mechanical advantage must be positive: {}", val);
    }
}
