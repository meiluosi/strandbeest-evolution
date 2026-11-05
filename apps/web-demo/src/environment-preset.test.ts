import { describe, expect, it } from "vitest";
import { environmentForReplay } from "./environment-preset";
import type { Replay } from "./replay-types";

function world(gravity: number, airDensity: number): Replay {
	return {
		info: { environment: { gravity, air_density: airDensity } },
	} as Replay;
}

describe("environment art presets", () => {
	it("uses a moonlit sea only for Earth-like runs", () => {
		const preset = environmentForReplay(world(9.81, 1.2));
		expect(preset.kind).toBe("earth");
		expect(preset.sea).toBe(true);
		expect(preset.moonDisc).toBe(true);
	});

	it("never decorates the airless Moon with a liquid sea", () => {
		const preset = environmentForReplay(world(1.62, 0));
		expect(preset.kind).toBe("moon");
		expect(preset.sea).toBe(false);
		expect(preset.stars).toBe(true);
	});

	it("distinguishes Mars, Titan and Venus without changing their inputs", () => {
		expect(environmentForReplay(world(3.73, 0.02)).kind).toBe("mars");
		expect(environmentForReplay(world(1.35, 5.4)).kind).toBe("titan");
		expect(environmentForReplay(world(8.87, 65)).kind).toBe("venus");
	});
});
