import { sha256 } from "./sha256";

/**
 * Stable asset identity (ADR-0001): ULIDs are 128 bits as 26 Crockford base32 characters, a 48-bit millisecond
 * timestamp then 80 random bits, so ids sort by creation time. Python twin: strandbeest_common/ids.py; both are
 * checked against contracts/ids/ulid-vectors.json.
 */
export const ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
const ULID_RE = /^[0-7][0-9A-HJKMNP-TV-Z]{25}$/;
const TIME_MAX = (1n << 48n) - 1n;
const RAND_MAX = (1n << 80n) - 1n;

/** Build a ULID from a millisecond timestamp and 80 random bits. */
export function encodeUlid(
	timeMs: number | bigint,
	randomness: bigint,
): string {
	const t = BigInt(timeMs);
	if (t < 0n || t > TIME_MAX)
		throw new RangeError(`timestamp out of range: ${timeMs}`);
	if (randomness < 0n || randomness > RAND_MAX)
		throw new RangeError("randomness must fit in 80 bits");
	const n = (t << 80n) | randomness;
	let out = "";
	for (let shift = 125n; shift >= 0n; shift -= 5n)
		out += ULID_ALPHABET[Number((n >> shift) & 31n)];
	return out;
}

export function isUlid(s: unknown): s is string {
	return typeof s === "string" && ULID_RE.test(s);
}

/** [time in ms, 80-bit randomness] of a canonical (upper-case) ULID. */
export function decodeUlid(ulid: string): [number, bigint] {
	if (!isUlid(ulid)) throw new Error(`not a ULID: ${ulid}`);
	let n = 0n;
	for (const ch of ulid) n = (n << 5n) | BigInt(ULID_ALPHABET.indexOf(ch));
	return [Number(n >> 80n), n & RAND_MAX];
}

export function ulidTimeMs(ulid: string): number {
	return decodeUlid(ulid)[0];
}

export interface UlidSources {
	clock?: () => number;
	random?: (bytes: number) => Uint8Array;
}

/** Monotonic generator: ids made in the same millisecond still sort in creation order. */
export class UlidGenerator {
	private lastMs = -1;
	private lastRand = 0n;
	private readonly clock: () => number;
	private readonly random: (bytes: number) => Uint8Array;

	constructor(src: UlidSources = {}) {
		this.clock = src.clock ?? (() => Date.now());
		this.random =
			src.random ??
			((n) => globalThis.crypto.getRandomValues(new Uint8Array(n)));
	}

	new(): string {
		const ms = Math.max(this.clock(), this.lastMs);
		let rand: bigint;
		if (ms === this.lastMs) {
			rand = this.lastRand + 1n;
			if (rand > RAND_MAX)
				throw new RangeError("more than 2^80 ids in one millisecond");
		} else {
			rand = 0n;
			for (const b of this.random(10)) rand = (rand << 8n) | BigInt(b);
		}
		this.lastMs = ms;
		this.lastRand = rand;
		return encodeUlid(ms, rand);
	}
}

const defaultGenerator = new UlidGenerator();

/** A fresh, time-sortable asset id. */
export function newUlid(): string {
	return defaultGenerator.new();
}

/**
 * Deterministic id for a document written before ids existed (schema v1), which other documents refer to by name.
 * It depends only on the kind and the old name: time part 0, random part = first 80 bits of SHA-256("kind:name").
 * Same result on every machine, so a reference resolves to the id of what it names without a lookup table.
 */
export function legacyUlid(kind: string, key: string): string {
	const digest = sha256(new TextEncoder().encode(`${kind}:${key}`));
	let rand = 0n;
	for (let i = 0; i < 10; i++)
		rand = (rand << 8n) | BigInt(digest[i] as number);
	return encodeUlid(0, rand);
}
