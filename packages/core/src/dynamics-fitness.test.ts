import { describe, expect, it } from "vitest";
import { fitnessWindSpeed } from "./dynamics-fitness";
import { paramsToGenome } from "./fitness";
import { JANSEN_LENGTHS } from "./jansen";

const jansen = paramsToGenome(JANSEN_LENGTHS);

describe("fitnessWindSpeed", () => {
	it("gives Jansen's leg a positive speed in a fresh breeze", () => {
		expect(fitnessWindSpeed({ wind: 6 })(jansen)).toBeGreaterThan(0);
	});

	it("is faster in stronger wind", () => {
		expect(fitnessWindSpeed({ wind: 10 })(jansen)).toBeGreaterThan(
			fitnessWindSpeed({ wind: 5 })(jansen),
		);
	});

	it("penalises a leg that cannot start in a very weak wind below any running speed", () => {
		const weak = fitnessWindSpeed({ wind: 0.1 })(jansen);
		expect(weak).toBeLessThan(0);
	});

	it("penalises broken legs below working ones", () => {
		const broken = jansen.slice();
		broken[7] = 1;
		expect(fitnessWindSpeed({ wind: 6 })(broken)).toBeLessThan(
			fitnessWindSpeed({ wind: 6 })(jansen),
		);
	});
});
