<script lang="ts">
import type * as T from "three";
import { call, runJob } from "./api";
import { currentDesign, store } from "./store.svelte";

type Scene = {
	bodies: string[];
	geoms: {
		body: number;
		type: "capsule" | "sphere" | "box";
		rgba: number[];
		foot: boolean;
		a?: number[];
		b?: number[];
		radius?: number;
		pos?: number[];
		quat?: number[];
		size?: number[];
	}[];
	obstacles: { pos: number[]; size: number[] }[];
	slope_deg: number;
};
type Replay = {
	scene: Scene;
	t: number[];
	pos: number[][][];
	quat: number[][][];
	contact: number[][];
	series: { t: number[]; psi: number[]; x: number[]; torque: number[] };
	metrics: Record<string, number | null>;
	stalled: boolean;
	nominal_stride_m: number | null;
	revolutions: number;
	info: {
		terrain: {
			kind: string;
			slope_deg: number;
			params: Record<string, number>;
		};
		drive: string;
		wind: { kind: string; speed: number; params: Record<string, number> };
		environment: { gravity: number; air_density: number };
	};
};

// Planet numbers are approximate (NASA fact sheets, Wikipedia); Moon has no atmosphere, so no sail drive there.
const SCENES: Record<
	string,
	{ label: string; hint: string; sail?: boolean; ov: Record<string, any> }
> = {
	flat: {
		label: "平地（电机）",
		hint: "电机以固定转速带动曲柄，最简单的基准",
		ov: {},
	},
	slope: {
		label: "上坡 5°",
		hint: "斜坡用倾斜重力模拟，+x 是上坡方向",
		ov: { terrain: { kind: "slope", slope_deg: 5 } },
	},
	step: {
		label: "台阶 12 mm",
		hint: "一块凸起的平台；电机有扭矩上限，过不去就会卡住",
		ov: {
			terrain: { kind: "step", params: { distance: 0.15, height: 0.012 } },
			run: { revolutions: 2.5 },
		},
	},
	bumps: {
		label: "凹凸地面",
		hint: "随机凸块，最高 10 mm",
		ov: {
			terrain: {
				kind: "bumps",
				params: { count: 8, max_height: 0.01, start: 0.15, seed: 3 },
			},
			run: { revolutions: 2.5 },
		},
	},
	wind: {
		label: "风力（帆）",
		hint: "没有电机：帆在风里转曲柄，风太小就起不来",
		sail: true,
		ov: {},
	},
	gusts: {
		label: "阵风",
		hint: "平均风速加正弦阵风",
		sail: true,
		ov: { wind: { kind: "gusts", params: { amplitude: 1.5, period: 5 } } },
	},
	mars: {
		label: "火星（帆）",
		hint: "g≈3.7 m/s²，空气密度≈0.02 kg/m³：帆几乎没力气",
		sail: true,
		ov: { environment: { gravity: 3.73, air_density: 0.02 } },
	},
	titan: {
		label: "泰坦（帆）",
		hint: "g≈1.35 m/s²，空气密度≈5.4 kg/m³：低重力、浓空气",
		sail: true,
		ov: { environment: { gravity: 1.35, air_density: 5.4 } },
	},
	venus: {
		label: "金星（帆）",
		hint: "g≈8.9 m/s²，空气密度≈65 kg/m³：微风就能推动",
		sail: true,
		ov: { environment: { gravity: 8.87, air_density: 65 } },
	},
	moon: {
		label: "月球（电机）",
		hint: "g≈1.6 m/s²，没有空气，只能用电机",
		ov: { environment: { gravity: 1.62, air_density: 0 } },
	},
};

let key = $state("flat");
let wind = $state(3);
let busy = $state("");
let error = $state("");
let replay = $state<Replay | null>(null);
let frame = $state(0);
let playing = $state(true);
let speed = $state(1);
let follow = $state(true);
let host: HTMLDivElement;
const live = {
	frame: 0,
	playing: true,
	speed: 1,
	follow: true,
	replay: null as Replay | null,
};
$effect(() => {
	live.frame = frame;
	live.playing = playing;
	live.speed = speed;
	live.follow = follow;
	live.replay = replay;
});
let rebuild: (() => void) | null = null;
$effect(() => {
	replay;
	rebuild?.();
});

const scene = $derived(SCENES[key] as (typeof SCENES)[string]);

