"""Describe the simulated scene (geometry in body-local frames) so a viewer can replay the recorded frames."""

from __future__ import annotations

import mujoco
import numpy as np


def _rot(vec, quat):
    out = np.zeros(3)
    mujoco.mju_rotVecQuat(out, np.asarray(vec, float), np.asarray(quat, float))
    return out


def describe_scene(model: mujoco.MjModel, slope_deg: float = 0.0) -> dict:
    """Bodies (excluding the world) with their geoms, plus static obstacles. Frame arrays index bodies by position in `bodies`."""
    bodies = [mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, i) for i in range(1, model.nbody)]
    geoms, obstacles = [], []
    for g in range(model.ngeom):
        gtype = int(model.geom_type[g])
        body = int(model.geom_bodyid[g])
        rgba = [round(float(x), 3) for x in model.geom_rgba[g]]
        pos, quat, size = model.geom_pos[g], model.geom_quat[g], model.geom_size[g]
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, g) or ""
        if body == 0:
            if gtype == mujoco.mjtGeom.mjGEOM_BOX:  # obstacles on the ground
                obstacles.append({"pos": [round(float(x), 4) for x in pos], "size": [round(float(x), 4) for x in size], "name": name})
            continue
        item = {"body": body - 1, "name": name, "rgba": rgba, "foot": name.startswith("foot_")}
        if gtype == mujoco.mjtGeom.mjGEOM_CAPSULE:
            axis = _rot([0, 0, size[1]], quat)
            item.update(type="capsule", a=[round(float(x), 5) for x in pos - axis], b=[round(float(x), 5) for x in pos + axis], radius=round(float(size[0]), 5))
        elif gtype == mujoco.mjtGeom.mjGEOM_SPHERE:
            item.update(type="sphere", pos=[round(float(x), 5) for x in pos], radius=round(float(size[0]), 5))
        elif gtype == mujoco.mjtGeom.mjGEOM_BOX:
            item.update(type="box", pos=[round(float(x), 5) for x in pos], quat=[round(float(x), 6) for x in quat], size=[round(float(x), 5) for x in size])
        else:
            continue
        geoms.append(item)
    return {"bodies": bodies, "geoms": geoms, "obstacles": obstacles, "slope_deg": slope_deg}
