"""Printability checks. Thresholds are rules of thumb for FDM, not guarantees."""

from __future__ import annotations

from dataclasses import dataclass

from strandbeest_common import Design

from .parts import GAP_MM, LegPlan


@dataclass
class Check:
    name: str
    status: str  # "pass" | "warn" | "fail"
    value: float | str
    limit: str
    note: str = ""


def run_checks(design: Design, plan: LegPlan) -> list[Check]:
    m = design.mfg
    hole = m["pin_diameter_mm"] + m["clearance_mm"]
    wall = m["bar_width_mm"] / 2 - hole / 2
    min_wall = m.get("min_wall_mm", 1.2)
    layer_h = m.get("layer_height_mm", 0.2)
    bed = m.get("bed_mm", [220, 220])
    longest = max(b.length_mm for b in plan.bars) + m["bar_width_mm"]
    out: list[Check] = []

    def add(name, ok, value, limit, note="", warn=False):
        out.append(Check(name, "pass" if ok else ("warn" if warn else "fail"), value, limit, note))

    add("wall around pin hole", wall >= min_wall, round(wall, 3), f">= {min_wall} mm", "bar end must not be too thin around the hole")
    add("clearance", 0.15 <= m["clearance_mm"] <= 0.6, m["clearance_mm"], "0.15 – 0.6 mm",
        "too tight fuses, too loose wobbles; tune after a test print", warn=True)
    add("bar thickness", m["bar_thickness_mm"] >= 2 * layer_h, m["bar_thickness_mm"], f">= {2 * layer_h:.2f} mm (2 layers)")
    add("pin diameter", m["pin_diameter_mm"] >= 2.5, m["pin_diameter_mm"], ">= 2.5 mm", "thin pins bend", warn=True)
    add("longest part fits bed", longest <= min(bed), round(longest, 1), f"<= {min(bed)} mm")
    add("aspect ratio of longest bar", longest / m["bar_width_mm"] <= 20, round(longest / m["bar_width_mm"], 1), "<= 20",
        "very slender bars warp and flex", warn=True)
    stack = plan.layers * (m["bar_thickness_mm"] + GAP_MM)
    add("leg stack height", True, round(stack, 1), "informational", f"{plan.layers} layers per leg; legs sit side by side along the axle")
    return out