async function run() {
	busy = "仿真中";
	error = "";
	replay = null;
	try {
		const sc = scene;
		const ov: Record<string, any> = JSON.parse(JSON.stringify(sc.ov));
		ov.run = { settle: 0.5, revolutions: 2, frame_rate: 30, ...(ov.run ?? {}) };
		if (sc.sail) {
			ov.drive = { kind: "sail", ...(ov.drive ?? {}) };
			ov.wind = { ...(ov.wind ?? {}), speed: wind };
			ov.run = { ...ov.run, give_up_after: 6, max_time: 30 };
		}
		const doc = await runJob("/runs", {
			design: currentDesign(),
			ensemble: false,
			overrides: ov,
		});
		replay = await call(`/runs/${doc.id}/replay`);
		frame = 0;
		playing = true;
	} catch (e) {
		error = e instanceof Error ? e.message : String(e);
	} finally {
		busy = "";
	}
}

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
		const world = new THREE.Group();
		scn.add(world);
		let dyn: { update: (f: number) => void; torso: number } | null = null;
		let grid: T.GridHelper | null = null;

		function build() {
			world.clear();
			const R = live.replay;
			if (!R) {
				dyn = null;
				return;
			}
			const S = R.scene;
			world.rotation.z = (S.slope_deg * Math.PI) / 180;
			grid = new THREE.GridHelper(
				6,
				120,
				dark ? 0x666666 : 0xaaaaaa,
				dark ? 0x3a3a3a : 0xdddddd,
			);
			world.add(grid);
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
			const torso = S.bodies.indexOf("torso");
			const tmp = new THREE.Vector3();
			const tmp2 = new THREE.Vector3();
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
							const a = tmp
								.fromArray(g.a as number[])
								.applyQuaternion(qb)
								.add(pb)
								.clone();
							const b = tmp2
								.fromArray(g.b as number[])
								.applyQuaternion(qb)
								.add(pb)
								.clone();
							const am = mapV(a);
							const bm = mapV(b);
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
									(R.contact[f] as number[])[contactIdx] ? 0x2e8b57 : 0xd9622b,
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
				},
			};
		}
		rebuild = build;
		build();

		function resize() {
			const w = host.clientWidth;
			const h = Math.max(300, Math.min(500, w * 0.55));
			renderer.setSize(w, h, false);
			renderer.domElement.style.width = `${w}px`;
			renderer.domElement.style.height = `${h}px`;
			camera.aspect = w / h;
			camera.updateProjectionMatrix();
		}
		const ro = new ResizeObserver(resize);
		ro.observe(host);
		resize();

		let last = performance.now();
		let acc = 0;
		const lastTarget = new THREE.Vector3();
		function tick(now: number) {
			raf = requestAnimationFrame(tick);
			const R = live.replay;
			if (R && dyn) {
				const n = R.t.length;
				if (live.playing && n > 1) {
					const dtFrame =
						((R.t[n - 1] as number) - (R.t[0] as number)) / (n - 1);
					acc += ((now - last) / 1000) * live.speed;
					while (acc >= dtFrame) {
						acc -= dtFrame;
						frame = (frame + 1) % n;
					}
				}
				const f = Math.min(live.frame, n - 1);
				dyn.update(f);
				if (live.follow && dyn.torso >= 0) {
					const tp = R.pos[f]?.[dyn.torso] as number[];
					const target = world.localToWorld(
						mapV(new THREE.Vector3(tp[0], tp[1], tp[2])),
					);
					const delta = target.clone().sub(lastTarget);
					camera.position.add(delta);
					controls.target.copy(target);
					lastTarget.copy(target);
				}
			}
			last = now;
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

// ---- synced charts ----
function line(
	xs: number[],
	ys: number[],
	lo: number,
	hi: number,
	tmax: number,
): string {
	return ys
		.map(
			(y, i) =>
				`${((xs[i] as number) / tmax) * 300},${46 - ((y - lo) / (hi - lo || 1)) * 40}`,
		)
		.join(" ");
}
const charts = $derived.by(() => {
	if (!replay) return null;
	const s = replay.series;
	const tmax = Math.max(...s.t);
	const mk = (ys: number[]) => ({
		lo: Math.min(...ys),
		hi: Math.max(...ys),
		pts: line(s.t, ys, Math.min(...ys), Math.max(...ys), tmax),
	});
	return { tmax, torque: mk(s.torque), x: mk(s.x) };
});
const cursor = $derived.by(() => {
	if (!replay || !charts) return 0;
	const t0 = replay.t[0] as number;
	return (
		(((replay.t[Math.min(frame, replay.t.length - 1)] as number) - t0) /
			charts.tmax) *
		300
	);
});
const outcome = $derived.by(() => {
	if (!replay) return null;
	const dist =
		(replay.series.x.at(-1) as number) - (replay.series.x[0] as number);
	const dur = replay.series.t.at(-1) as number;
	// distance the body would cover if no foot slipped or was blocked: stance travel / duty factor, per revolution
	const ideal = replay.nominal_stride_m
		? replay.nominal_stride_m * replay.revolutions
		: null;
	return {
		dist,
		dur,
		speed: dist / dur,
		efficiency: ideal ? dist / ideal : null,
	};
});
</script>

<div class="card">
	<h2>场景演示：看它怎么动</h2>
	<p class="muted">选一个场景，运行一次完整的 MuJoCo 仿真，然后在 3D 里回放。脚着地时变绿，悬空时是橙色。</p>
	<div class="chips">
		{#each Object.entries(SCENES) as [k, s]}
			<button class="btn small" class:primary={key === k} onclick={() => (key = k)} title={s.hint}>{s.label}</button>
		{/each}
	</div>
	<p class="muted">{scene.hint}</p>
	<div class="row center">
		{#if scene.sail}<label>平均风速 (m/s) <input type="number" min="0" max="20" step="0.5" bind:value={wind} /></label>{/if}
		<button class="btn primary" disabled={!!busy} onclick={run}>运行并回放</button>
		{#if busy}<span class="muted"><span class="spin"></span>{busy}…</span>{/if}
		<small>当前设计：{store.name}</small>
	</div>
	{#if error}<p class="notice error">出错：{error}</p>{/if}

	<div bind:this={host} class="host"></div>
	{#if !replay && !busy}<p class="muted">还没有回放：点“运行并回放”。</p>{/if}

	{#if replay && outcome && charts}
		<div class="row center">
			<button class="btn small" onclick={() => (playing = !playing)}>{playing ? "暂停" : "播放"}</button>
			<input type="range" min="0" max={replay.t.length - 1} step="1" bind:value={frame} style="width:240px" oninput={() => (playing = false)} />
			<label class="inline">速度
				<select bind:value={speed}><option value={0.25}>0.25×</option><option value={0.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option></select>
			</label>
			<label class="inline"><input type="checkbox" bind:checked={follow} /> 镜头跟随</label>
		</div>
		<div class="cards">
			<div class="stat"><b>{outcome.dist.toFixed(3)} m</b><span>{outcome.dur.toFixed(1)} s 内前进</span></div>
			<div class="stat"><b>{outcome.speed.toFixed(3)} m/s</b><span>平均速度</span></div>
			{#if outcome.efficiency !== null}<div class="stat"><b>{(outcome.efficiency * 100).toFixed(0)}%</b><span>前进效率（实际 ÷ 理想步幅）</span></div>{/if}
			<div class="stat"><b>{replay.info.environment.gravity} m/s² · {replay.info.environment.air_density} kg/m³</b><span>重力 · 空气密度</span></div>
			<div class="stat"><b>{replay.info.drive === "sail" ? `帆，风 ${replay.info.wind.speed} m/s` : "电机"}</b><span>驱动{replay.info.wind.kind === "gusts" ? "（阵风）" : ""}</span></div>
		</div>
		{#if replay.stalled}
			<p class="notice">
				{#if replay.info.drive === "sail"}它<b>没能自己动起来</b>（或动得太慢没跑完）：这个风速下帆的扭矩不够克服起步负载。把风速调大点再试，或换金星看看。{:else}电机<b>卡住</b>了：被地形挡住或载荷超过了电机的扭矩上限。{/if}
			</p>
		{/if}
		{#if outcome.efficiency !== null && outcome.efficiency < 0.5 && !replay.stalled}
			<p class="notice">它<b>几乎没有前进</b>（只达到理想距离的 {(outcome.efficiency * 100).toFixed(0)}%）：脚被地形挡住、在原地打滑，或者扭矩不够。拖动时间轴看看卡在哪里。</p>
		{/if}
		<div class="plots">
			<div>
				<small>曲柄扭矩 (N·m) {charts.torque.lo.toFixed(4)} – {charts.torque.hi.toFixed(4)}</small>
				<svg viewBox="0 0 300 50"><polyline points={charts.torque.pts} fill="none" stroke="var(--accent)" stroke-width="1.5" /><line x1={cursor} x2={cursor} y1="0" y2="50" stroke="var(--blue)" stroke-width="1" /></svg>
			</div>
			<div>
				<small>机身位置 x (m) {charts.x.lo.toFixed(3)} – {charts.x.hi.toFixed(3)}</small>
				<svg viewBox="0 0 300 50"><polyline points={charts.x.pts} fill="none" stroke="var(--blue)" stroke-width="1.5" /><line x1={cursor} x2={cursor} y1="0" y2="50" stroke="var(--accent)" stroke-width="1" /></svg>
			</div>
		</div>
		<small>其他星球的重力和空气密度是近似值（NASA 数据表和维基百科），尚未在本次会话里逐项核对；风只作用在帆上，不作用在机身上；软地面、沙地没有建模。</small>
	{/if}
</div>

<style>
	.chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0; }
	.host { width: 100%; border: 1px solid var(--line); border-radius: 10px; background: var(--bg); overflow: hidden; margin: 8px 0; min-height: 300px; }
	.host :global(canvas) { display: block; }
	.plots { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 8px; }
	.plots svg { width: 100%; height: 56px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); }
	input[type="number"] { width: 70px; }
</style>
