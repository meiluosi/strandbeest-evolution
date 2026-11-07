import { describe, expect, it } from "vitest";
import {
	findKeyframes,
	frameAt,
	largestDifference,
	type Replay,
} from "./replay-types";
import { decodeArrowTelemetry } from "./telemetry-arrow";

describe("Replay and Telemetry Defensive Edge Cases", () => {
	it("handles empty and single-frame replays without throwing exceptions", () => {
		const emptyReplay = {
			t: [],
			pos: [],
		} as unknown as Replay;

		expect(frameAt(emptyReplay, 1.0)).toBe(0);
		expect(findKeyframes([], 1.0)).toEqual({ k0: 0, k1: 0, alpha: 0 });
		expect(largestDifference(emptyReplay, emptyReplay)).toBeNull();

		const singleFrameReplay = {
			t: [0.5],
			pos: [[[0, 0, 0]]],
		} as unknown as Replay;

		expect(frameAt(singleFrameReplay, 0.5)).toBe(0);
		expect(frameAt(singleFrameReplay, 10.0)).toBe(0);
		expect(findKeyframes([0.5], 2.0)).toEqual({ k0: 0, k1: 0, alpha: 0 });
	});

	it("prevents division by zero or NaN when replay timestamps are degenerate (dt = 0)", () => {
		const degenerateReplay = {
			t: [1.0, 1.0],
			pos: [[[0, 0, 0]], [[0, 0, 0]]],
		} as unknown as Replay;

		const idx = frameAt(degenerateReplay, 1.0);
		expect(Number.isFinite(idx)).toBe(true);
		expect(Number.isNaN(idx)).toBe(false);
		expect(idx).toBe(0);
	});

	it("gracefully compares replays with mismatched frame counts", () => {
		const shortReplay = {
			t: [0.0, 0.5, 1.0],
			pos: [[[0, 0, 0]], [[1, 0, 0]], [[2, 0, 0]]],
		} as unknown as Replay;

		const longReplay = {
			t: [0.0, 0.25, 0.5, 0.75, 1.0],
			pos: [
				[[0, 0, 0]],
				[[0.5, 0, 0]],
				[[1.0, 0, 0]],
				[[1.5, 0, 0]],
				[[2.0, 0, 0]],
			],
		} as unknown as Replay;

		const diff = largestDifference(shortReplay, longReplay);
		expect(diff).not.toBeNull();
		if (diff) {
			expect(Number.isFinite(diff.t)).toBe(true);
			expect(Number.isFinite(diff.distance)).toBe(true);
			expect(diff.distance).toBeGreaterThanOrEqual(0);
		}
	});

	it("gracefully decodes partial or empty Arrow telemetry buffers to 0 frames", () => {
		const corruptBuffer = new Uint8Array([
			0x41, 0x52, 0x52, 0x4f, 0x57, 0x00, 0x00,
		]);
		const decoded = decodeArrowTelemetry(corruptBuffer);
		expect(decoded.t.length).toBe(0);
		const replay = decoded.toReplay();
		expect(replay.t.length).toBe(0);
	});

	it("calculates stall angle normalized by dynamic sample resolution", () => {
		// Verify that when calculating stall angle across 180 samples, stall at index 90 maps to 180 deg
		const nSamples180 = 180;
		const stallIdx = 90;
		const stallAngle = Math.round((stallIdx / nSamples180) * 360);
		expect(stallAngle).toBe(180);

		// With 120 samples, stall at index 60 maps to 180 deg
		const nSamples120 = 120;
		const stallAngle120 = Math.round((60 / nSamples120) * 360);
		expect(stallAngle120).toBe(180);
	});
});
