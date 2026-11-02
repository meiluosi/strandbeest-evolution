import { type Table, tableFromIPC, type Vector } from "apache-arrow";
import type { Diagnosis, Replay, RunEvent } from "./replay-types";

export interface DecodedTelemetry {
	table: Table;
	t: Float32Array | Float64Array;
	pos?: Float32Array;
	quat?: Float32Array;
	contact?: Uint8Array;
	foot_pos?: Float32Array;
	foot_force?: Float32Array;
	foot_slip?: Float32Array;
	com?: Float32Array;
	psi?: Float32Array;
	x?: Float32Array;
	torque?: Float32Array;
	shapes: Record<string, number[]>;
	meta: Record<string, any>;
	toReplay(): Replay;
}

/**
 * Extract the underlying typed array (e.g. Float32Array, Uint8Array) from an Arrow column Vector
 * directly without copying or creating intermediate JavaScript wrapper objects.
 */
export function extractFlatVector<T extends ArrayLike<number> = Float32Array>(
	vec: Vector | null | undefined,
): T | null {
	if (!vec || vec.length === 0) return null;
	if (vec.data && vec.data.length === 1 && vec.data[0]) {
		const d = vec.data[0];
		if (d.children && d.children.length > 0 && d.children[0]?.values) {
			const child = d.children[0];
			const val = child.values as T;
			const offset = child.offset ?? 0;
			const len = child.length ?? (val as any).length;
			if (offset === 0 && len === (val as any).length) return val;
			return (val as any).subarray(offset, offset + len) as T;
		}
		if (d.values) {
			const val = d.values as T;
			const offset = d.offset ?? 0;
			const len = d.length ?? (val as any).length;
			if (offset === 0 && len === (val as any).length) return val;
			return (val as any).subarray(offset, offset + len) as T;
		}
	}
	return vec.toArray() as unknown as T;
}

function make3DView(
	flat: Float32Array | undefined,
	shape: number[] | undefined,
): Float32Array[][] {
	if (!flat || !shape || shape.length < 3) return [];
	const frames = shape[0] ?? 0;
	const dim1 = shape[1] ?? 0;
	const dim2 = shape[2] ?? 0;
	if (frames <= 0 || dim1 <= 0 || dim2 <= 0) return [];
	const res: Float32Array[][] = new Array(frames);
	for (let f = 0; f < frames; f++) {
		const row = new Array(dim1);
		const fOffset = f * dim1 * dim2;
		for (let i = 0; i < dim1; i++) {
			const offset = fOffset + i * dim2;
			row[i] = flat.subarray(offset, offset + dim2);
		}
		res[f] = row;
	}
	return res;
}

function make2DView(
	flat: ArrayLike<number> | undefined,
	shape: number[] | undefined,
): ArrayLike<number>[] {
	if (!flat || !shape || shape.length < 2) return [];
	const frames = shape[0] ?? 0;
	const dim1 = shape[1] ?? 0;
	if (frames <= 0 || dim1 <= 0) return [];
	const res: ArrayLike<number>[] = new Array(frames);
	for (let f = 0; f < frames; f++) {
		const offset = f * dim1;
		if ("subarray" in flat && typeof flat.subarray === "function") {
			res[f] = (flat as any).subarray(offset, offset + dim1);
		} else {
			res[f] = (flat as any).slice(offset, offset + dim1);
		}
	}
	return res;
}

/**
 * Decode binary Arrow IPC stream buffer into typed arrays and replay document.
 */
