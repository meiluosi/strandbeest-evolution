import { describe, expect, it } from "vitest";
import { jansenSpec } from "./jansen";
import { evenPhases, groundContactCounts, multiLegFeet } from "./multileg";

describe("multi-leg", () => {
	const spec = jansenSpec();

	it("spaces phases evenly", () => {
		const p = evenPhases(4).map((l) => l.phase);
		expect(p[1]).toBeCloseTo(Math.PI / 2);
		expect(p[3]).toBeCloseTo((3 * Math.PI) / 2);
	});

	it("shares one path across legs, shifted in time", () => {
		const feet = multiLegFeet(spec, evenPhases(4), 120) as NonNullable<
			ReturnType<typeof multiLegFeet>
		>;
		expect(feet[1]?.[0]).toEqual(feet[0]?.[30]);
	});

	it("keeps at least one foot on the ground with 6 legs per side at all times", () => {
		const feet = multiLegFeet(spec, evenPhases(6), 120) as NonNullable<
			ReturnType<typeof multiLegFeet>
		>;
		const counts = groundContactCounts(feet);
		expect(Math.min(...counts)).toBeGreaterThanOrEqual(1);
	});
});
