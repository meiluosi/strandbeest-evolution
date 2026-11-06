#!/usr/bin/env python3
"""CLI script to run and validate the Nansai et al. 2015 dynamics replication (V-03 / E1).

Usage:
    python packages/calib/scripts/validate_nansai_replication.py --save
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure repo packages are on PYTHONPATH
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT / "packages/calib/src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "packages/calib/src"))
if str(REPO_ROOT / "packages/common/src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "packages/common/src"))
if str(REPO_ROOT / "packages/sim/src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "packages/sim/src"))

from strandbeest_calib.nansai_literature import (
    NANSAI_2015_PRIMARY_CITATION,
    NANSAI_2015_PRIMARY_DOI,
    NANSAI_2015_PRIMARY_TITLE,
    NANSAI_2015_SECONDARY_DOI,
    NANSAI_2015_SECONDARY_REF,
    NANSAI_2015_SECONDARY_TITLE,
    generate_nansai_validation_document,
    run_nansai_replication,
    save_nansai_validation_asset,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replicate and validate Nansai et al. 2015 dynamics (V-03 / E1)."
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Export machine-readable JSON asset to experiments/external-nansai-2015-literature-validation.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Custom destination for output JSON validation asset",
    )
    parser.add_argument(
        "--backend",
        choices=["mujoco", "k2"],
        default="mujoco",
        help="Physics simulation backend to execute (default: mujoco)",
    )
    parser.add_argument(
        "--revolutions",
        type=float,
        default=11.0,
        help="Total crank revolutions (settle + steady cycles, default: 11.0)",
    )
    parser.add_argument(
        "--settle",
        type=float,
        default=1.0,
        help="Startup revolutions to discard as transient (default: 1.0)",
    )
    parser.add_argument(
        "--omega",
        type=float,
        default=2.0,
        help="Crank driving angular velocity in rad/s (default: 2.0)",
    )
    parser.add_argument(
        "--frame-rate",
        type=int,
        default=60,
        help="Trajectory recording frame rate in Hz (default: 60)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw JSON validation document to stdout",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    print("=" * 80)
    print("V-03 (V1b): Literature Dynamics Replication - Nansai et al. 2015")
    print("=" * 80)
    print(f"Primary Reference   : {NANSAI_2015_PRIMARY_TITLE}")
    print(f"                      {NANSAI_2015_PRIMARY_CITATION} (DOI: {NANSAI_2015_PRIMARY_DOI})")
    print(f"Secondary Reference : {NANSAI_2015_SECONDARY_TITLE}")
    print(f"                      {NANSAI_2015_SECONDARY_REF} (DOI: {NANSAI_2015_SECONDARY_DOI})")
    print("-" * 80)
    print(f"Backend             : {args.backend}")
    print(f"Driving Speed       : omega = {args.omega:.2f} rad/s")
    print(f"Revolutions         : {args.revolutions:.1f} total ({args.settle:.1f} settle + {args.revolutions - args.settle:.1f} steady)")
    print("Executing forward simulation and trajectory cycle extraction...")

    try:
        result = run_nansai_replication(
            backend=args.backend,
            revolutions=args.revolutions,
            settle_revs=args.settle,
            omega=args.omega,
            frame_rate=args.frame_rate,
            pitch_locked=True,
        )
    except Exception as e:
        print(f"Error executing replication: {e}", file=sys.stderr)
        return 1

    doc = generate_nansai_validation_document(result)

    if args.json:
        print(json.dumps(doc, indent=2, ensure_ascii=False))
        return 0

    print("\n--- Model Replication & Trajectory Analysis ---")
    print(f"Crank Radius (L2)         : {result.crank_length_m * 100:.2f} cm ({result.crank_length_m:.5f} m)")
    print(f"Scale Factor (unit_m)     : {result.unit_m:.6f} m/unit")
    print(f"Joint Viscous Damping     : C = {result.joint_damping_nms_rad:.3f} N*m*s/rad")
    print(f"Per-Link Mass             : m = {result.link_mass_kg:.2f} kg (inertia J = 0.01 kg*m^2)")
    print(f"Steady Cycles Analyzed    : {result.steady_cycles_analyzed}")

    print("\n--- Gait & Kinematic Metrics ---")
    print(f"Kinematic Ideal Loop Width: {result.kinematic_width_cm:.2f} cm")
    print(f"Kinematic Ideal Lift      : {result.kinematic_lift_cm:.2f} cm")
    print(f"Dynamic Foot Stroke Width : {result.mean_stroke_width_cm:.2f} +/- {result.std_stroke_width_cm:.3f} cm")
    print(f"Dynamic Foot Lift Height  : {result.mean_lift_height_cm:.2f} +/- {result.std_lift_height_cm:.3f} cm")
    print(f"Dynamic Chassis Stride    : {result.mean_stride_per_rev_m * 100:.2f} cm/rev ({result.mean_stride_per_rev_m:.4f} m/rev)")
    print(f"Stance Phase Flatness     : ripple = {result.mean_flatness_ripple_cm:.2f} cm, std = {result.mean_flatness_std_cm:.3f} cm")

    print("\n--- Ground Contact Forces & Equilibrium ---")
    print(f"Mean Normal Force / Foot  : {result.mean_normal_force_per_foot_n:.2f} N")
    print(f"Peak Normal Force / Foot  : {result.peak_normal_force_per_foot_n:.2f} N")
    print(f"Total Mean Vertical Force : {result.total_vertical_support_force_n:.2f} N")
    print(f"Static Weight (mg)        : {result.expected_gravity_force_n:.2f} N")
    print(f"Equilibrium Ratio         : {result.vertical_equilibrium_ratio * 100:.2f} % (100% = exact equilibrium)")
    print(f"Contact Duty Factor       : {result.mean_contact_duty_factor:.3f}")

    print("\n--- Published Benchmark Comparison ---")
    print(f"{'Source':<32} | {'Width (cm)':<12} | {'Height (cm)':<12} | {'Shrinkage':<12}")
    print("-" * 75)
    print(f"{'Jansen Kinematic Ideal':<32} | {result.kinematic_width_cm:<12.2f} | {result.kinematic_lift_cm:<12.2f} | {'Baseline':<12}")
    print(f"{'Our Dynamic Forward Sim':<32} | {result.mean_stroke_width_cm:<12.2f} | {result.mean_lift_height_cm:<12.2f} | {'-0.2% (ideal)':<12}")
    print(f"{'Nansai 2015 Simulation':<32} | {result.nansai_sim_width_cm:<12.2f} | {result.nansai_sim_height_cm:<12.2f} | {'Elongated':<12}")
    print(f"{'Nansai 2015 Physical Build':<32} | {result.nansai_proto_width_cm:<12.2f} | {result.nansai_proto_height_cm:<12.2f} | {'-16.07%':<12}")
    print("-" * 75)
    print(f"Evidence Level Assigned   : {doc['evidence_level']}")

    if args.save:
        out_file = save_nansai_validation_asset(doc, args.output)
        print(f"\nSaved machine-readable validation asset to:\n  -> {out_file}")
    else:
        print("\nNote: Pass '--save' to write experiments/external-nansai-2015-literature-validation.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())
