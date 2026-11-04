import { readFileSync } from "node:fs";
import loadMujoco from "@mujoco/mujoco";
import type { Design } from "strandbeest-core";
import { beforeAll, expect, it } from "vitest";
import { buildMjcf, resolveSpec } from "./builder";
import { simConfig } from "./config";
import { scenarioFromDesign } from "./from-design";

const design = JSON.parse(
	readFileSync(
		new URL(
			"../../../schemas/examples/design-jansen-small-6leg.json",
			import.meta.url,
		),
		"utf8",
	),
) as Design;
let mj: Awaited<ReturnType<typeof loadMujoco>>;
beforeAll(async () => {
	mj = await loadMujoco();
});

it.each([undefined, null, 0, 1e-12, 1e-10])(
	"persists the precision request and compiles it in WASM: %s",
	(tolerance) => {
		const cfg = scenarioFromDesign(design, {
			solver: tolerance === undefined ? {} : { tolerance },
		});
		const reloaded = simConfig(JSON.parse(JSON.stringify(cfg)));
		expect(reloaded).toEqual(cfg);
		expect(reloaded.solver.tolerance).toBe(tolerance ?? null);
		const { xml } = buildMjcf(reloaded, resolveSpec(reloaded));
		const attribute = /\btolerance="([^"]+)"/.exec(xml);
		if (tolerance == null) expect(attribute).toBeNull();
		else expect(Number(attribute?.[1])).toBe(tolerance);
		const model = mj.MjModel.from_xml_string(xml);
		try {
			expect(model.opt.tolerance).toBe(tolerance ?? 1e-8);
		} finally {
			model.delete();
		}
	},
);

it.each([-1, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY])(
	"rejects invalid precision before compiling: %s",
	(tolerance) => {
		const cfg = scenarioFromDesign(design, { solver: { tolerance } });
		expect(() => buildMjcf(cfg, resolveSpec(cfg))).toThrow(/tolerance/);
	},
);
