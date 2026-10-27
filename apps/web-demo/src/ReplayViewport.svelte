<script lang="ts">
import type * as T from "three";
import { t } from "./i18n/index.svelte";
import {
	frameAt,
	hull,
	insidePolygon,
	type Overlays,
	type Replay,
	type Scene,
} from "./replay-types";

/** One 3D view of a recorded run at a given time, with the glass-box overlays: contact force arrows, slip, centre of mass,
 * support polygon, wind streamlines, footprint trails, and Theo Jansen PVC styling. */
let {
	replay,
	time,
	follow = true,
	overlays,
	label = "",
	highlight = false,
}: {
	replay: Replay | null;
	time: number;
	follow?: boolean;
	overlays: Overlays;
	label?: string;
	highlight?: boolean;
} = $props();

let host: HTMLDivElement;
let camView = $state<"iso" | "side" | "top">("iso");
const live = {
	replay: null as Replay | null,
	time: 0,
	follow: true,
	camView: "iso" as "iso" | "side" | "top",
	overlays: {
		forces: true,
		slip: true,
		com: true,
		wind: true,
		trails: true,
		pvc: true,
	} as Overlays,
};
$effect(() => {
	live.replay = replay;
	live.time = time;
	live.follow = follow;
	live.camView = camView;
	live.overlays = overlays;
});
let rebuild: (() => void) | null = null;
let applyCameraPreset: ((v: "iso" | "side" | "top") => void) | null = null;
$effect(() => {
	replay;
	overlays.pvc;
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
	let disposed = false;
	let raf = 0;
	let cleanup = () => {};
	(async () => {
		const THREE = await import("three");
		const { OrbitControls } = await import(
			"three/examples/jsm/controls/OrbitControls.js"
		);
		if (disposed) return;
		const dark = matchMedia("(prefers-color-scheme: dark)").matches;
		const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
		renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
		renderer.shadowMap.enabled = true;
		renderer.shadowMap.type = THREE.PCFSoftShadowMap;
		host.appendChild(renderer.domElement);
		const scn = new THREE.Scene();
		const camera = new THREE.PerspectiveCamera(38, 1, 0.005, 20);
		camera.position.set(0.18, 0.22, 0.64);
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
		const mapV = (v: T.Vector3) => new THREE.Vector3(v.x, v.z, -v.y);
		const mapA = (a: number[]) =>
			new THREE.Vector3(a[0] as number, a[2] as number, -(a[1] as number));
		const world = new THREE.Group();
		scn.add(world);
		let dyn: {
			update: (f: number, nowSec: number) => void;
			torso: number;
		} | null = null;

		applyCameraPreset = (v: "iso" | "side" | "top") => {
			const tPos = controls.target.clone();
			if (v === "side") {
				camera.position.set(tPos.x, tPos.y + 0.04, tPos.z + 0.68);
			} else if (v === "top") {
				camera.position.set(tPos.x, tPos.y + 0.72, tPos.z + 0.01);
			} else {
				camera.position.set(tPos.x + 0.18, tPos.y + 0.22, tPos.z + 0.62);
			}
			controls.update();
		};

		function build() {
			world.clear();
			const R = live.replay;
			if (!R) {
				dyn = null;
				return;
			}
			const S: Scene = R.scene;
			const usePvc = live.overlays.pvc ?? true;
			world.rotation.z = (S.slope_deg * Math.PI) / 180;

			// Beach / planetary ground plane with shadow reception
			const beachPlane = new THREE.Mesh(
				new THREE.PlaneGeometry(8, 4),
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

			const grid = new THREE.GridHelper(
				6,
				120,
				dark ? 0x555866 : 0xb8ad99,
				dark ? 0x2c2f3a : 0xe2d9c8,
			);
			grid.position.y = 0.0001;
			world.add(grid);

			const groundMat = new THREE.MeshStandardMaterial({
				color: dark ? 0x2e323d : 0xdccbb1,
				roughness: 0.9,
			});
			for (const o of S.obstacles) {
				const m = new THREE.Mesh(
					new THREE.BoxGeometry(
						2 * (o.size[0] as number),
						2 * (o.size[2] as number),
						2 * Math.min(o.size[1] as number, 0.6),
					),
					groundMat,
				);
				m.position.set(o.pos[0] as number, o.pos[2] as number, 0);
				m.castShadow = true;
				m.receiveShadow = true;
				world.add(m);
			}
			const parts: {
				geom: Scene["geoms"][number];
				mesh: T.Mesh;
				contactIdx: number;
			}[] = [];
			let fi = 0;
			for (const g of S.geoms) {
				const isSailBox = g.type === "box";
				const baseColor = usePvc
					? isSailBox
						? new THREE.Color(0xf7f2e4)
						: g.foot
							? new THREE.Color(0xd9622b)
							: new THREE.Color(g.body === 1 ? PVC_TORSO_COLOR : PVC_COLOR)
					: new THREE.Color(
							g.rgba[0] ?? 0.5,
							g.rgba[1] ?? 0.5,
							g.rgba[2] ?? 0.5,
						);
				const mat = new THREE.MeshStandardMaterial({
					color: baseColor,
					roughness: usePvc ? 0.36 : 0.55,
					metalness: usePvc ? 0.08 : 0.02,
					transparent: isSailBox,
					opacity: isSailBox ? 0.72 : 1,
				});
				let mesh: T.Mesh;
				if (g.type === "capsule")
					mesh = new THREE.Mesh(
						new THREE.CylinderGeometry(
							g.radius as number,
							g.radius as number,
							1,
							12,
						),
						mat,
					);
				else if (g.type === "sphere")
					mesh = new THREE.Mesh(
						new THREE.SphereGeometry(g.radius as number, 16, 12),
						mat,
					);
				else {
					mesh = new THREE.Mesh(
						new THREE.BoxGeometry(
							2 * (g.size as number[])[0]!,
							2 * (g.size as number[])[1]!,
							2 * (g.size as number[])[2]!,
						),
						mat,
					);
					// Add a subtle sail frame border to box geoms
					const edges = new THREE.LineSegments(
						new THREE.EdgesGeometry(mesh.geometry),
						new THREE.LineBasicMaterial({
							color: usePvc ? PVC_TORSO_COLOR : 0xd9622b,
						}),
					);
					mesh.add(edges);
				}
				mesh.castShadow = true;
				mesh.receiveShadow = !isSailBox;
				world.add(mesh);
				parts.push({ geom: g, mesh, contactIdx: g.foot ? fi++ : -1 });
			}

			// overlays: one arrow per foot, a centre-of-mass marker and the support polygon
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
			const comDrop = new THREE.Line(
				new THREE.BufferGeometry(),
				new THREE.LineBasicMaterial({ color: 0x2255cc }),
			);
			const polyLine = new THREE.LineLoop(
				new THREE.BufferGeometry(),
				new THREE.LineBasicMaterial({ color: 0x2e8b57 }),
			);
			for (const o of [comMarker, comDrop, polyLine]) {
				o.visible = false;
				world.add(o);
			}

			// 3D Wind Streamlines (animated ribbons flowing past the walker)
			const windGroup = new THREE.Group();
			const windLines = STREAMLINES.map(() => {
				const geom = new THREE.BufferGeometry().setFromPoints([
					new THREE.Vector3(),
					new THREE.Vector3(0.08, 0, 0),
				]);
				const line = new THREE.Line(
					geom,
					new THREE.LineBasicMaterial({
						color: dark ? 0x7cb3ff : 0x2f6fd1,
						transparent: true,
						opacity: 0.45,
					}),
				);
				windGroup.add(line);
				return line;
			});
			world.add(windGroup);

			// Footprint ground contact marks (sampled along the replay up to current frame)
			const trailGroup = new THREE.Group();
			const footprintGeo = new THREE.CircleGeometry(0.0055, 10);
			footprintGeo.rotateX(-Math.PI / 2);
			const matStanceMark = new THREE.MeshBasicMaterial({
				color: 0x2e8b57,
				transparent: true,
				opacity: 0.35,
			});
			const matSlipMark = new THREE.MeshBasicMaterial({
				color: 0xd62828,
				transparent: true,
				opacity: 0.55,
			});
			const footMarks: { frame: number; mesh: T.Mesh }[] = [];
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
						const mark = new THREE.Mesh(
							footprintGeo,
							slip > SLIP_SPEED ? matSlipMark : matStanceMark,
						);
						mark.position.set(fp[0] as number, 0.0006, -(fp[1] as number));
						mark.visible = false;
						trailGroup.add(mark);
						footMarks.push({ frame: fIdx, mesh: mark });
					}
				}
			}
			world.add(trailGroup);

			const torso = S.bodies.indexOf("torso");
			const tmp = new THREE.Vector3();
			const tmp2 = new THREE.Vector3();
			const footColor = (R2: Replay, f: number, k: number) => {
				const down = (R2.contact[f] as number[])[k];
				const slipping =
					live.overlays.slip &&
					down &&
					((R2.foot_slip?.[f]?.[k] as number | undefined) ?? 0) > SLIP_SPEED;
				return slipping ? 0xd62828 : down ? 0x2e8b57 : 0xd9622b;
			};
			dyn = {
				torso,
				update(f: number, nowSec: number) {
					const P = R.pos[f] as number[][];
					const Q = R.quat[f] as number[][];
					for (const { geom: g, mesh, contactIdx } of parts) {
						const p = P[g.body] as number[];
						const q = Q[g.body] as number[];
						const qb = new THREE.Quaternion(q[1], q[2], q[3], q[0]);
						const pb = new THREE.Vector3(p[0], p[1], p[2]);
						if (g.type === "capsule") {
							const am = mapV(
								tmp
									.fromArray(g.a as number[])
									.applyQuaternion(qb)
									.add(pb)
									.clone(),
							);
							const bm = mapV(
								tmp2
									.fromArray(g.b as number[])
									.applyQuaternion(qb)
									.add(pb)
									.clone(),
							);
							const dir = bm.clone().sub(am);
							const len = dir.length();
							mesh.position.copy(am.clone().add(bm).multiplyScalar(0.5));
							mesh.scale.set(1, len, 1);
							mesh.quaternion.setFromUnitVectors(
								new THREE.Vector3(0, 1, 0),
								dir.normalize(),
							);
						} else if (g.type === "sphere") {
							mesh.position.copy(
								mapV(
									tmp
										.fromArray(g.pos as number[])
										.applyQuaternion(qb)
										.add(pb)
										.clone(),
								),
							);
							if (g.foot)
								(mesh.material as T.MeshStandardMaterial).color.set(
									footColor(R, f, contactIdx),
								);
						} else {
							const gq = new THREE.Quaternion(
								(g.quat as number[])[1],
								(g.quat as number[])[2],
								(g.quat as number[])[3],
								(g.quat as number[])[0],
							);
							mesh.position.copy(
								mapV(
									tmp
										.fromArray(g.pos as number[])
										.applyQuaternion(qb)
										.add(pb)
										.clone(),
								),
							);
							mesh.quaternion.copy(
								qMap.clone().multiply(qb.clone().multiply(gq)),
							);
						}
					}
					const ov = live.overlays;
					const ff = R.foot_force?.[f];
					const fp = R.foot_pos?.[f];
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
						const dir = mapA(force).normalize();
						const len = Math.min(MAX_ARROW, mag * SCALE_PER_N);
						a.position.copy(mapA(pos).sub(dir.clone().multiplyScalar(0)));
						a.setDirection(dir);
						a.setLength(
							len,
							Math.min(0.03, len * 0.4),
							Math.min(0.015, len * 0.25),
						);
					});
					const com = R.com?.[f];
					const show = ov.com && !!com && !!fp;
					comMarker.visible = comDrop.visible = polyLine.visible = show;
					if (show && com && fp) {
						const down = (R.contact[f] as number[])
							.map((c, k) => (c ? k : -1))
							.filter((k) => k >= 0);
						const pts = hull(
							down.map(
								(k) =>
									[
										(fp[k] as number[])[0] as number,
										(fp[k] as number[])[1] as number,
									] as [number, number],
							),
						);
						const stable =
							pts.length >= 3 &&
							insidePolygon([com[0] as number, com[1] as number], pts);
						const col = stable ? 0x2e8b57 : 0xd62828;
						(polyLine.material as T.LineBasicMaterial).color.set(col);
						(comMarker.material as T.MeshBasicMaterial).color.set(col);
						(comDrop.material as T.LineBasicMaterial).color.set(col);
						const ground = 0.0005;
						polyLine.geometry.setFromPoints(
							pts.map(([x, y]) => new THREE.Vector3(x, ground, -y)),
						);
						comMarker.position.copy(mapA(com));
						comDrop.geometry.setFromPoints([
							mapA(com),
							new THREE.Vector3(com[0], ground, -(com[1] as number)),
						]);
					}

					// Footprint trails visibility
					const showTrails = ov.trails ?? true;
					trailGroup.visible = showTrails;
					if (showTrails) {
						for (const fm of footMarks) {
							fm.mesh.visible = fm.frame <= f;
						}
					}

					// Wind streamlines around the walker torso
					const torsoX =
						torso >= 0 ? ((P[torso]?.[0] as number | undefined) ?? 0) : 0;
					const wSpeed =
						R.info?.drive === "sail" ? (R.info.wind?.speed ?? 3) : 0;
					const showWind = (ov.wind ?? true) && wSpeed > 0.05;
					windGroup.visible = showWind;
					if (showWind) {
						const spanX = 0.9;
						windLines.forEach((line, i) => {
							const s = STREAMLINES[i]!;
							const travel =
								(s.phase + nowSec * (0.25 + wSpeed * 0.09) * s.speedMul) % 1;
							const x0 = torsoX - spanX * 0.5 + travel * spanX;
							const len = s.len * (0.7 + wSpeed * 0.12);
							const posAttr = line.geometry.getAttribute(
								"position",
							) as T.BufferAttribute;
							posAttr.setXYZ(0, x0, s.y, s.z);
							posAttr.setXYZ(1, x0 + len, s.y, s.z);
							posAttr.needsUpdate = true;
						});
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

		const lastTarget = new THREE.Vector3();
		function tick(now: number) {
			raf = requestAnimationFrame(tick);
			const R = live.replay;
			if (R && dyn) {
				const f = frameAt(R, live.time);
				dyn.update(f, now / 1000);
				if (live.follow && dyn.torso >= 0) {
					const tp = R.pos[f]?.[dyn.torso] as number[];
					const target = world.localToWorld(
						mapV(new THREE.Vector3(tp[0], tp[1], tp[2])),
					);
					camera.position.add(target.clone().sub(lastTarget));
					controls.target.copy(target);
					sun.position.set(target.x + 0.8, target.y + 1.8, target.z + 1.1);
					sun.target.position.copy(target);
					lastTarget.copy(target);
				}
			}
			controls.update();
			renderer.render(scn, camera);
		}
		raf = requestAnimationFrame(tick);
		cleanup = () => {
			cancelAnimationFrame(raf);
			ro.disconnect();
			controls.dispose();
			renderer.dispose();
			renderer.domElement.remove();
			rebuild = null;
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
