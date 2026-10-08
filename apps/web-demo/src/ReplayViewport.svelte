<script lang="ts">
import type * as T from "three";
import {
	frameAt,
	hull,
	insidePolygon,
	type Overlays,
	type Replay,
	type Scene,
} from "./replay-types";

/** One 3D view of a recorded run at a given time, with the glass-box overlays: contact force arrows, slip, centre of mass and
 * support polygon. The controller owns the clock; this component only draws frame `frame` of `replay`. */
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
const live = {
	replay: null as Replay | null,
	time: 0,
	follow: true,
	overlays: { forces: true, slip: true, com: true } as Overlays,
};
$effect(() => {
	live.replay = replay;
	live.time = time;
	live.follow = follow;
	live.overlays = overlays;
});
let rebuild: (() => void) | null = null;
$effect(() => {
	replay;
	rebuild?.();
});

const SCALE_PER_N = 0.03; // metres of arrow per newton, capped
const MAX_ARROW = 0.25;
const SLIP_SPEED = 0.02;

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
		host.appendChild(renderer.domElement);
		const scn = new THREE.Scene();
		const camera = new THREE.PerspectiveCamera(38, 1, 0.005, 20);
		camera.position.set(0.15, 0.2, 0.62);
		const controls = new OrbitControls(camera, renderer.domElement);
		controls.enableDamping = true;
		scn.add(
			new THREE.HemisphereLight(0xffffff, dark ? 0x333344 : 0xbbbbcc, 1.2),
		);
		const sun = new THREE.DirectionalLight(0xffffff, 1.3);
		sun.position.set(1, 2, 1.5);
		scn.add(sun);

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
		let dyn: { update: (f: number) => void; torso: number } | null = null;

		function build() {
			world.clear();
			const R = live.replay;
			if (!R) {
				dyn = null;
				return;
			}
			const S: Scene = R.scene;
			world.rotation.z = (S.slope_deg * Math.PI) / 180;
			world.add(
				new THREE.GridHelper(
					6,
					120,
					dark ? 0x666666 : 0xaaaaaa,
					dark ? 0x3a3a3a : 0xdddddd,
				),
			);
			const groundMat = new THREE.MeshStandardMaterial({
				color: dark ? 0x2a2a2e : 0xeeeae0,
				roughness: 1,
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
				world.add(m);
			}
			const parts: {
				geom: Scene["geoms"][number];
				mesh: T.Mesh;
				contactIdx: number;
			}[] = [];
			let fi = 0;
			for (const g of S.geoms) {
				const color = new THREE.Color(
					g.rgba[0] ?? 0.5,
					g.rgba[1] ?? 0.5,
					g.rgba[2] ?? 0.5,
				);
				const mat = new THREE.MeshStandardMaterial({
					color,
					roughness: 0.55,
					transparent: g.type === "box",
					opacity: g.type === "box" ? 0.55 : 1,
				});
				let mesh: T.Mesh;
				if (g.type === "capsule")
					mesh = new THREE.Mesh(
						new THREE.CylinderGeometry(
							g.radius as number,
							g.radius as number,
							1,
							8,
						),
						mat,
					);
				else if (g.type === "sphere")
					mesh = new THREE.Mesh(
						new THREE.SphereGeometry(g.radius as number, 14, 10),
						mat,
					);
				else
					mesh = new THREE.Mesh(
						new THREE.BoxGeometry(
							2 * (g.size as number[])[0]!,
							2 * (g.size as number[])[1]!,
							2 * (g.size as number[])[2]!,
						),
						mat,
					);
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
				update(f: number) {
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
		function tick() {
			raf = requestAnimationFrame(tick);
			const R = live.replay;
			if (R && dyn) {
				const f = frameAt(R, live.time);
				dyn.update(f);
				if (live.follow && dyn.torso >= 0) {
					const tp = R.pos[f]?.[dyn.torso] as number[];
					const target = world.localToWorld(
						mapV(new THREE.Vector3(tp[0], tp[1], tp[2])),
					);
					camera.position.add(target.clone().sub(lastTarget));
					controls.target.copy(target);
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
	<div bind:this={host} class="host"></div>
</div>

<style>
	.vp { position: relative; min-width: 0; }
	.label { position: absolute; top: 8px; left: 10px; z-index: 2; font-weight: 700; font-size: 13px; background: var(--card); padding: 1px 8px; border-radius: 8px; border: 1px solid var(--line); }
	.host { width: 100%; border: 1px solid var(--line); border-radius: 10px; background: var(--bg); overflow: hidden; min-height: 280px; }
	.highlight .host { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent); }
	.host :global(canvas) { display: block; }
</style>
