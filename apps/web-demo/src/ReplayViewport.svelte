<script lang="ts">
import type * as T from "three";
import { environmentForReplay } from "./environment-preset";
import { t } from "./i18n/index.svelte";
import {
	findKeyframes,
	hull,
	insidePolygon,
	type Overlays,
	type Replay,
	type Scene,
} from "./replay-types";
import type { SceneEnvironment } from "./scene-environment";
import { theme } from "./theme.svelte";

/** One 3D view of a recorded run at a given time, with the glass-box overlays: contact force arrows, slip, centre of mass,
 * support polygon, wind streamlines, footprint trails, and Theo Jansen PVC styling. */
let {
	replay,
	time,
	follow = true,
	overlays,
	environment = true,
	label = "",
	highlight = false,
}: {
	replay: Replay | null;
	time: number;
	follow?: boolean;
	overlays: Overlays;
	environment?: boolean;
	label?: string;
	highlight?: boolean;
} = $props();

let host: HTMLDivElement;
let camView = $state<"iso" | "side" | "top">("iso");
const live = {
	replay: null as Replay | null,
	time: 0,
	follow: true,
	environment: true,
	camView: "iso" as "iso" | "side" | "top",
	overlays: {
		forces: true,
		slip: true,
		com: true,
		wind: true,
		trails: true,
		pvc: true,
		pneumatics: true,
	} as Overlays,
};
let rebuild: (() => void) | null = null;
let refreshEnvironment: (() => void) | null = null;
let applyCameraPreset: ((v: "iso" | "side" | "top") => void) | null = null;
$effect(() => {
	live.replay = replay;
	live.time = time;
	live.follow = follow;
	live.environment = environment;
	live.camView = camView;
	live.overlays = overlays;
	refreshEnvironment?.();
});
$effect(() => {
	replay;
	overlays.pvc;
	overlays.pneumatics;
	rebuild?.();
});

function setCamera(v: "iso" | "side" | "top") {
	camView = v;
	applyCameraPreset?.(v);
}

const SCALE_PER_N = 0.03; // metres of arrow per newton, capped
const MAX_ARROW = 0.25;
const SLIP_SPEED = 0.02;
const PVC_COLOR = 0xe3b448; // Theo Jansen iconic yellow PVC conduit tone
const PVC_TORSO_COLOR = 0xc89632;

// Deterministic wind streamline seeds in local walker space
const STREAMLINES = Array.from({ length: 28 }, (_, i) => ({
	phase: ((i * 61) % 100) / 100,
	y: 0.02 + (((i * 37) % 100) / 100) * 0.26,
	z: -0.24 + (((i * 53) % 100) / 100) * 0.48,
	len: 0.06 + (i % 4) * 0.02,
	speedMul: 0.85 + (i % 5) * 0.1,
}));

