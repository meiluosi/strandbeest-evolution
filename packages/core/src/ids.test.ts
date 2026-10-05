/// <reference types="node" />
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
	decodeUlid,
	encodeUlid,
	isUlid,
	legacyUlid,
	newUlid,
	UlidGenerator,
	ulidTimeMs,
} from "./ids";
import { sha256 } from "./sha256";

const vectors = JSON.parse(
	readFileSync(
		join(import.meta.dirname, "../../../contracts/ids/ulid-vectors.json"),
		"utf8",
	),
);

describe("ULID contract vectors (shared with Python)", () => {
	it("encodes every row to the expected string and decodes it back", () => {
		for (const row of vectors.ulid) {
			const rand = BigInt(`0x${row.random_hex}`);
			expect(encodeUlid(row.time_ms, rand)).toBe(row.ulid);
			const [t, r] = decodeUlid(row.ulid);
			expect(t).toBe(row.time_ms);
			expect(r).toBe(rand);
		}
	});
	it("derives the same legacy ids as Python", () => {
		for (const row of vectors.legacy)
			expect(legacyUlid(row.kind, row.key)).toBe(row.ulid);
	});
});

describe("ULID reference examples", () => {
	it("agrees with published examples of the reference implementation", () => {
		expect(ulidTimeMs("01ARZ3NDEKTSV4RRFFQ69G5FAV")).toBe(1469922850259);
		expect(encodeUlid(1469918176385, 0n).startsWith("01ARYZ6S41")).toBe(true);
	});
});

describe("ULID generator", () => {
	it("makes valid ids that sort by creation order, even within one millisecond", () => {
		const ids = Array.from({ length: 2000 }, () => newUlid());
		expect(ids.every(isUlid)).toBe(true);
		expect([...ids].sort()).toEqual(ids);
		expect(new Set(ids).size).toBe(ids.length);
	});
	it("carries the clock time and never goes backwards when the clock does", () => {
		let now = 1_800_000_000_000;
		const g = new UlidGenerator({
			clock: () => now,
			random: () => new Uint8Array(10),
		});
		const a = g.new();
		now -= 5000;
		const b = g.new();
		expect(ulidTimeMs(a)).toBe(1_800_000_000_000);
		expect(b > a).toBe(true);
	});
	it("rejects malformed ids", () => {
		for (const bad of [
			"",
			"abc",
			"8ZZZZZZZZZZZZZZZZZZZZZZZZZ",
			"01ARZ3NDEKTSV4RRFFQ69G5FAI",
			"01arz3ndektsv4rrffq69g5fav",
		]) {
			expect(isUlid(bad)).toBe(false);
			expect(() => decodeUlid(bad)).toThrow();
		}
	});
});

describe("sha256", () => {
	it("matches node:crypto on assorted inputs, including block boundaries", () => {
		for (const len of [0, 1, 55, 56, 63, 64, 65, 119, 120, 1000]) {
			const data = Uint8Array.from(
				{ length: len },
				(_, i) => (i * 31 + 7) & 255,
			);
			expect(Buffer.from(sha256(data)).toString("hex")).toBe(
				createHash("sha256").update(data).digest("hex"),
			);
		}
	});
});

describe("design migration v1 -> v2 (contract shared with Python)", () => {
	const root = join(import.meta.dirname, "../../..");
	const read = (f: string) => JSON.parse(readFileSync(join(root, f), "utf8"));
	const v1 = read("contracts/migration/v1/design-jansen-small-6leg.json");
	// schemas/examples holds what Python's migration produced from that v1 file
	const expected = read("schemas/examples/design-jansen-small-6leg.json");
	it("gives exactly the document Python's migrate_doc gives", async () => {
		const { migrateDesign } = await import("./design");
		expect(migrateDesign(v1)).toEqual(expected);
	});
	it("leaves a v2 document alone and refuses unknown versions", async () => {
		const { migrateDesign } = await import("./design");
		expect(migrateDesign(expected)).toEqual(expected);
		expect(() => migrateDesign({ schema_version: 7, name: "x" })).toThrow();
	});
});
