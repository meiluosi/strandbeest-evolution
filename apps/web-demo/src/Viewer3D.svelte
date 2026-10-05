<script lang="ts">
import { type LinkageSpec, solvePose } from "strandbeest-core";
import type * as THREE_NS from "three";
import { t } from "./i18n/index.svelte";

type Outline = { exterior: number[][]; interiors: number[][][] };
type Bar = {
	key: string;
	label: string;
	a: string;
	b: string;
	length_mm: number;
	layer: number;
	part: string;
};
type Manifest = {
	parts: Record<string, { outline?: Outline; qty: number; kind: string }>;
	bars: Bar[];
	crank_pivot_mm: number[];
	layer_pitch_mm: number;
	leg_pitch_mm: number;
	crank_phase_deg: number[];
};

let {
	api,
	exportId,
	manifest,
	spec,
	unitMm,
	thickness,
}: {
	api: string;
	exportId: string;
	manifest: Manifest;
	spec: LinkageSpec;
	unitMm: number;
	thickness: number;
} = $props();

let host: HTMLDivElement;
let mode = $state<"assembly" | "part">("assembly");
let legsShown = $state<"one" | "all">("one");
let playing = $state(true);
let part = $state("frame_plate");
let status = $state("");

const stlParts = $derived(Object.keys(manifest.parts));
// let the render loop read current values without re-creating the scene
const live = { mode: "assembly", legs: "one", playing: true };
$effect(() => {
	live.mode = mode;
	live.legs = legsShown;
	live.playing = playing;
});

let api3: {
	loadPart: (name: string) => Promise<void>;
	rebuild: () => void;
} | null = null;

$effect(() => {
	manifest;
	spec;
	api3?.rebuild();
});
$effect(() => {
	part;
	if (mode === "part") api3?.loadPart(part);
});
$effect(() => {
	mode;
	if (mode === "part") api3?.loadPart(part);
});