$effect(() => {
	theme.mode;
	let disposed = false;
	let raf = 0;
	let cleanup = () => {};
	(async () => {
		const THREE = await import("three");
		const { OrbitControls } = await import(
			"three/examples/jsm/controls/OrbitControls.js"
		);
		const { mergeGeometries } = await import(
			"three/examples/jsm/utils/BufferGeometryUtils.js"
		);
		const { createSceneEnvironment } = await import("./scene-environment");
		if (disposed) return;
		const dark = document.documentElement.dataset.theme === "dark";
		const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
		renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
		renderer.shadowMap.enabled = true;
		renderer.shadowMap.type = THREE.PCFSoftShadowMap;
		host.appendChild(renderer.domElement);
		const scn = new THREE.Scene();
		const camera = new THREE.PerspectiveCamera(38, 1, 0.005, 20);
		camera.position.set(0.18, 0.16, 0.64);
		const controls = new OrbitControls(camera, renderer.domElement);
		controls.enableDamping = true;
		scn.add(
			new THREE.HemisphereLight(
				dark ? 0xdde4ff : 0xfff8e7,
				dark ? 0x2a2d3a : 0xcbb89d,
				1.15,
			),
		);
		const sun = new THREE.DirectionalLight(0xfffdf6, 1.45);
		sun.position.set(0.8, 1.8, 1.1);
		sun.castShadow = true;
		sun.shadow.mapSize.set(1024, 1024);
		sun.shadow.camera.near = 0.1;
		sun.shadow.camera.far = 5;
		const d = 0.9;
		sun.shadow.camera.left = -d;
		sun.shadow.camera.right = d;
		sun.shadow.camera.top = d;
		sun.shadow.camera.bottom = -d;
		sun.shadow.bias = -0.0005;
		scn.add(sun);
		scn.add(sun.target);

		// mujoco (x fwd, y lateral, z up) -> three (x, z, -y): a rotation about x by -90 degrees
		const qMap = new THREE.Quaternion().setFromAxisAngle(
			new THREE.Vector3(1, 0, 0),
			-Math.PI / 2,
		);
		const world = new THREE.Group();
		scn.add(world);
		let scenery: SceneEnvironment | null = null;
		let groundGrid: T.GridHelper | null = null;
		let appliedEnvironment = "";
		refreshEnvironment = () => {
			const preset = live.replay ? environmentForReplay(live.replay) : null;
			if (!preset) {
				scenery?.dispose();
				scenery = null;
				appliedEnvironment = "";
				return;
			}
			const state = `${preset.kind}:${live.environment}:${live.overlays.pvc ?? true}`;
			if (scenery && appliedEnvironment === state) return;
			if (scenery?.group.name !== `environment-${preset.kind}`) {
				scenery?.dispose();
				scenery = createSceneEnvironment(scn, preset, dark);
			}
			scenery?.setEnabled(live.environment, live.overlays.pvc ?? true);
			appliedEnvironment = state;
			if (groundGrid) groundGrid.visible = !live.environment;
		};

		// Pre-allocated scratch object pool for zero allocation in the animation loop
		const _vBody0 = new THREE.Vector3();
		const _vBody1 = new THREE.Vector3();
		const _qBody0 = new THREE.Quaternion();
		const _qBody1 = new THREE.Quaternion();

		const _vLocalA = new THREE.Vector3();
		const _vLocalB = new THREE.Vector3();
		const _vWorldA = new THREE.Vector3();
		const _vWorldB = new THREE.Vector3();
		const _vThreeA = new THREE.Vector3();
		const _vThreeB = new THREE.Vector3();
		const _vMid = new THREE.Vector3();
		const _vDir = new THREE.Vector3();
		const _vScale = new THREE.Vector3();
		const _vUp = new THREE.Vector3(0, 1, 0);

		const _vWorldPos = new THREE.Vector3();
		const _vThreePos = new THREE.Vector3();

		const _qIdentity = new THREE.Quaternion(0, 0, 0, 1);
		const _qRot = new THREE.Quaternion();
		const _qGeom = new THREE.Quaternion();
		const _qBox = new THREE.Quaternion();

		const _mat = new THREE.Matrix4();
		const _colFootActive = new THREE.Color();

		const _vTarget = new THREE.Vector3();
		const _vDelta = new THREE.Vector3();
		const _vForceDir = new THREE.Vector3();
		const _vFootPos = new THREE.Vector3();
		const _comInterp = new THREE.Vector3();

		const _colClear = new THREE.Color(0xa0e8f0);
		const _colPressurized = new THREE.Color(0xe64a19);
		const _colBottle = new THREE.Color();
		const _colFeelerDry = new THREE.Color(0x667788);
		const _colFeelerGlow = new THREE.Color(0xff2233);
		const _vScaleOne = new THREE.Vector3(1, 1, 1);
		const _vFeelerBase = new THREE.Vector3();
		const _vFeelerTip = new THREE.Vector3();
		const _qCylHorizontal = new THREE.Quaternion().setFromAxisAngle(
			new THREE.Vector3(0, 0, 1),
			Math.PI / 2,
		);
		const _qAnchorCone = new THREE.Quaternion().setFromAxisAngle(
			new THREE.Vector3(1, 0, 0),
			Math.PI,
		);

		let dyn: {
			update: (timeSec: number, nowSec: number) => void;
			getTorsoTarget: (out: T.Vector3) => void;
			torso: number;
		} | null = null;

		applyCameraPreset = (v: "iso" | "side" | "top") => {
			const tPos = controls.target;
			if (v === "side") {
				camera.position.set(tPos.x, tPos.y + 0.04, tPos.z + 0.68);
			} else if (v === "top") {
				camera.position.set(tPos.x, tPos.y + 0.72, tPos.z + 0.01);
			} else {
				camera.position.set(tPos.x + 0.18, tPos.y + 0.16, tPos.z + 0.64);
			}
			controls.update();
		};

		function build() {
			world.clear();
			groundGrid = null;
			refreshEnvironment?.();
			const R = live.replay;
			if (!R || !R.scene || !R.t || R.t.length === 0) {
				dyn = null;
				return;
			}
			const S: Scene = R.scene;
			const usePvc = live.overlays.pvc ?? true;
			world.rotation.z = (S.slope_deg * Math.PI) / 180;

			// Beach / planetary ground plane with shadow reception (1 draw call)
			const beachPlane = new THREE.Mesh(
				new THREE.PlaneGeometry(8, 4),
				scenery?.sand ??
					new THREE.MeshStandardMaterial({
						color: dark ? 0x1e2028 : usePvc ? 0xf3ead8 : 0xeeeae0,
						roughness: 0.92,
						metalness: 0.02,
					}),
			);
			beachPlane.rotation.x = -Math.PI / 2;
			beachPlane.position.y = -0.0005;
			beachPlane.receiveShadow = true;
			world.add(beachPlane);

			// Ground grid (1 draw call)
			groundGrid = new THREE.GridHelper(
				6,
				120,
				dark ? 0x555866 : 0xb8ad99,
				dark ? 0x2c2f3a : 0xe2d9c8,
			);
			groundGrid.position.y = 0.0001;
			groundGrid.visible = !live.environment;
			world.add(groundGrid);

			// Water plane (if water_level_m is set on terrain)
			const waterLevel =
				R.info?.terrain?.water_level_m ??
				(R.info?.terrain?.params as any)?.water_level_m ??
				(S as any)?.water_level_m;
			if (typeof waterLevel === "number") {
				const waterPlane = new THREE.Mesh(
					new THREE.PlaneGeometry(12, 6),
					new THREE.MeshStandardMaterial({
						color: 0x1976d2,
						roughness: 0.1,
						metalness: 0.1,
						transparent: true,
						opacity: 0.5,
						depthWrite: false,
					}),
				);
				waterPlane.rotation.x = -Math.PI / 2;
				waterPlane.position.y = waterLevel;
				world.add(waterPlane);
			}

			// Static obstacles: merge all obstacle box geometries into a single mesh (1 draw call)
			const groundMat = new THREE.MeshStandardMaterial({
				color: dark ? 0x2e323d : 0xdccbb1,
				roughness: 0.9,
			});
			if (S.obstacles && S.obstacles.length > 0) {
				const obsGeoms: T.BufferGeometry[] = [];
				for (const o of S.obstacles) {
					const bg = new THREE.BoxGeometry(
						2 * (o.size[0] as number),
						2 * (o.size[2] as number),
						2 * Math.min(o.size[1] as number, 0.6),
					);
					bg.translate(o.pos[0] as number, o.pos[2] as number, 0);
					obsGeoms.push(bg);
				}
				const merged = mergeGeometries(obsGeoms, false);
				for (const g of obsGeoms) g.dispose();
				if (merged) {
					const obsMesh = new THREE.Mesh(merged, groundMat);
					obsMesh.castShadow = true;
					obsMesh.receiveShadow = true;
					world.add(obsMesh);
				}
			}

			// Pre-allocate interpolated body pose array
			const numBodies = S.bodies.length;
			const bodyPositions = Array.from(
				{ length: numBodies },
				() => new THREE.Vector3(),
			);
			const bodyQuaternions = Array.from(
				{ length: numBodies },
				() => new THREE.Quaternion(),
			);

			// Categorize scene geoms: capsules (bars) vs spheres (feet) vs boxes (torso/sail)
			type GeomItem = {
				geom: Scene["geoms"][number];
				contactIdx: number;
				baseColor: T.Color;
			};
			const barItems: GeomItem[] = [];
			const sphereItems: GeomItem[] = [];
			const boxItems: {
				geom: Scene["geoms"][number];
				mesh: T.Mesh;
				contactIdx: number;
			}[] = [];

			let fi = 0;
			for (const g of S.geoms) {
				const isFoot = !!g.foot;
				const cIdx = isFoot ? fi++ : -1;
				const isSailBox = g.type === "box";
				const baseColor = usePvc
					? isSailBox
						? new THREE.Color(0xf7f2e4)
						: isFoot
							? new THREE.Color(0xd9622b)
							: new THREE.Color(g.body === 1 ? PVC_TORSO_COLOR : PVC_COLOR)
					: new THREE.Color(
							g.rgba[0] ?? 0.5,
							g.rgba[1] ?? 0.5,
							g.rgba[2] ?? 0.5,
						);

				if (g.type === "capsule") {
					barItems.push({ geom: g, contactIdx: cIdx, baseColor });
				} else if (g.type === "sphere") {
					sphereItems.push({ geom: g, contactIdx: cIdx, baseColor });
				} else {
					const mat = new THREE.MeshStandardMaterial({
						color: baseColor,
						roughness: usePvc ? 0.36 : 0.55,
						metalness: usePvc ? 0.08 : 0.02,
						transparent: isSailBox,
						opacity: isSailBox ? 0.72 : 1,
					});
					const mesh = new THREE.Mesh(
						new THREE.BoxGeometry(
							2 * (g.size as number[])[0]!,
							2 * (g.size as number[])[1]!,
							2 * (g.size as number[])[2]!,
						),
						mat,
					);
					const edges = new THREE.LineSegments(
						new THREE.EdgesGeometry(mesh.geometry),
						new THREE.LineBasicMaterial({
							color: usePvc ? PVC_TORSO_COLOR : 0xd9622b,
						}),
					);
					mesh.add(edges);
					mesh.castShadow = true;
					mesh.receiveShadow = !isSailBox;
					world.add(mesh);
					boxItems.push({ geom: g, mesh, contactIdx: cIdx });
				}
			}

			// 1. InstancedMesh for Linkage Bars (Capsules -> consolidated into 1 InstancedMesh)
			let barInstMesh: T.InstancedMesh | null = null;
			if (barItems.length > 0) {
				const unitCylinderGeo = new THREE.CylinderGeometry(1, 1, 1, 12);
				const barMat = new THREE.MeshStandardMaterial({
					roughness: usePvc ? 0.36 : 0.55,
					metalness: usePvc ? 0.08 : 0.02,
				});
				barInstMesh = new THREE.InstancedMesh(
					unitCylinderGeo,
					barMat,
					barItems.length,
				);
				barInstMesh.castShadow = true;
				barInstMesh.receiveShadow = true;
				for (let i = 0; i < barItems.length; i++) {
					barInstMesh.setColorAt(i, barItems[i]!.baseColor);
				}
				if (barInstMesh.instanceColor)
					barInstMesh.instanceColor.needsUpdate = true;
				world.add(barInstMesh);
			}

			// 2. InstancedMesh for Feet (Spheres -> consolidated into 1 InstancedMesh)
			let sphereInstMesh: T.InstancedMesh | null = null;
			if (sphereItems.length > 0) {
				const unitSphereGeo = new THREE.SphereGeometry(1, 16, 12);
				const sphereMat = new THREE.MeshStandardMaterial({
					roughness: usePvc ? 0.36 : 0.55,
					metalness: usePvc ? 0.08 : 0.02,
				});
				sphereInstMesh = new THREE.InstancedMesh(
					unitSphereGeo,
					sphereMat,
					sphereItems.length,
				);
				sphereInstMesh.castShadow = true;
				sphereInstMesh.receiveShadow = true;
				for (let i = 0; i < sphereItems.length; i++) {
					sphereInstMesh.setColorAt(i, sphereItems[i]!.baseColor);
				}
				if (sphereInstMesh.instanceColor)
					sphereInstMesh.instanceColor.needsUpdate = true;
				world.add(sphereInstMesh);
			}

			// Overlays: arrows, comMarker, comDrop, polyLine
			const nFeet = fi;
			const arrows = Array.from({ length: nFeet }, () => {
				const a = new THREE.ArrowHelper(
					new THREE.Vector3(0, 1, 0),
					new THREE.Vector3(),
					0.1,
					0x1b7f4c,
					0.02,
					0.012,
				);
				a.visible = false;
				world.add(a);
				return a;
			});

			const comMarker = new THREE.Mesh(
				new THREE.SphereGeometry(0.008, 12, 8),
				new THREE.MeshBasicMaterial({ color: 0x2255cc }),
			);

			// Pre-allocated Float32Array for comDrop line (2 vertices, 6 floats)
			const comDropPositions = new Float32Array(6);
			const comDropGeo = new THREE.BufferGeometry();
			comDropGeo.setAttribute(
				"position",
				new THREE.BufferAttribute(comDropPositions, 3),
			);
			const comDrop = new THREE.Line(
				comDropGeo,
				new THREE.LineBasicMaterial({ color: 0x2255cc }),
			);

			// Pre-allocated Float32Array for support polygon (up to 32 vertices, 96 floats)
			const polyPositions = new Float32Array(32 * 3);
			const polyGeo = new THREE.BufferGeometry();
			polyGeo.setAttribute(
				"position",
				new THREE.BufferAttribute(polyPositions, 3),
			);
			const polyLine = new THREE.LineLoop(
				polyGeo,
				new THREE.LineBasicMaterial({ color: 0x2e8b57 }),
			);
			for (const o of [comMarker, comDrop, polyLine]) {
				o.visible = false;
				world.add(o);
			}

			// Wind streamlines: consolidated into a SINGLE THREE.LineSegments (1 draw call)
			const numStreamlines = STREAMLINES.length;
			const windPositions = new Float32Array(numStreamlines * 2 * 3);
			const windGeo = new THREE.BufferGeometry();
			const windPosAttr = new THREE.BufferAttribute(windPositions, 3);
			windGeo.setAttribute("position", windPosAttr);
			const windMat = new THREE.LineBasicMaterial({
				color: dark ? 0x7cb3ff : 0x2f6fd1,
				transparent: true,
				opacity: 0.45,
			});
			const windSegments = new THREE.LineSegments(windGeo, windMat);
			world.add(windSegments);

			// Footprint ground contact marks: consolidated into a SINGLE THREE.InstancedMesh (1 draw call)
			type FootprintEntry = {
				frame: number;
				pos: [number, number, number];
				isSlip: boolean;
			};
			const footprintMarks: FootprintEntry[] = [];
			if (R.foot_pos && R.contact) {
				const step = Math.max(1, Math.floor(R.t.length / 90));
				for (let fIdx = 0; fIdx < R.t.length; fIdx += step) {
					const contacts = R.contact[fIdx] as number[] | undefined;
					const fps = R.foot_pos[fIdx];
					if (!contacts || !fps) continue;
					for (let k = 0; k < contacts.length; k++) {
						if (!contacts[k]) continue;
						const fp = fps[k];
						if (!fp) continue;
						const slip = (R.foot_slip?.[fIdx]?.[k] as number | undefined) ?? 0;
						footprintMarks.push({
							frame: fIdx,
							pos: [fp[0] as number, 0.0006, -(fp[1] as number)],
							isSlip: slip > SLIP_SPEED,
						});
					}
				}
			}

			let footprintInstancedMesh: T.InstancedMesh | null = null;
			if (footprintMarks.length > 0) {
				const footprintGeo = new THREE.CircleGeometry(0.0055, 10);
				footprintGeo.rotateX(-Math.PI / 2);
				const footprintMat = new THREE.MeshBasicMaterial({
					transparent: true,
					opacity: 0.45,
				});
				footprintInstancedMesh = new THREE.InstancedMesh(
					footprintGeo,
					footprintMat,
					footprintMarks.length,
				);
				footprintInstancedMesh.count = 0;
				const colStance = new THREE.Color(0x2e8b57);
				const colSlip = new THREE.Color(0xd62828);
				for (let i = 0; i < footprintMarks.length; i++) {
					const m = footprintMarks[i]!;
					_mat.makeTranslation(m.pos[0], m.pos[1], m.pos[2]);
					footprintInstancedMesh.setMatrixAt(i, _mat);
					footprintInstancedMesh.setColorAt(i, m.isSlip ? colSlip : colStance);
				}
				footprintInstancedMesh.instanceMatrix.needsUpdate = true;
				if (footprintInstancedMesh.instanceColor)
					footprintInstancedMesh.instanceColor.needsUpdate = true;
				world.add(footprintInstancedMesh);
			}

			const torso = S.bodies.indexOf("torso");

			// Pneumatic overlays: PET bottle bank, water feeler, sand anchor spike
			const pneumaticsData = R.pneumatics;
			const pneumaticsConfig =
				(R.info as any)?.pneumatics ?? (S as any)?.pneumatics;
			const hasPneumatics =
				(live.overlays.pneumatics ?? true) &&
				(!!pneumaticsData || !!pneumaticsConfig);

			let bottleInstMesh: T.InstancedMesh | null = null;
			let feelerArmMesh: T.Mesh | null = null;
			let feelerTipMesh: T.Mesh | null = null;
			let feelerTipMat: T.MeshStandardMaterial | null = null;
			let anchorMesh: T.Mesh | null = null;

			const BOTTLE_OFFSETS = [
				{ x: -0.07, y: -0.035, z: 0.08 },
				{ x: -0.07, y: 0.035, z: 0.08 },
				{ x: 0.07, y: -0.035, z: 0.08 },
				{ x: 0.07, y: 0.035, z: 0.08 },
			];

			if (hasPneumatics && torso >= 0) {
				// 1. PET Bottle bank (semi-transparent cylinders on walker chassis)
				const bottleGeo = new THREE.CylinderGeometry(0.016, 0.016, 0.12, 16);
				const bottleMat = new THREE.MeshStandardMaterial({
					roughness: 0.25,
					transparent: true,
					opacity: 0.75,
					metalness: 0.05,
				});
				bottleInstMesh = new THREE.InstancedMesh(
					bottleGeo,
					bottleMat,
					BOTTLE_OFFSETS.length,
				);
				bottleInstMesh.castShadow = true;
				for (let i = 0; i < BOTTLE_OFFSETS.length; i++) {
					bottleInstMesh.setColorAt(i, _colClear);
				}
				if (bottleInstMesh.instanceColor)
					bottleInstMesh.instanceColor.needsUpdate = true;
				world.add(bottleInstMesh);

				// 2. Water feeler (probe arm and tip indicator extending down from chassis front)
				const feelerArmGeo = new THREE.CylinderGeometry(0.003, 0.003, 1, 8);
				const feelerArmMat = new THREE.MeshStandardMaterial({
					color: 0x556677,
					roughness: 0.4,
					metalness: 0.3,
				});
				feelerArmMesh = new THREE.Mesh(feelerArmGeo, feelerArmMat);
				world.add(feelerArmMesh);

				const feelerTipGeo = new THREE.SphereGeometry(0.01, 16, 12);
				feelerTipMat = new THREE.MeshStandardMaterial({
					color: _colFeelerDry,
					emissive: 0x000000,
					roughness: 0.3,
					metalness: 0.1,
				});
				feelerTipMesh = new THREE.Mesh(feelerTipGeo, feelerTipMat);
				world.add(feelerTipMesh);

				// 3. Sand anchor spike (retracted into chassis or extended down into sand)
				const anchorGeo = new THREE.ConeGeometry(0.012, 0.14, 16);
				const anchorMat = new THREE.MeshStandardMaterial({
					color: 0x37474f,
					roughness: 0.35,
					metalness: 0.8,
				});
				anchorMesh = new THREE.Mesh(anchorGeo, anchorMat);
				anchorMesh.castShadow = true;
				world.add(anchorMesh);
			}

			const footColor = (R2: Replay, f: number, k: number) => {
				const down = (R2.contact[f] as number[] | undefined)?.[k];
				const slipping =
					live.overlays.slip &&
					down &&
					((R2.foot_slip?.[f]?.[k] as number | undefined) ?? 0) > SLIP_SPEED;
				return slipping ? 0xd62828 : down ? 0x2e8b57 : 0xd9622b;
			};

			dyn = {
				torso,
				getTorsoTarget(out: T.Vector3) {
					if (torso >= 0 && bodyPositions[torso]) {
						const tp = bodyPositions[torso]!;
						_vWorldPos.set(tp.x, tp.z, -tp.y);
						world.localToWorld(out.copy(_vWorldPos));
					}
				},
				update(timeSec: number, nowSec: number) {
					const { k0, k1, alpha } = findKeyframes(R.t, timeSec);
					const nearestFrame = alpha < 0.5 ? k0 : k1;

					// Fractional sub-frame body interpolation: position lerp and orientation slerp
					const P0 = R.pos[k0];
					const P1 = R.pos[k1];
					const Q0 = R.quat[k0];
					const Q1 = R.quat[k1];
					for (let b = 0; b < numBodies; b++) {
						const p0 = P0?.[b];
						const p1 = P1?.[b];
						const q0 = Q0?.[b];
						const q1 = Q1?.[b];
						if (p0 && p1 && q0 && q1) {
							_vBody0.set(p0[0] as number, p0[1] as number, p0[2] as number);
							_vBody1.set(p1[0] as number, p1[1] as number, p1[2] as number);
							bodyPositions[b]!.lerpVectors(_vBody0, _vBody1, alpha);

							_qBody0.set(
								q0[1] as number,
								q0[2] as number,
								q0[3] as number,
								q0[0] as number,
							);
							_qBody1.set(
								q1[1] as number,
								q1[2] as number,
								q1[3] as number,
								q1[0] as number,
							);
							bodyQuaternions[b]!.copy(_qBody0).slerp(_qBody1, alpha);
						}
					}

					// Update InstancedMesh for Linkage Bars
					if (barInstMesh) {
						let barColorUpdated = false;
						for (let i = 0; i < barItems.length; i++) {
							const { geom: g, contactIdx } = barItems[i]!;
							const pb = bodyPositions[g.body]!;
							const qb = bodyQuaternions[g.body]!;

							const ga = g.a as number[];
							const gb = g.b as number[];
							_vLocalA.set(ga[0] as number, ga[1] as number, ga[2] as number);
							_vLocalB.set(gb[0] as number, gb[1] as number, gb[2] as number);

							_vWorldA.copy(_vLocalA).applyQuaternion(qb).add(pb);
							_vThreeA.set(_vWorldA.x, _vWorldA.z, -_vWorldA.y);

							_vWorldB.copy(_vLocalB).applyQuaternion(qb).add(pb);
							_vThreeB.set(_vWorldB.x, _vWorldB.z, -_vWorldB.y);

							_vMid.addVectors(_vThreeA, _vThreeB).multiplyScalar(0.5);
							_vDir.subVectors(_vThreeB, _vThreeA);
							const len = _vDir.length();
							if (len > 1e-6) {
								_vDir.multiplyScalar(1 / len);
							} else {
								_vDir.set(0, 1, 0);
							}
							_qRot.setFromUnitVectors(_vUp, _vDir);
							const r = g.radius ?? 0.005;
							_vScale.set(r, len, r);
							_mat.compose(_vMid, _qRot, _vScale);
							barInstMesh.setMatrixAt(i, _mat);

							if (g.foot && contactIdx >= 0) {
								_colFootActive.set(footColor(R, nearestFrame, contactIdx));
								barInstMesh.setColorAt(i, _colFootActive);
								barColorUpdated = true;
							}
						}
						barInstMesh.instanceMatrix.needsUpdate = true;
						if (barColorUpdated && barInstMesh.instanceColor) {
							barInstMesh.instanceColor.needsUpdate = true;
						}
					}

					// Update InstancedMesh for Feet Spheres
					if (sphereInstMesh) {
						let sphereColorUpdated = false;
						for (let i = 0; i < sphereItems.length; i++) {
							const { geom: g, contactIdx } = sphereItems[i]!;
							const pb = bodyPositions[g.body]!;
							const qb = bodyQuaternions[g.body]!;
							const gp = g.pos as number[];
							_vLocalA.set(gp[0] as number, gp[1] as number, gp[2] as number);
							_vWorldA.copy(_vLocalA).applyQuaternion(qb).add(pb);
							_vThreePos.set(_vWorldA.x, _vWorldA.z, -_vWorldA.y);

							const r = g.radius ?? 0.002;
							_vScale.set(r, r, r);
							_mat.compose(_vThreePos, _qIdentity, _vScale);
							sphereInstMesh.setMatrixAt(i, _mat);

							if (g.foot && contactIdx >= 0) {
								_colFootActive.set(footColor(R, nearestFrame, contactIdx));
								sphereInstMesh.setColorAt(i, _colFootActive);
								sphereColorUpdated = true;
							}
						}
						sphereInstMesh.instanceMatrix.needsUpdate = true;
						if (sphereColorUpdated && sphereInstMesh.instanceColor) {
							sphereInstMesh.instanceColor.needsUpdate = true;
						}
					}

					// Update minimal box meshes (torso box, sails)
					for (const { geom: g, mesh } of boxItems) {
						const pb = bodyPositions[g.body]!;
						const qb = bodyQuaternions[g.body]!;
						const gp = g.pos as number[];
						_vLocalA.set(gp[0] as number, gp[1] as number, gp[2] as number);
						_vWorldA.copy(_vLocalA).applyQuaternion(qb).add(pb);
						mesh.position.set(_vWorldA.x, _vWorldA.z, -_vWorldA.y);

						const gq = g.quat as number[];
						_qGeom.set(
							gq[1] as number,
							gq[2] as number,
							gq[3] as number,
							gq[0] as number,
						);
						_qBox.copy(qb).multiply(_qGeom);
						mesh.quaternion.copy(qMap).multiply(_qBox);
					}

					// Overlays: foot force arrows
					const ov = live.overlays;
					const ff = R.foot_force?.[nearestFrame];
					const fp = R.foot_pos?.[nearestFrame];
					arrows.forEach((a, k) => {
						const force = ff?.[k];
						const pos = fp?.[k];
						const mag = force
							? Math.hypot(
									force[0] as number,
									force[1] as number,
									force[2] as number,
								)
							: 0;
						a.visible = ov.forces && !!force && !!pos && mag > 0.02;
						if (!a.visible || !force || !pos) return;

						_vForceDir
							.set(
								force[0] as number,
								force[2] as number,
								-(force[1] as number),
							)
							.normalize();
						const len = Math.min(MAX_ARROW, mag * SCALE_PER_N);
						_vFootPos.set(
							pos[0] as number,
							pos[2] as number,
							-(pos[1] as number),
						);
						a.position.copy(_vFootPos);
						a.setDirection(_vForceDir);
						a.setLength(
							len,
							Math.min(0.03, len * 0.4),
							Math.min(0.015, len * 0.25),
						);
					});

					// Overlays: Centre of mass & support polygon
					const com0 = R.com?.[k0];
					const com1 = R.com?.[k1];
					const show = ov.com && !!com0 && !!com1 && !!fp;
					comMarker.visible = comDrop.visible = polyLine.visible = show;
					if (show && com0 && com1 && fp) {
						const cx0 = com0[0] as number;
						const cy0 = com0[1] as number;
						const cz0 = com0[2] as number;
						const cx1 = com1[0] as number;
						const cy1 = com1[1] as number;
						const cz1 = com1[2] as number;

						const cx = cx0 * (1 - alpha) + cx1 * alpha;
						const cy = cy0 * (1 - alpha) + cy1 * alpha;
						const cz = cz0 * (1 - alpha) + cz1 * alpha;

						_comInterp.set(cx, cz, -cy);
						comMarker.position.copy(_comInterp);

						// Arrow contact rows are Uint8Array: its map would wrap -1 to 255.
						const down = Array.from(R.contact[nearestFrame] ?? [], (c, k) =>
							c ? k : -1,
						).filter((k) => k >= 0);
						const pts = hull(
							down.map(
								(k) =>
									[
										(fp[k] as number[])[0] as number,
										(fp[k] as number[])[1] as number,
									] as [number, number],
							),
						);
						const stable = pts.length >= 3 && insidePolygon([cx, cy], pts);
						const col = stable ? 0x2e8b57 : 0xd62828;
						(polyLine.material as T.LineBasicMaterial).color.set(col);
						(comMarker.material as T.MeshBasicMaterial).color.set(col);
						(comDrop.material as T.LineBasicMaterial).color.set(col);
						const ground = 0.0005;

						comDropPositions[0] = cx;
						comDropPositions[1] = cz;
						comDropPositions[2] = -cy;
						comDropPositions[3] = cx;
						comDropPositions[4] = ground;
						comDropPositions[5] = -cy;
						comDropGeo.attributes.position!.needsUpdate = true;

						for (let i = 0; i < pts.length; i++) {
							const pt = pts[i]!;
							polyPositions[i * 3] = pt[0]!;
							polyPositions[i * 3 + 1] = ground;
							polyPositions[i * 3 + 2] = -pt[1]!;
						}
						polyGeo.setDrawRange(0, pts.length);
						polyGeo.attributes.position!.needsUpdate = true;
					}

					// Overlays: Footprint trails via InstancedMesh dynamic count
					const showTrails = ov.trails ?? true;
					if (footprintInstancedMesh) {
						if (!showTrails || footprintMarks.length === 0) {
							footprintInstancedMesh.count = 0;
						} else {
							let low = 0;
							let high = footprintMarks.length;
							while (low < high) {
								const mid = (low + high) >> 1;
								if (footprintMarks[mid]!.frame <= nearestFrame) {
									low = mid + 1;
								} else {
									high = mid;
								}
							}
							footprintInstancedMesh.count = low;
						}
					}

					// Overlays: Wind streamlines via LineSegments position updates
					const torsoX = torso >= 0 ? (bodyPositions[torso]?.x ?? 0) : 0;
					const wSpeed =
						R.info?.drive === "sail" ? (R.info.wind?.speed ?? 3) : 0;
					const showWind = (ov.wind ?? true) && wSpeed > 0.05;
					windSegments.visible = showWind;
					if (showWind) {
						const spanX = 0.9;
						for (let i = 0; i < numStreamlines; i++) {
							const s = STREAMLINES[i]!;
							const travel =
								(s.phase + nowSec * (0.25 + wSpeed * 0.09) * s.speedMul) % 1;
							const x0 = torsoX - spanX * 0.5 + travel * spanX;
							const len = s.len * (0.7 + wSpeed * 0.12);
							const idx = i * 6;
							windPositions[idx] = x0;
							windPositions[idx + 1] = s.y;
							windPositions[idx + 2] = s.z;
							windPositions[idx + 3] = x0 + len;
							windPositions[idx + 4] = s.y;
							windPositions[idx + 5] = s.z;
						}
						windPosAttr.needsUpdate = true;
					}

					// Overlays: Pneumatics (PET bottle bank, water feeler, sand anchor spike)
					if (hasPneumatics && torso >= 0) {
						const pb = bodyPositions[torso]!;
						const qb = bodyQuaternions[torso]!;

						// 1. PET Bottle bank pressure color & position
						if (bottleInstMesh) {
							const pressPa =
								pneumaticsData?.bottle_pressure?.[nearestFrame] ??
								pneumaticsData?.bottle_pressure_pa?.[nearestFrame] ??
								pneumaticsConfig?.precharge_pa ??
								101325;
							const pNorm = Math.max(
								0,
								Math.min(1, (pressPa - 101325) / (600000 - 101325)),
							);
							_colBottle.lerpColors(_colClear, _colPressurized, pNorm);

							for (let i = 0; i < BOTTLE_OFFSETS.length; i++) {
								const bo = BOTTLE_OFFSETS[i]!;
								_vLocalA.set(bo.x, bo.y, bo.z);
								_vWorldA.copy(_vLocalA).applyQuaternion(qb).add(pb);
								_vThreePos.set(_vWorldA.x, _vWorldA.z, -_vWorldA.y);

								_qBox.copy(qb).multiply(_qCylHorizontal);
								_qRot.copy(qMap).multiply(_qBox);
								_mat.compose(_vThreePos, _qRot, _vScaleOne);
								bottleInstMesh.setMatrixAt(i, _mat);
								bottleInstMesh.setColorAt(i, _colBottle);
							}
							bottleInstMesh.instanceMatrix.needsUpdate = true;
							if (bottleInstMesh.instanceColor) {
								bottleInstMesh.instanceColor.needsUpdate = true;
							}
						}

						// 2. Water feeler arm & glowing tip indicator
						if (feelerTipMesh && feelerArmMesh && feelerTipMat) {
							_vLocalA.set(0.18, 0, 0.02);
							_vWorldA.copy(_vLocalA).applyQuaternion(qb).add(pb);
							_vFeelerBase.set(_vWorldA.x, _vWorldA.z, -_vWorldA.y);

							_vLocalB.set(0.28, 0, -0.12);
							_vWorldB.copy(_vLocalB).applyQuaternion(qb).add(pb);
							_vFeelerTip.set(_vWorldB.x, _vWorldB.z, -_vWorldB.y);

							feelerTipMesh.position.copy(_vFeelerTip);

							const vacPa =
								pneumaticsData?.feeler_vacuum?.[nearestFrame] ??
								pneumaticsData?.feeler_vacuum_pa?.[nearestFrame] ??
								0;
							const isSubmerged =
								(typeof waterLevel === "number" &&
									_vFeelerTip.y <= waterLevel) ||
								vacPa > 15000;

							if (isSubmerged) {
								feelerTipMat.color.copy(_colFeelerGlow);
								feelerTipMat.emissive.copy(_colFeelerGlow);
								feelerTipMat.emissiveIntensity = 1.2;
							} else {
								feelerTipMat.color.copy(_colFeelerDry);
								feelerTipMat.emissive.set(0x000000);
								feelerTipMat.emissiveIntensity = 0.0;
							}

							_vMid.addVectors(_vFeelerBase, _vFeelerTip).multiplyScalar(0.5);
							_vDir.subVectors(_vFeelerTip, _vFeelerBase);
							const armLen = _vDir.length();
							if (armLen > 1e-6) {
								_vDir.multiplyScalar(1 / armLen);
							} else {
								_vDir.set(0, 1, 0);
							}
							_qRot.setFromUnitVectors(_vUp, _vDir);
							_vScale.set(1, armLen, 1);
							_mat.compose(_vMid, _qRot, _vScale);
							feelerArmMesh.matrix.copy(_mat);
							feelerArmMesh.matrixAutoUpdate = false;
						}

						// 3. Sand anchor spike extension
						if (anchorMesh) {
							const isDeployed =
								Boolean(pneumaticsData?.anchor_deployed?.[nearestFrame]) ||
								false;
							_vLocalA.set(0, 0, isDeployed ? -0.12 : 0.03);
							_vWorldA.copy(_vLocalA).applyQuaternion(qb).add(pb);
							_vThreePos.set(_vWorldA.x, _vWorldA.z, -_vWorldA.y);

							_qBox.copy(qb).multiply(_qAnchorCone);
							_qRot.copy(qMap).multiply(_qBox);
							anchorMesh.position.copy(_vThreePos);
							anchorMesh.quaternion.copy(_qRot);
						}
					}
				},
			};
		}
		rebuild = build;
		build();

		function resize() {
			const w = host.clientWidth;
			const h = Math.max(280, Math.min(460, w * 0.6));
			renderer.setSize(w, h, false);
			renderer.domElement.style.width = `${w}px`;
			renderer.domElement.style.height = `${h}px`;
			camera.aspect = w / h;
			camera.updateProjectionMatrix();
		}
		const ro = new ResizeObserver(resize);
		ro.observe(host);
		resize();

		let hasTarget = false;
		const lastTarget = new THREE.Vector3();
		function tick(now: number) {
			raf = requestAnimationFrame(tick);
			const R = live.replay;
			if (R && dyn) {
				dyn.update(live.time, now / 1000);
				if (live.follow && dyn.torso >= 0) {
					dyn.getTorsoTarget(_vTarget);
					if (!hasTarget) {
						lastTarget.copy(_vTarget);
						hasTarget = true;
					}
					_vDelta.subVectors(_vTarget, lastTarget);
					camera.position.add(_vDelta);
					controls.target.copy(_vTarget);
					sun.position.set(
						_vTarget.x + 0.8,
						_vTarget.y + 1.8,
						_vTarget.z + 1.1,
					);
					sun.target.position.copy(_vTarget);
					lastTarget.copy(_vTarget);
				}
			}
			controls.update();
			scenery?.updateTarget(controls.target);
			renderer.render(scn, camera);
		}
		raf = requestAnimationFrame(tick);
		cleanup = () => {
			cancelAnimationFrame(raf);
			ro.disconnect();
			controls.dispose();
			scenery?.dispose();
			scenery = null;
			groundGrid = null;
			renderer.dispose();
			renderer.domElement.remove();
			rebuild = null;
			refreshEnvironment = null;
			applyCameraPreset = null;
		};
	})();
	return () => {
		disposed = true;
		cleanup();
	};
});
</script>

