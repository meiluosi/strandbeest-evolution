"""W-06: Virtual Dynamometer (docs/WIND.md section 5, docs/ACTIONS.md W-06).

Measures and visualizes the crank load torque curve T(theta) under slow rotation, and overlays the
aerodynamic torque curve of the sail to identify the critical stall angle theta* where the sail first loses.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from strandbeest_common import Design
from strandbeest_common.linkage import solve_pose

from .builder import resolve_spec
from .config import sim_config
from .from_design import scenario_from_design


def virtual_dynamometer(
    design: Design,
    *,
    wind_speed: float | None = None,
    samples: int = 180,
    slope_deg: float = 0.0,
    with_simulation: bool = False,
    backend: str = "k2",
) -> dict[str, Any]:
    """Calculate the virtual dynamometer load torque curve T(theta) and sail torque overlay.

    Args:
        design: The walker Design.
        wind_speed: Wind speed in m/s. If None, uses default 0.5 m/s or calculates stall threshold.
        samples: Number of angular samples over 1 revolution [0, 2*pi).
        slope_deg: Ground slope in degrees (uphill = +x).
        with_simulation: If True, also runs a slow-motor dynamic simulation using K2/MuJoCo.
        backend: Physics backend ("k2" or "mujoco").

    Returns:
        dict with angular arrays, torque curves, stall angle, and margin.
    """
    sc_base = scenario_from_design(design)
    cfg = sim_config(sc_base)
    spec = resolve_spec(cfg)

    w = cfg.walker
    u = w.unit
    n = w.legs
    direction = w.direction
    m_total = w.mass
    g = cfg.environment.gravity
    weight = m_total * g
    slope_rad = math.radians(slope_deg)

    thetas = np.linspace(0, 2 * math.pi, samples, endpoint=False)
    phases = [2 * math.pi * i / n for i in range(n)]

    # 1. Analytical Quasi-Static Torque Curve
    # H(psi): hip height = -(lowest foot y in meters)
    h_samples = []
    x_contact_samples = []

    for th in thetas:
        feet = [solve_pose(spec, th + ph)[spec.foot] for ph in phases]
        lowest_y = min(p[1] for p in feet)
        h_samples.append(-lowest_y * u)
        # Average forward position of contact feet (within 1 length unit of ground)
        contact_xs = [p[0] * u for p in feet if p[1] <= lowest_y + 1.0]
        x_contact_samples.append(float(np.mean(contact_xs)) if contact_xs else 0.0)

    h_arr = np.array(h_samples)
    dh_dpsi = np.gradient(h_arr, thetas)

    # Forward displacement rate per radian
    x_contact_arr = np.array(x_contact_samples)
    dx_dpsi = -direction * np.gradient(x_contact_arr, thetas)

    # Virtual work: T dpsi = W sin(slope) dX + W cos(slope) dH + pin_friction
    pin_friction = getattr(w, "joint_friction", 0.0)
    tau_quasi = (
        (weight * math.sin(slope_rad)) * np.abs(dx_dpsi)
        + (weight * math.cos(slope_rad)) * dh_dpsi
        + pin_friction
    )

    peak_quasi = float(np.max(tau_quasi))
    min_quasi = float(np.min(tau_quasi))
    mean_quasi = float(np.mean(tau_quasi))
    stall_idx = int(np.argmax(tau_quasi))
    stall_theta = float(thetas[stall_idx])
    stall_angle_deg = float(math.degrees(stall_theta))

    # 2. Sail Drive Aerodynamic Torque
    # Sail parameters
    d_sail = design.doc.get("drive", {}).get("sail", {})
    sail_area = float(d_sail.get("area_m2", 0.03))
    sail_radius = float(d_sail.get("radius_m", 0.08))
    sail_gear = float(d_sail.get("gear", 10.0))
    drag_coeff = float(d_sail.get("drag_coeff", 1.2))
    air_density = float(cfg.environment.air_density if hasattr(cfg.environment, "air_density") else 1.225)

    # Aerodynamic torque at zero crank speed (startup condition)
    # tau_sail = gear * 0.5 * rho * Cd * A * r * v_wind^2
    aero_factor = sail_gear * 0.5 * air_density * drag_coeff * sail_area * sail_radius

    # Minimum start wind required to overcome peak torque at startup
    min_start_wind = math.sqrt(max(0.0, peak_quasi) / aero_factor) if aero_factor > 0 else float("inf")

    # Evaluate for requested wind speed
    active_wind = wind_speed if wind_speed is not None else min_start_wind
    tau_sail_val = aero_factor * (active_wind**2)
    tau_sail_curve = [float(tau_sail_val)] * samples

    # Net stall margin: tau_sail - T_load(theta)
    margin_curve = [float(tau_sail_val - tq) for tq in tau_quasi]
    min_margin = float(np.min(margin_curve))
    stalls = bool(min_margin < 0.0)

    res: dict[str, Any] = {
        "theta": [float(t) for t in thetas],
        "theta_deg": [float(math.degrees(t)) for t in thetas],
        "torque_quasi": [float(t) for t in tau_quasi],
        "torque_sail": tau_sail_curve,
        "margin": margin_curve,
        "peak_torque": peak_quasi,
        "min_torque": min_quasi,
        "mean_torque": mean_quasi,
        "stall_theta": stall_theta,
        "stall_angle_deg": stall_angle_deg,
        "min_start_wind": float(min_start_wind),
        "wind_speed": float(active_wind),
        "stall_margin": min_margin,
        "stalls": stalls,
        "hip_height_ripple_mm": float(np.ptp(h_arr) * 1000.0),
        "sail_parameters": {
            "area_m2": sail_area,
            "radius_m": sail_radius,
            "gear": sail_gear,
            "drag_coeff": drag_coeff,
            "aero_factor": aero_factor,
        },
    }

    # 3. Dynamic Simulation Cross-Check (Slow Motor)
    if with_simulation:
        from .runner import run

        ov = {
            "drive": {"omega": 0.2, "ramp": 0.1},
            "solver": {"timestep": 0.001},
            "run": {
                "revolutions": 1.0,
                "settle": 0.2,
                "max_time": 40.0,
                "frame_rate": 0,
                "record_every": 10,
            },
        }
        if slope_deg:
            ov["terrain"] = {"kind": "slope", "slope_deg": slope_deg}

        sc = scenario_from_design(design, ov)
        sim_res = run(sc, backend=backend)

        # Interpolate simulation torque onto the uniform theta grid
        psi_norm = np.mod(sim_res.psi, 2 * math.pi)
        sort_idx = np.argsort(psi_norm)
        sorted_psi = psi_norm[sort_idx]
        sorted_tau = sim_res.torque[sort_idx]

        sim_interp = np.interp(thetas, sorted_psi, sorted_tau)
        res["torque_sim"] = [float(t) for t in sim_interp]
        res["sim_peak_torque"] = float(np.max(sim_interp))
        res["sim_mean_torque"] = float(np.mean(sim_interp))

    return res
