/// <reference types="node" />
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import Ajv2020 from "ajv/dist/2020";
import { describe, expect, it } from "vitest";
import { jansenSpec } from "./jansen";

// The schemas live at the repo root and are shared with the Python packages.
const dir = join(import.meta.dirname, "../../../schemas");
const load = (f: string) => JSON.parse(readFileSync(join(dir, f), "utf8"));
const ajv = new Ajv2020({ strict: false });
const validators = Object.fromEntries(
	["design", "measurement", "profile", "run"].map((n) => [
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

	it("a Design built from core's jansenSpec() validates", () => {
		const design = {
			schema_version: 1,
			name: "from-core",
			linkage: jansenSpec(),
			walker: { legs: 4, unit_m: 0.002, direction: -1, body_mass_kg: 0.3 },
			drive: { kind: "motor", motor_omega_rad_s: 2 },
			manufacturing: {
				process: "fdm",
				material: "PLA",
				bar_width_mm: 10,
				bar_thickness_mm: 3,
				pin_diameter_mm: 3,
				clearance_mm: 0.3,
			},
		};
		const v = validators.design;
		expect(v?.(design), JSON.stringify(v?.errors)).toBe(true);
	});

	it("rejects a design with an unknown field", () => {
		const bad = { ...load("examples/design-jansen-small-6leg.json"), extra: 1 };
		expect(validators.design?.(bad)).toBe(false);
	});
});