$effect(() => {
	let disposed = false;
	let raf = 0;
	let cleanup = () => {};
	(async () => {
		status = t("viewer3d.loadingEngine");
		const THREE: typeof THREE_NS = await import("three");
		const { OrbitControls } = await import(
			"three/examples/jsm/controls/OrbitControls.js"
		);
		const { STLLoader } = await import(
			"three/examples/jsm/loaders/STLLoader.js"
		);
		if (disposed) return;
		status = "";

		const dark = matchMedia("(prefers-color-scheme: dark)").matches;
		const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
		renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
		host.appendChild(renderer.domElement);
		const scene = new THREE.Scene();
		const camera = new THREE.PerspectiveCamera(40, 1, 1, 5000);
		camera.position.set(260, 120, 420);
		const controls = new OrbitControls(camera, renderer.domElement);
		controls.enableDamping = true;
		scene.add(
			new THREE.HemisphereLight(0xffffff, dark ? 0x333344 : 0xbbbbcc, 1.1),
		);
		const sun = new THREE.DirectionalLight(0xffffff, 1.2);
		sun.position.set(200, 400, 300);
		scene.add(sun);

		const assembly = new THREE.Group();
		const partGroup = new THREE.Group();
		scene.add(assembly, partGroup);
		const palette = [
			0xd9622b, 0x2f6fd1, 0x3aa17e, 0xb7791f, 0x8e5bd0, 0x777777,
		];
		const geoCache = new Map<string, THREE_NS.BufferGeometry>();
		let bars: { mesh: THREE_NS.Mesh; bar: Bar; leg: number }[] = [];
		let feet: THREE_NS.Mesh[] = [];
		let ground: THREE_NS.GridHelper | null = null;

		function shapeOf(o: Outline): THREE_NS.Shape {
			const sh = new THREE.Shape(
				o.exterior.map(([x, y]) => new THREE.Vector2(x, y)),
			);
			for (const r of o.interiors)
				sh.holes.push(
					new THREE.Path(r.map(([x, y]) => new THREE.Vector2(x, y))),
				);
			return sh;
		}
		function geometryFor(name: string): THREE_NS.BufferGeometry | null {
			const o = manifest.parts[name]?.outline;
			if (!o) return null;
			if (!geoCache.has(name)) {
				geoCache.set(
					name,
					new THREE.ExtrudeGeometry(shapeOf(o), {
						depth: thickness,
						bevelEnabled: false,
						curveSegments: 12,
					}),
				);
			}
			return geoCache.get(name) as THREE_NS.BufferGeometry;
		}

		function rebuild() {
			geoCache.clear();
			assembly.clear();
			bars = [];
			feet = [];
			const n = manifest.crank_phase_deg.length;
			const legIdx = live.legs === "all" ? [...Array(n).keys()] : [0];
			const pitch = manifest.layer_pitch_mm;
			for (const leg of legIdx) {
				for (const bar of manifest.bars) {
					const g = geometryFor(bar.part);
					if (!g) continue;
					const mat = new THREE.MeshStandardMaterial({
						color: palette[bar.layer % palette.length],
						roughness: 0.55,
						metalness: 0.05,
					});
					const mesh = new THREE.Mesh(g, mat);
					assembly.add(mesh);
					bars.push({ mesh, bar, leg });
				}
				const foot = new THREE.Mesh(
					new THREE.SphereGeometry(3, 16, 12),
					new THREE.MeshStandardMaterial({ color: 0xd9622b }),
				);
				assembly.add(foot);
				feet.push(foot);
			}
			if (ground) scene.remove(ground);
			ground = new THREE.GridHelper(
				500,
				20,
				dark ? 0x555555 : 0xbbbbbb,
				dark ? 0x333333 : 0xdddddd,
			);
			scene.add(ground);
			void pitch;
		}

		function pose(t: number) {
			const n = manifest.crank_phase_deg.length;
			const pitch = manifest.layer_pitch_mm;
			const legPitch = manifest.leg_pitch_mm;
			const [px, py] = manifest.crank_pivot_mm as [number, number];
			let lowest = Number.POSITIVE_INFINITY;
			for (const { mesh, bar, leg } of bars) {
				const phase = ((manifest.crank_phase_deg[leg] ?? 0) * Math.PI) / 180;
				const p = solvePose(spec, -t + phase);
				if (!p) continue;
				const pt = (id: string) =>
					id === "P"
						? { x: px / unitMm, y: py / unitMm }
						: (p[id] as { x: number; y: number });
				const A = pt(bar.a);
				const B = pt(bar.b);
				const ax = A.x * unitMm;
				const ay = A.y * unitMm;
				const ang = Math.atan2((B.y - A.y) * unitMm, (B.x - A.x) * unitMm);
				mesh.position.set(ax, ay, leg * legPitch + bar.layer * pitch);
				mesh.rotation.set(0, 0, ang);
				if (bar.b === spec.foot) lowest = Math.min(lowest, B.y * unitMm);
			}
			for (let i = 0; i < feet.length; i++) {
				const leg = bars[0] ? i : 0;
				const phase = ((manifest.crank_phase_deg[leg] ?? 0) * Math.PI) / 180;
				const p = solvePose(spec, -t + phase);
				if (!p) continue;
				const f = p[spec.foot] as { x: number; y: number };
				feet[i]?.position.set(
					f.x * unitMm,
					f.y * unitMm,
					leg * legPitch + 2 * pitch,
				);
			}
			if (ground && Number.isFinite(lowest)) ground.position.y = lowest - 1;
			void n;
		}

		async function loadPart(name: string) {
			partGroup.clear();
			status = t("viewer3d.loadingParts");
			try {
				const r = await fetch(`${api}/exports/${exportId}/stl/${name}`);
				const geo = new STLLoader().parse(await r.arrayBuffer());
				geo.center();
				const mesh = new THREE.Mesh(
					geo,
					new THREE.MeshStandardMaterial({ color: 0xd9622b, roughness: 0.5 }),
				);
				partGroup.add(mesh);
				geo.computeBoundingSphere();
				const rad = geo.boundingSphere?.radius ?? 50;
				camera.position.set(rad * 1.7, rad * 1.5, rad * 3.8);
				controls.target.set(0, 0, 0);
				status = "";
			} catch (e) {
				status = t("viewer3d.partsFailed", {
					e: e instanceof Error ? e.message : String(e),
				});
			}
		}

		api3 = { loadPart, rebuild };
		rebuild();
		let clock = 0;
		let last = performance.now();
		function resize() {
			const w = host.clientWidth;
			const h = Math.max(320, Math.min(520, w * 0.66));
			renderer.setSize(w, h, false);
			renderer.domElement.style.width = `${w}px`;
			renderer.domElement.style.height = `${h}px`;
			camera.aspect = w / h;
			camera.updateProjectionMatrix();
		}
		const ro = new ResizeObserver(resize);
		ro.observe(host);
		resize();
		// frame the walker once
		controls.target.set(40, -30, 20);
		let lastLegs = live.legs;
		function frame(now: number) {
			raf = requestAnimationFrame(frame);
			if (live.legs !== lastLegs) {
				lastLegs = live.legs;
				rebuild();
			}
			if (live.playing) clock += ((now - last) / 1000) * 1.2;
			last = now;
			assembly.visible = live.mode === "assembly";
			partGroup.visible = live.mode === "part";
			if (ground) ground.visible = live.mode === "assembly";
			if (live.mode === "assembly") pose(clock);
			controls.update();
			renderer.render(scene, camera);
		}
		raf = requestAnimationFrame(frame);
		cleanup = () => {
			cancelAnimationFrame(raf);
			ro.disconnect();
			controls.dispose();
			renderer.dispose();
			renderer.domElement.remove();
			api3 = null;
		};
	})().catch((e) => {
		status = t("viewer3d.unavailable", {
			e: e instanceof Error ? e.message : String(e),
		});
	});
	return () => {
		disposed = true;
		cleanup();
	};
});
</script>

<div>
	<div class="row center">
		<button class="btn small" class:primary={mode === "assembly"} onclick={() => (mode = "assembly")}>{t("viewer3d.assembly")}</button>
		<button class="btn small" class:primary={mode === "part"} onclick={() => (mode = "part")}>{t("viewer3d.singlePart")}</button>
		{#if mode === "assembly"}
			<button class="btn small" onclick={() => (playing = !playing)}>{playing ? t("common.pause") : t("common.play")}</button>
			<button class="btn small" onclick={() => (legsShown = legsShown === "one" ? "all" : "one")}>{legsShown === "one" ? t("viewer3d.allLegs") : t("viewer3d.oneLeg")}</button>
			<small>{t("viewer3d.hint")}</small>
		{:else}
			<select bind:value={part}>
				{#each stlParts as p}<option value={p}>{p}</option>{/each}
			</select>
			<small>{t("viewer3d.stlNote")}</small>
		{/if}
		{#if status}<small><span class="spin"></span>{status}</small>{/if}
	</div>
	<div bind:this={host} class="host"></div>
</div>


<style>
	.host { width: 100%; border: 1px solid var(--line); border-radius: 10px; background: var(--bg); overflow: hidden; }
	.host :global(canvas) { display: block; }
</style>