import { describe, expect, it } from "vitest";
import { fmtG9, pyFloat } from "./pyfmt";
import { PyRandom } from "./pyrandom";

// expected strings were produced by CPython 3.12 (`f"{v:.9g}"` and `repr(v)`)
describe("python number formatting", () => {
	it("fmtG9 matches format(v, '.9g')", () => {
		const cases: [number, string][] = [
			[0, "0"],
			[-0, "-0"],
			[0.002, "0.002"],
			[1e-6, "1e-06"],
			[0.0001, "0.0001"],
			[0.00001234, "1.234e-05"],
			[123456789, "123456789"],
			[1234567891, "1.23456789e+09"],
			[0.1 + 0.2, "0.3"],
			[-2.0943951023931953, "-2.0943951"],
			[100, "100"],
			[1 / 3, "0.333333333"],
		];
		for (const [v, s] of cases) expect(fmtG9(v), String(v)).toBe(s);
	});

	it("pyFloat matches repr(float)", () => {
		const cases: [number, string][] = [
			[300000, "300000.0"],
			[0.0001, "0.0001"],
			[0.00001, "1e-05"],
			[1e16, "1e+16"],
			[1e15, "1000000000000000.0"],
			[0.1 + 0.2, "0.30000000000000004"],
			[-0.3, "-0.3"],
			[9.81, "9.81"],
			[1.5, "1.5"],
			[2.5e-7, "2.5e-07"],
			[-0, "-0.0"],
		];
		for (const [v, s] of cases) expect(pyFloat(v), String(v)).toBe(s);
	});
});

describe("PyRandom", () => {
	it("draws the numbers CPython draws for random.Random(3)", () => {
		const r = new PyRandom(3);
		// random.Random(3): [random() x3]
		expect([r.random(), r.random(), r.random()]).toEqual([
			0.23796462709189137, 0.5442292252959519, 0.36995516654807925,
		]);
	});
});
