import { describe, expect, it } from "vitest";
import designSchema from "../../../schemas/design.schema.json";
import scenarioSchema from "../../../schemas/scenario.schema.json";
import { extractFields, getByPath, setByPath } from "./schema-form";

describe("schema-form (E1-04)", () => {
	it("extracts design file and walker fields with units, ranges and assumption/calibratable flags", () => {
		const fields = extractFields(designSchema as Record<string, unknown>, {
			sections: ["", "walker"],
		});
		const paths = fields.map((f) => f.path);
		expect(paths).toContain("name");
		expect(paths).toContain("walker.legs");
		expect(paths).toContain("walker.unit_m");
		expect(paths).toContain("walker.body_mass_kg");

		const legs = fields.find((f) => f.path === "walker.legs");
		expect(legs?.kind).toBe("integer");
		expect(legs?.range).toEqual([1, 16]);
		expect(legs?.group).toBe("group.walker");

		const bodyMass = fields.find((f) => f.path === "walker.body_mass_kg");
		expect(bodyMass?.unit).toBe("kg");
		expect(bodyMass?.assumption).toBe(true);
		expect(bodyMass?.source).toContain("Weigh the real frame");
	});

	it("extracts scenario run and solver fields including calibratable contact_stiffness", () => {
		const fields = extractFields(scenarioSchema as Record<string, unknown>, {
			sections: ["run", "solver"],
		});
		const paths = fields.map((f) => f.path);
		expect(paths).toContain("run.revolutions");
		expect(paths).toContain("solver.contact_stiffness");
		expect(paths).toContain("solver.timestep");

		const stiffness = fields.find((f) => f.path === "solver.contact_stiffness");
		expect(stiffness?.assumption).toBe(true);
		expect(stiffness?.calibratable).toBe(true);
		expect(stiffness?.unit).toBe("1/s²");
		expect(stiffness?.range).toEqual([10000, 10000000]);
	});

	it("automatically surfaces a newly added schema field without code changes", () => {
		const mutated = JSON.parse(JSON.stringify(designSchema)) as Record<
			string,
			any
		>;
		mutated.$defs.Walker.properties.wind_drag_area_m2 = {
			type: "number",
			minimum: 0,
			"x-unit": "m²",
			"x-range": [0.001, 0.5],
			"x-group": "group.walker",
			"x-doc": {
				zh: "body wind area (zh placeholder)",
				en: "Body frontal wind area",
			},
			"x-assumption": true,
			"x-source": "Added in test to verify E1-04 dynamic discovery",
			"x-calibratable": true,
		};

		const fields = extractFields(mutated, { sections: ["", "walker"] });
		const added = fields.find((f) => f.path === "walker.wind_drag_area_m2");
		expect(added).toBeDefined();
		expect(added?.unit).toBe("m²");
		expect(added?.range).toEqual([0.001, 0.5]);
		expect(added?.assumption).toBe(true);
		expect(added?.calibratable).toBe(true);
	});

	it("reads and updates nested values via getByPath and setByPath", () => {
		const doc = { name: "beest", walker: { legs: 6, unit_m: 0.002 } };
		expect(getByPath(doc, "walker.legs")).toBe(6);
		const updated = setByPath(doc, "walker.legs", 8);
		expect(getByPath(updated, "walker.legs")).toBe(8);
		expect(doc.walker.legs).toBe(6);
	});
});
