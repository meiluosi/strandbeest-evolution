"""CLI script to run H4-01 / V-05 / H3-03 Binnenhof video validation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from strandbeest_calib.binnenhof_video import (
    CALIBRATED_MPP,
    SCALE_UNCERTAINTY_MPP,
    THEO_JANSEN_HEIGHT_M,
    ANIMARIS_HEIGHT_M,
    build_measurement_asset,
    extract_shot3_frames,
    run_digital_twin_forward_comparison,
    run_video_tracking,
)
from strandbeest_calib.community import validate_submission

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_VIDEO_PATH = Path("/tmp/strandbeest-video-2026-11-06/binnenhof_walking.webm")
OUT_MEASUREMENT_PATH = ROOT / "experiments" / "measurement-binnenhof-walker-v2.json"
OUT_EXPERIMENT_PATH = ROOT / "experiments" / "external-binnenhof-video-validation-2026-11-06.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Process Binnenhof Strandbeest walking footage for H4-01 / V-05 / H3-03 validation.")
    parser.add_argument(
        "--video-path",
        type=Path,
        default=DEFAULT_VIDEO_PATH,
        help="Path to the Binnenhof walking video file (defaults to /tmp/strandbeest-video-2026-11-06/binnenhof_walking.webm)",
    )
    args = parser.parse_args()
    video_path = args.video_path

    print(f"Loading Binnenhof walking video from {video_path}...")
    frames, fps = extract_shot3_frames(video_path, start_frame=650, num_frames=300)
    print(f"Extracted {len(frames)} frames at {fps:.2f} fps.")

    print("Running optical flow feature tracking on walker chassis...")
    track_data = run_video_tracking(frames, fps)
    print(f"Tracking completed: {track_data['dx_m']:.4f} m in {track_data['dt_s']:.2f} s")
    print(f"Forward speed: {track_data['v_mean_m_s']:.4f} m/s, Cadence: {track_data['f_crank_hz']:.3f} Hz")
    print(f"Empirical stride per revolution: {track_data['stride_per_rev_m']:.4f} m")

    print("Building and validating Schema v2 Measurement asset...")
    measurement_doc = build_measurement_asset(track_data)
    OUT_MEASUREMENT_PATH.write_text(json.dumps(measurement_doc, indent=2), encoding="utf-8")
    print(f"Saved Measurement asset to {OUT_MEASUREMENT_PATH}")

    # Validate with community validator
    rep = validate_submission(measurement_doc)
    print("\n--- Community Submission Quality Report ---")
    print(rep.render())

    print("\nRunning forward digital twin simulation comparison...")
    comparison = run_digital_twin_forward_comparison(track_data)
    print(f"Physical Stride:  {comparison['stride_physical_m']:.4f} +/- {comparison['stride_physical_uncertainty_m']:.4f} m")
    print(f"MuJoCo Stride:    {comparison['stride_mujoco_simulation_m']:.4f} m (diff: {comparison['rel_diff_mujoco_pct']:.2f}%)")
    print(f"Kinematic Stride: {comparison['stride_kinematic_ideal_m']:.4f} m (diff: {comparison['rel_diff_kinematic_pct']:.2f}%)")
    print(f"Within 95% uncertainty envelope: {comparison['within_uncertainty_envelope']}")

    experiment_record = {
        "date": "2026-11-06",
        "task": "H4-01 / V-05 / H3-03",
        "evidence_level": "E2 (Kinematic position, speed, and stride from traceable physical video)",
        "source_video": {
            "title": "Het Strandbeest van kunstenaar Theo Jansen loopt over het Binnenhof",
            "url": "https://commons.wikimedia.org/wiki/File:Het_Strandbeest_van_kunstenaar_Theo_Jansen_loopt_over_het_Binnenhof.webm",
            "license": "CC BY 3.0",
            "author": "Tweede Kamer der Staten-Generaal",
            "sha256": "9944c693e7326d19c839b208790230fea1b03532eed189cedcd72cc76772e478",
            "date": "2016-04-13",
        },
        "tracking_results": track_data,
        "digital_twin_comparison": comparison,
        "submission_report": rep.asdict(),
    }
    OUT_EXPERIMENT_PATH.write_text(json.dumps(experiment_record, indent=2), encoding="utf-8")
    print(f"Saved experiment record to {OUT_EXPERIMENT_PATH}")


if __name__ == "__main__":
    main()