export function decodeArrowTelemetry(
	buf: ArrayBuffer | Uint8Array,
): DecodedTelemetry {
	const table = tableFromIPC(buf);
	const metaStr = table.schema.metadata?.get("meta") ?? "{}";
	let meta: Record<string, any> = {};
	try {
		meta = JSON.parse(metaStr);
	} catch {
		meta = {};
	}

	const shapes: Record<string, number[]> = meta.shapes ?? {};

	const t =
		extractFlatVector<Float32Array | Float64Array>(table.getChild("t")) ??
		new Float32Array(0);
	const pos =
		extractFlatVector<Float32Array>(table.getChild("pos")) ?? undefined;
	const quat =
		extractFlatVector<Float32Array>(table.getChild("quat")) ?? undefined;
	const contact =
		extractFlatVector<Uint8Array>(table.getChild("contact")) ?? undefined;
	const foot_pos =
		extractFlatVector<Float32Array>(table.getChild("foot_pos")) ?? undefined;
	const foot_force =
		extractFlatVector<Float32Array>(table.getChild("foot_force")) ?? undefined;
	const foot_slip =
		extractFlatVector<Float32Array>(table.getChild("foot_slip")) ?? undefined;
	const com =
		extractFlatVector<Float32Array>(table.getChild("com")) ?? undefined;
	const psi =
		extractFlatVector<Float32Array>(table.getChild("psi")) ?? undefined;
	const x = extractFlatVector<Float32Array>(table.getChild("x")) ?? undefined;
	const torque =
		extractFlatVector<Float32Array>(table.getChild("torque")) ?? undefined;

	return {
		table,
		t,
		pos,
		quat,
		contact,
		foot_pos,
		foot_force,
		foot_slip,
		com,
		psi,
		x,
		torque,
		shapes,
		meta,
		toReplay(): Replay {
			return {
				scene: meta.scene ?? {
					bodies: [],
					geoms: [],
					obstacles: [],
					slope_deg: 0,
				},
				t: Array.from(t),
				pos: make3DView(pos, shapes.pos) as unknown as number[][][],
				quat: make3DView(quat, shapes.quat) as unknown as number[][][],
				contact: make2DView(contact, shapes.contact) as unknown as number[][],
				foot_pos: make3DView(
					foot_pos,
					shapes.foot_pos,
				) as unknown as number[][][],
				foot_force: make3DView(
					foot_force,
					shapes.foot_force,
				) as unknown as number[][][],
				foot_slip: make2DView(
					foot_slip,
					shapes.foot_slip,
				) as unknown as number[][],
				com: make2DView(com, shapes.com) as unknown as number[][],
				series: meta.series ?? {
					t: Array.from(t),
					psi: psi ? Array.from(psi) : [],
					x: x ? Array.from(x) : [],
					torque: torque ? Array.from(torque) : [],
				},
				energy: meta.energy ?? null,
				events: (meta.events ?? []) as RunEvent[],
				diagnosis: (meta.diagnosis ?? []) as Diagnosis[],
				metrics: (meta.metrics ?? {}) as Record<string, number | null>,
				stalled: Boolean(meta.stalled),
				nominal_stride_m: meta.nominal_stride_m ?? null,
				kinematic_duty: meta.kinematic_duty ?? null,
				revolutions: meta.revolutions ?? 0,
				info: meta.info ?? {
					terrain: { kind: "flat", slope_deg: 0, params: {} },
					drive: "motor",
					wind: { kind: "constant", speed: 0, params: {} },
					environment: { gravity: 9.81, air_density: 1.2 },
					legs: 6,
					max_torque: null,
				},
			};
		},
	};
}

/**
 * Fetch and decode binary Apache Arrow telemetry stream from backend API (ADR-0006, M6-01).
 */
export async function fetchArrowTelemetry(
	runId: string,
	layers?: string[],
	apiBase = "",
	maxFrames = 240,
): Promise<DecodedTelemetry> {
	const params = new URLSearchParams();
	if (maxFrames) params.set("max_frames", String(maxFrames));
	if (layers && layers.length > 0) params.set("layers", layers.join(","));
	const qs = params.toString();
	const base = apiBase.endsWith("/") ? apiBase.slice(0, -1) : apiBase;
	const url = `${base}/runs/${runId}/telemetry.arrow${qs ? `?${qs}` : ""}`;

	const res = await fetch(url);
	if (!res.ok) {
		throw new Error(`${res.status} ${await res.text()}`);
	}
	const buf = await res.arrayBuffer();
	return decodeArrowTelemetry(buf);
}
