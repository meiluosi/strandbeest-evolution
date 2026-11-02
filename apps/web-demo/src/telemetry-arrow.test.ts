import * as arrow from "apache-arrow";
import { describe, expect, it, vi } from "vitest";
import {
	decodeArrowTelemetry,
	extractFlatVector,
	fetchArrowTelemetry,
} from "./telemetry-arrow";

describe("telemetry-arrow IPC stream", () => {
	function buildTestIpcStream(): Uint8Array {
		const nFrames = 4;
		const nBodies = 2;
		const nFeet = 2;

		const tData = new Float32Array([0.0, 0.1, 0.2, 0.3]);
		const posNested = Array.from({ length: nFrames }, (_, f) =>
			Array.from(
				{ length: nBodies * 3 },
				(_, i) => (f * nBodies * 3 + i) * 0.1,
			),
		);
		const quatNested = Array.from({ length: nFrames }, () =>
			Array.from({ length: nBodies * 4 }, (_, i) => (i === 0 ? 1.0 : 0.0)),
		);
		const contactNested = [
			[1, 0],
			[0, 1],
			[1, 1],
			[0, 0],
		];
		const psiData = new Float32Array([0.0, 0.5, 1.0, 1.5]);

		const tVector = arrow.vectorFromArray(tData);
		const posVector = arrow.vectorFromArray(
			posNested,
			new arrow.FixedSizeList(
				nBodies * 3,
				new arrow.Field("item", new arrow.Float32()),
			),
		);
		const quatVector = arrow.vectorFromArray(
			quatNested,
			new arrow.FixedSizeList(
				nBodies * 4,
				new arrow.Field("item", new arrow.Float32()),
			),
		);
		const contactVector = arrow.vectorFromArray(
			contactNested,
			new arrow.FixedSizeList(
				nFeet,
				new arrow.Field("item", new arrow.Uint8()),
			),
		);
		const psiVector = arrow.vectorFromArray(psiData);

		const metaPayload = {
			events: [{ t: 0.1, kind: "touchdown", leg: 0 }],
			diagnosis: [
				{
					code: "ok",
					severity: "info",
					message: "Smooth run",
					evidence: {},
				},
			],
			metrics: { stride_per_rev: 0.25 },
			stalled: false,
			nominal_stride_m: 0.26,
			kinematic_duty: 0.55,
			revolutions: 1.2,
			shapes: {
				t: [nFrames],
				pos: [nFrames, nBodies, 3],
				quat: [nFrames, nBodies, 4],
				contact: [nFrames, nFeet],
				psi: [nFrames],
			},
			info: {
				terrain: { kind: "flat", slope_deg: 0, params: {} },
				drive: "motor",
				wind: { kind: "constant", speed: 0, params: {} },
				environment: { gravity: 9.81, air_density: 1.2 },
				legs: 6,
				max_torque: 2.0,
			},
		};

		const fields = [
			new arrow.Field("t", tVector.type),
			new arrow.Field("pos", posVector.type),
			new arrow.Field("quat", quatVector.type),
			new arrow.Field("contact", contactVector.type),
			new arrow.Field("psi", psiVector.type),
		];

		const schema = new arrow.Schema(
			fields,
			new Map([["meta", JSON.stringify(metaPayload)]]),
		);

		const structData = (arrow.makeData as any)({
			type: new arrow.Struct(fields),
			length: nFrames,
			children: [
				tVector.data[0],
				posVector.data[0],
				quatVector.data[0],
				contactVector.data[0],
				psiVector.data[0],
			],
		});

		const batch = new arrow.RecordBatch(schema, structData);
		const table = new arrow.Table([batch]);

		return arrow.tableToIPC(table, "stream");
	}

	it("decodes real Arrow IPC stream directly into typed arrays", () => {
		const bytes = buildTestIpcStream();
		const decoded = decodeArrowTelemetry(bytes);

		expect(decoded.t).toBeInstanceOf(Float32Array);
		expect(decoded.t.length).toBe(4);
		expect(decoded.t[1]).toBeCloseTo(0.1);

		expect(decoded.pos).toBeInstanceOf(Float32Array);
		expect(decoded.pos?.length).toBe(4 * 2 * 3);

		expect(decoded.quat).toBeInstanceOf(Float32Array);
		expect(decoded.quat?.length).toBe(4 * 2 * 4);

		expect(decoded.contact).toBeInstanceOf(Uint8Array);
		expect(decoded.contact?.length).toBe(4 * 2);

		expect(decoded.psi).toBeInstanceOf(Float32Array);
		expect(decoded.psi?.length).toBe(4);

		expect(decoded.shapes.pos).toEqual([4, 2, 3]);
		expect(decoded.meta.metrics.stride_per_rev).toBe(0.25);
		expect(decoded.meta.events).toHaveLength(1);
	});

	it("converts decoded telemetry to standard Replay layout", () => {
		const bytes = buildTestIpcStream();
		const decoded = decodeArrowTelemetry(bytes);
		const replay = decoded.toReplay();

		expect(replay.t).toEqual([
			0.0, 0.10000000149011612, 0.20000000298023224, 0.30000001192092896,
		]);
		expect(replay.pos).toHaveLength(4);
		expect(replay.pos[0]).toHaveLength(2);
		expect(replay.pos[0]?.[0]?.[0]).toBe(0.0);
		expect(replay.pos[0]?.[1]?.[0]).toBeCloseTo(0.3);

		expect(replay.contact).toHaveLength(4);
		expect(replay.contact[0]?.[0]).toBe(1);
		expect(replay.contact[0]?.[1]).toBe(0);

		expect(replay.events).toHaveLength(1);
		expect(replay.events[0]?.kind).toBe("touchdown");
		expect(replay.stalled).toBe(false);
	});

	it("extractFlatVector returns null for absent vector", () => {
		expect(extractFlatVector(null)).toBeNull();
		expect(extractFlatVector(undefined)).toBeNull();
	});

	it("fetches telemetry.arrow via HTTP and parses result", async () => {
		const bytes = buildTestIpcStream();
		const fetchMock = vi.fn().mockResolvedValue({
			ok: true,
			status: 200,
			arrayBuffer: async () => bytes.buffer,
		});
		vi.stubGlobal("fetch", fetchMock);

		const decoded = await fetchArrowTelemetry(
			"01TEST0001",
			["poses", "feet"],
			"http://test-api:8000",
		);
		expect(fetchMock).toHaveBeenCalledWith(
			"http://test-api:8000/runs/01TEST0001/telemetry.arrow?max_frames=240&layers=poses%2Cfeet",
		);
		expect(decoded.t.length).toBe(4);
		expect(decoded.pos?.length).toBe(24);

		vi.unstubAllGlobals();
	});
});