<div class="vp" class:highlight>
	{#if label}<div class="label">{label}</div>{/if}
	<div class="cam-hud">
		<button class="hud-btn" class:active={camView === "iso"} onclick={() => setCamera("iso")}>{t("viewport.cam.iso")}</button>
		<button class="hud-btn" class:active={camView === "side"} onclick={() => setCamera("side")}>{t("viewport.cam.side")}</button>
		<button class="hud-btn" class:active={camView === "top"} onclick={() => setCamera("top")}>{t("viewport.cam.top")}</button>
	</div>
	<div bind:this={host} class="host"></div>
</div>

<style>
	.vp { position: relative; min-width: 0; }
	.label { position: absolute; top: 8px; left: 10px; z-index: 2; font-weight: 700; font-size: 13px; background: color-mix(in srgb, var(--card) 85%, transparent); backdrop-filter: blur(4px); padding: 1px 8px; border-radius: 8px; border: 1px solid var(--line); }
	.cam-hud { position: absolute; top: 8px; right: 10px; z-index: 2; display: flex; gap: 3px; background: color-mix(in srgb, var(--card) 82%, transparent); backdrop-filter: blur(6px); border: 1px solid var(--line); border-radius: 7px; padding: 2px; }
	.hud-btn { font: inherit; font-size: 11.5px; padding: 2px 7px; border: none; border-radius: 5px; background: transparent; color: var(--muted); cursor: pointer; }
	.hud-btn:hover { color: var(--ink); }
	.hud-btn.active { background: var(--accent); color: #fff; font-weight: 600; }
	.host { width: 100%; border: 1px solid var(--line); border-radius: 10px; background: var(--bg); overflow: hidden; min-height: 280px; }
	.highlight .host { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent); }
	.host :global(canvas) { display: block; }
</style>
