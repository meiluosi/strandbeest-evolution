/// <reference types="node" />
// TS runner of the kinematics contract corpus (contracts/kinematics/*.json); the Python runner reads the same files.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { type LinkageSpec, solvePose, trace } from "./linkage";
import { gaitMetrics } from "./metrics";

const dir = join(import.meta.dirname, "../../../contracts/kinematics");
const files = readdirSync(dir).filter((f) => f.endsWith(".json"));
type P = { x: number; y: number };

describe("kinematics contract corpus", () => {
	it("is not empty", () => expect(files.length).toBeGreaterThanOrEqual(4));

	for (const f of files) {
		it(`${f}: positions, link lengths and gait metrics`, () => {
			const doc = JSON.parse(readFileSync(join(dir, f), "utf8"));
			const spec = doc.spec as LinkageSpec;
			const val = (r: string | number) =>
				typeof r === "number" ? r : (spec.params[r] as number);
			for (const s of doc.samples) {
				const pose = solvePose(spec, s.theta) as Record<string, P> | null;
				expect(pose, `${f} @ ${s.theta}`).not.toBeNull();
				const at = pose as Record<string, P>;
				for (const [id, [x, y]] of Object.entries(s.points) as [
					string,
					[number, number],
				][]) {
					const p = at[id] as P;
					expect(Math.abs(p.x - x)).toBeLessThan(doc.tolerance.points);
					expect(Math.abs(p.y - y)).toBeLessThan(doc.tolerance.points);
				}
				for (const j of spec.joints) {
					j.centers.forEach((c, k) => {
						const a = at[j.id] as P;
						const b = at[c] as P;
						expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeCloseTo(
							val(j.radii[k] as string | number),
							8,
						);
					});
				}
			}
			const g = gaitMetrics(trace(spec, doc.gait.samples).foot);
			expect(Math.abs(g.width - doc.gait.width)).toBeLessThan(
				doc.tolerance.gait,
			);
			expect(Math.abs(g.lift - doc.gait.lift)).toBeLessThan(doc.tolerance.gait);
			expect(Math.abs(g.strokeLength - doc.gait.stroke_length)).toBeLessThan(
				doc.tolerance.gait,
			);
			expect(Math.abs(g.duty - doc.gait.duty)).toBeLessThan(doc.tolerance.gait);
		});
	}
});
