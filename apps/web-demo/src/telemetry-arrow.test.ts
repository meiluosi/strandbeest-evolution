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

	it("decodes pneumatic telemetry channels accurately into typed arrays and replay", () => {
		const nFrames = 4;
		const tData = new Float32Array([0.0, 0.1, 0.2, 0.3]);
		const bottleData = new Float32Array([
			101325.0, 200000.0, 400000.0, 600000.0,
		]);
		const vacuumData = new Float32Array([0.0, 5000.0, 15000.0, 25000.0]);
		const cylData = new Float32Array([101325.0, 120000.0, 200000.0, 101325.0]);
		const valveData = new Int8Array([1, 1, -1, 1]);
		const stepData = new Uint8Array([0, 1, 2, 3]);
		const anchorData = new Uint8Array([0, 0, 1, 1]);
		const anchorDepthData = new Float32Array([0.0, 0.0, 0.05, 0.12]);

		const tVector = arrow.vectorFromArray(tData);
		const bottleVector = arrow.vectorFromArray(bottleData);
		const cylVector = arrow.vectorFromArray(cylData);
		const vacuumVector = arrow.vectorFromArray(vacuumData);
		const valveVector = arrow.vectorFromArray(valveData);
		const stepVector = arrow.vectorFromArray(stepData);
		const anchorVector = arrow.vectorFromArray(anchorData);
		const anchorDepthVector = arrow.vectorFromArray(anchorDepthData);

		const fields = [
			new arrow.Field("t", tVector.type),
			new arrow.Field("bottle_pressure_pa", bottleVector.type),
			new arrow.Field("p_cyl", cylVector.type),
			new arrow.Field("feeler_vacuum_pa", vacuumVector.type),
			new arrow.Field("valve_state", valveVector.type),
			new arrow.Field("step_count", stepVector.type),
			new arrow.Field("anchor_deployed", anchorVector.type),
			new arrow.Field("anchor_depth", anchorDepthVector.type),
		];
		const schema = new arrow.Schema(
			fields,
			new Map([["meta", JSON.stringify({ shapes: {} })]]),
		);
		const structData = (arrow.makeData as any)({
			type: new arrow.Struct(fields),
			length: nFrames,
			children: [
				tVector.data[0],
				bottleVector.data[0],
				cylVector.data[0],
				vacuumVector.data[0],
				valveVector.data[0],
				stepVector.data[0],
				anchorVector.data[0],
				anchorDepthVector.data[0],
			],
		});
		const table = new arrow.Table([new arrow.RecordBatch(schema, structData)]);
		const bytes = arrow.tableToIPC(table, "stream");

		const decoded = decodeArrowTelemetry(bytes);
		expect(decoded.bottle_pressure_pa).toBeInstanceOf(Float32Array);
		expect(decoded.bottle_pressure).toBeInstanceOf(Float32Array);
		expect(decoded.bottle_pressure_pa?.[0]).toBeCloseTo(101325);
		expect(decoded.bottle_pressure_pa?.[3]).toBeCloseTo(600000);

		expect(decoded.p_cyl).toBeInstanceOf(Float32Array);
		expect(decoded.p_cyl?.[2]).toBeCloseTo(200000);

		expect(decoded.feeler_vacuum_pa).toBeInstanceOf(Float32Array);
		expect(decoded.feeler_vacuum).toBeInstanceOf(Float32Array);
		expect(decoded.feeler_vacuum_pa?.[2]).toBeCloseTo(15000);

		expect(decoded.valve_state).toBeInstanceOf(Int8Array);
		expect(decoded.valve_state?.[2]).toBe(-1);

		expect(decoded.step_count).toBeInstanceOf(Uint8Array);
		expect(decoded.step_count?.[3]).toBe(3);

		expect(decoded.anchor_deployed).toBeInstanceOf(Uint8Array);
		expect(decoded.anchor_deployed?.[2]).toBe(1);

		expect(decoded.anchor_depth).toBeInstanceOf(Float32Array);
		expect(decoded.anchor_depth?.[3]).toBeCloseTo(0.12);

		const replay = decoded.toReplay();
		expect(replay.pneumatics).toBeDefined();
		expect(replay.pneumatics?.bottle_pressure?.[3]).toBeCloseTo(600000);
		expect(replay.pneumatics?.p_bottle?.[3]).toBeCloseTo(600000);
		expect(replay.pneumatics?.p_cyl?.[2]).toBeCloseTo(200000);
		expect(replay.pneumatics?.feeler_vacuum?.[2]).toBeCloseTo(15000);
		expect(replay.pneumatics?.valve_state?.[2]).toBe(-1);
		expect(replay.pneumatics?.anchor_deployed?.[2]).toBe(1);
		expect(replay.pneumatics?.anchor_depth?.[3]).toBeCloseTo(0.12);
	});
});
