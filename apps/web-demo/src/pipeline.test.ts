import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { describe, expect, it } from "vitest";
import { findKeyframes } from "./replay-types";

describe("Three.js high-performance rendering pipeline math", () => {
	it("composes instance matrix aligning unit cylinder ends exactly with 3D joint points", () => {
		const _vUp = new THREE.Vector3(0, 1, 0);
		const p1 = new THREE.Vector3(0.12, -0.05, 0.35);
		const p2 = new THREE.Vector3(-0.08, 0.22, 0.15);
		const radius = 0.005;

		const dir = new THREE.Vector3().subVectors(p2, p1);
		const len = dir.length();
		const mid = new THREE.Vector3().addVectors(p1, p2).multiplyScalar(0.5);
		const rot = new THREE.Quaternion().setFromUnitVectors(
			_vUp,
			dir.clone().normalize(),
		);
		const scale = new THREE.Vector3(radius, len, radius);
		const mat = new THREE.Matrix4().compose(mid, rot, scale);

		// Unit cylinder extends from (0, -0.5, 0) to (0, +0.5, 0)
		const cylinderBottom = new THREE.Vector3(0, -0.5, 0).applyMatrix4(mat);
		const cylinderTop = new THREE.Vector3(0, +0.5, 0).applyMatrix4(mat);

		expect(cylinderBottom.x).toBeCloseTo(p1.x, 5);
		expect(cylinderBottom.y).toBeCloseTo(p1.y, 5);
		expect(cylinderBottom.z).toBeCloseTo(p1.z, 5);

		expect(cylinderTop.x).toBeCloseTo(p2.x, 5);
		expect(cylinderTop.y).toBeCloseTo(p2.y, 5);
		expect(cylinderTop.z).toBeCloseTo(p2.z, 5);
	});

	it("merges static obstacle box geometries into a single BufferGeometry", () => {
		const obstacles: {
			pos: [number, number, number];
			size: [number, number, number];
		}[] = [
			{ pos: [0.5, 0, 0.05], size: [0.1, 0.4, 0.05] },
			{ pos: [1.2, 0, 0.08], size: [0.15, 0.4, 0.08] },
			{ pos: [2.0, 0, 0.04], size: [0.2, 0.4, 0.04] },
		];

		const geoms: THREE.BufferGeometry[] = obstacles.map((o) => {
			const sx = o.size[0];
			const sy = o.size[1];
			const sz = o.size[2];
			const px = o.pos[0];
			const pz = o.pos[2];
			const g = new THREE.BoxGeometry(2 * sx, 2 * sz, 2 * Math.min(sy, 0.6));
			g.translate(px, pz, 0);
			return g;
		});

		const merged = mergeGeometries(geoms, false);
		for (const g of geoms) g.dispose();

		expect(merged).not.toBeNull();
		if (!merged) return;

		// A single box has 24 vertices (72 position floats)
		// 3 boxes merged = 72 vertices (216 position floats)
		const posAttr = merged.getAttribute("position");
		expect(posAttr?.count).toBe(24 * 3);
		merged.dispose();
	});

	it("computes fractional sub-frame position lerp and orientation slerp", () => {
		const times = [0, 0.05, 0.1];
		const { k0, k1, alpha } = findKeyframes(times, 0.025);
		expect(k0).toBe(0);
		expect(k1).toBe(1);
		expect(alpha).toBeCloseTo(0.5, 6);

		const p0 = new THREE.Vector3(1.0, 2.0, 3.0);
		const p1 = new THREE.Vector3(2.0, 4.0, 5.0);
		const pInterp = new THREE.Vector3().lerpVectors(p0, p1, alpha);

		expect(pInterp.x).toBeCloseTo(1.5, 6);
		expect(pInterp.y).toBeCloseTo(3.0, 6);
		expect(pInterp.z).toBeCloseTo(4.0, 6);

		// Rotation about Z by 0 deg to 90 deg -> 45 deg at alpha = 0.5
		const q0 = new THREE.Quaternion().setFromAxisAngle(
			new THREE.Vector3(0, 0, 1),
			0,
		);
		const q1 = new THREE.Quaternion().setFromAxisAngle(
			new THREE.Vector3(0, 0, 1),
			Math.PI / 2,
		);
		const qInterp = new THREE.Quaternion().copy(q0).slerp(q1, alpha);

		const expectedQ = new THREE.Quaternion().setFromAxisAngle(
			new THREE.Vector3(0, 0, 1),
			Math.PI / 4,
		);
		expect(qInterp.x).toBeCloseTo(expectedQ.x, 6);
		expect(qInterp.y).toBeCloseTo(expectedQ.y, 6);
		expect(qInterp.z).toBeCloseTo(expectedQ.z, 6);
		expect(qInterp.w).toBeCloseTo(expectedQ.w, 6);
	});

	it("binary search partitions active footprint count for dynamic InstancedMesh", () => {
		const marks = [
			{ frame: 0, slip: false },
			{ frame: 5, slip: false },
			{ frame: 5, slip: true },
			{ frame: 10, slip: false },
			{ frame: 15, slip: false },
			{ frame: 20, slip: true },
		];

		const countAtFrame = (f: number) => {
			let low = 0;
			let high = marks.length;
			while (low < high) {
				const mid = (low + high) >> 1;
				if (marks[mid]!.frame <= f) {
					low = mid + 1;
				} else {
					high = mid;
				}
			}
			return low;
		};

		expect(countAtFrame(-1)).toBe(0);
		expect(countAtFrame(0)).toBe(1);
		expect(countAtFrame(4)).toBe(1);
		expect(countAtFrame(5)).toBe(3);
		expect(countAtFrame(12)).toBe(4);
		expect(countAtFrame(25)).toBe(6);
	});
});
