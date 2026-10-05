from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from .calibration import Calibration, fit_torque_from_hanging_masses
from .convert import convert_raw


def _load_track(path: str) -> tuple[np.ndarray, np.ndarray]:
    a = np.genfromtxt(path, delimiter=",", names=True)
    return np.asarray(a["t_s"], float), np.asarray(a["x_m"], float)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="strandbeest-rig")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("convert", help="raw rig CSV -> Measurement JSON with a quality report")
    c.add_argument("raw")
    c.add_argument("--calibration", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--id", required=True)
    c.add_argument("--design-name", required=True)
    c.add_argument("--kind", choices=["motor_no_wind", "fan"], default="motor_no_wind")
    c.add_argument("--omega", type=float)
    c.add_argument("--wind", type=float)
    c.add_argument("--surface", default="")
    c.add_argument("--track", help="CSV from `track` (t_s,x_m)")
    c.add_argument("--track-offset", type=float, help="seconds added to the video clock; default: align by motion onset")

    t = sub.add_parser("track", help="ArUco marker in a side-view video -> t_s,x_m CSV")
    t.add_argument("video")
    t.add_argument("--marker-id", type=int, required=True)
    t.add_argument("--marker-mm", type=float, required=True, help="printed side length of the marker")
    t.add_argument("--out", required=True)
    t.add_argument("--forward-left", action="store_true")

    v = sub.add_parser("virtual", help="simulate a rig run and write raw CSV (+ track CSV) for testing the software chain")
    v.add_argument("design")
    v.add_argument("--calibration")
    v.add_argument("--out", required=True)
    v.add_argument("--omega", type=float, default=2.0)
    v.add_argument("--revolutions", type=float, default=3.0)

    k = sub.add_parser("torque-cal", help="fit torque constant and idle current from hanging-mass data")
    k.add_argument("csv", help="columns: mass_g,current_mA")
    k.add_argument("--arm-m", type=float, required=True)

    g = sub.add_parser("log", help="log the serial stream to a file (needs pyserial and a rig)")
    g.add_argument("port")
    g.add_argument("--baud", type=int, default=115200)
    g.add_argument("--out", required=True)
    g.add_argument("--duration", type=float, required=True)
    g.add_argument("--omega", type=float)

    n = sub.add_parser("calibration-template", help="write a calibration JSON to edit")
    n.add_argument("out")

    a = ap.parse_args(argv)
    if a.cmd == "convert":
        cal = Calibration.load(a.calibration)
        track = _load_track(a.track) if a.track else None
        doc = convert_raw(Path(a.raw).read_text(), cal, id=a.id, design_name=a.design_name, kind=a.kind, omega_rad_s=a.omega,
                          wind_m_s=a.wind, surface=a.surface, raw_name=Path(a.raw).name, track=track, track_offset_s=a.track_offset)
        Path(a.out).write_text(json.dumps(doc))
        print(json.dumps(doc["quality"], indent=2))
    elif a.cmd == "track":
        from .video_track import track_marker

        r = track_marker(a.video, a.marker_id, a.marker_mm, forward_is_left=a.forward_left)
        Path(a.out).write_text("t_s,x_m\n" + "\n".join(f"{ti:.4f},{xi:.6f}" for ti, xi in zip(r.t, r.x)) + "\n")
        print(json.dumps({"frames": r.frames, "fps": r.fps, "detected_fraction": round(r.detected_fraction, 3),
                          "mm_per_pixel": round(r.metres_per_pixel * 1000, 4), "warnings": r.warnings}, indent=2))
    elif a.cmd == "virtual":
        from strandbeest_common import Design

        from .virtual_rig import virtual_raw_csv

        cal = Calibration.load(a.calibration) if a.calibration else Calibration(calibrated=True)
        raw, (tt, xx) = virtual_raw_csv(Design.load(a.design), cal, omega=a.omega, revolutions=a.revolutions)
        Path(a.out).write_text(raw)
        track_path = Path(a.out).with_suffix(".track.csv")
        track_path.write_text("t_s,x_m\n" + "\n".join(f"{ti:.4f},{xi:.6f}" for ti, xi in zip(tt, xx)) + "\n")
        print(f"wrote {a.out} and {track_path}")
    elif a.cmd == "torque-cal":
        d = np.genfromtxt(a.csv, delimiter=",", names=True)
        fit = fit_torque_from_hanging_masses(list(d["mass_g"]), list(d["current_mA"]), a.arm_m)
        print(json.dumps({"kt_nm_per_a": fit.kt_nm_per_a, "idle_current_ma": fit.idle_current_ma, "residual_nm": fit.residual_nm, "n": fit.n}, indent=2))
    elif a.cmd == "log":
        from .serial_log import log_serial

        print(f"wrote {log_serial(a.port, a.baud, a.out, a.duration, a.omega)} lines to {a.out}")
    elif a.cmd == "calibration-template":
        Path(a.out).write_text(json.dumps(Calibration().asdict(), indent=2))
        print(f"wrote {a.out}; edit it, then set calibrated=true once you have checked the constants")
    else:  # pragma: no cover
        sys.exit(2)


if __name__ == "__main__":
    main()
