import { describe, expect, it } from "vitest";
import { decodeShare, encodeShare } from "./static";

describe("share links", () => {
	it("round-trips a design, including non-ASCII names", async () => {
		const doc = {
			name: "\u6d4b\u8bd5 walker",
			linkage: { params: { a: 38 }, joints: [] },
		};
		expect(await decodeShare(await encodeShare(doc))).toEqual(doc);
	});

	it("is URL-safe and shorter than the plain JSON for a realistic design", async () => {
		const doc = {
			legs: Array.from({ length: 40 }, (_, i) => ({ id: i, len: 41.5 })),
		};
		const text = await encodeShare(doc);
		expect(text).toMatch(/^[A-Za-z0-9_-]+$/);
		expect(text.length).toBeLessThan(JSON.stringify(doc).length);
	});
});
