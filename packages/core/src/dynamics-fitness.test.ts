import { describe, expect, it } from "vitest";
import { fitnessWindSpeed } from "./dynamics-fitness";
import { JANSEN_SPACE } from "./genome";

const jansen = JANSEN_SPACE.toGenome();

describe("fitnessWindSpeed", () => {
	it("gives Jansen's leg a positive speed in a fresh breeze", () => {
		expect(fitnessWindSpeed(JANSEN_SPACE, { wind: 6 })(jansen)).toBeGreaterThan(
			0,
		);
	});

	it("is faster in stronger wind", () => {
		expect(
			fitnessWindSpeed(JANSEN_SPACE, { wind: 10 })(jansen),
		).toBeGreaterThan(fitnessWindSpeed(JANSEN_SPACE, { wind: 5 })(jansen));
	});

	it("penalises a leg that cannot start in a very weak wind below any running speed", () => {
		const weak = fitnessWindSpeed(JANSEN_SPACE, { wind: 0.1 })(jansen);
		expect(weak).toBeLessThan(0);
	});

	it("penalises broken legs below working ones", () => {
		const broken = jansen.slice();
		broken[7] = 1;
		expect(fitnessWindSpeed(JANSEN_SPACE, { wind: 6 })(broken)).toBeLessThan(
			fitnessWindSpeed(JANSEN_SPACE, { wind: 6 })(jansen),
		);
	});
});
