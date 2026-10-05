/// <reference types="node" />
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import Ajv2020 from "ajv/dist/2020";
import { describe, expect, it } from "vitest";
import { defaultDesign } from "./design";
import type { Design, Scenario } from "./index";
import { JANSEN_LENGTHS } from "./jansen";

// The schemas live at the repo root and are shared with the Python packages.
const dir = join(import.meta.dirname, "../../../schemas");
const load = (f: string) => JSON.parse(readFileSync(join(dir, f), "utf8"));
const ajv = new Ajv2020({ strict: false });
const validators = Object.fromEntries(
	["design", "scenario", "measurement", "profile", "run"].map((n) => [
		n,
		ajv.compile(load(`${n}.schema.json`)),
	]),
);

describe("shared JSON schemas", () => {
	for (const f of readdirSync(join(dir, "examples"))) {
		it(`example ${f} validates`, () => {
			const name = f.split("-")[0] as string;
			const validate = validators[name];
			expect(
				validate?.(load(`examples/${f}`)),
				JSON.stringify(validate?.errors),
			).toBe(true);
		});
	}

	it("a Design built by defaultDesign() validates", () => {
		const v = validators.design;
		const design = defaultDesign();
		expect(v?.(design), JSON.stringify(v?.errors)).toBe(true);
	});

	it("rejects a design with an unknown field", () => {
		const bad = { ...load("examples/design-jansen-small-6leg.json"), extra: 1 };
		expect(validators.design?.(bad)).toBe(false);
	});

	it("the generated Scenario type accepts a partial document and the schema validates it", () => {
		// compile-time: Scenario is generated from schemas/scenario.schema.json (all fields optional, defaults in the schema)
		const sc: Scenario = {
			name: "t",
			walker: { legs: 6, direction: -1 },
			solver: { contact_stiffness: null },
		};
		const v = validators.scenario;
		expect(v?.(sc), JSON.stringify(v?.errors)).toBe(true);
		expect(v?.({ walker: { legs: 0 } })).toBe(false);
		expect(v?.({ walker: { direction: 0 } })).toBe(false);
		expect(v?.({ unknown: 1 })).toBe(false);
	});

	it("the generated Design type is what defaultDesign returns", () => {
		const d: Design = defaultDesign();
		expect(d.walker.legs).toBe(6);
	});
});
