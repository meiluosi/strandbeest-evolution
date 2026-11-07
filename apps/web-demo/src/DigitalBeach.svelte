<script lang="ts">
import { solvePose } from "strandbeest-core";
import type * as THREE_NS from "three";
import {
	type BeachWalkerState,
	beachDuneHeight,
	DigitalBeachSim,
	PHENOTYPES,
} from "./digital-beach-sim";
import { t } from "./i18n/index.svelte";
import StateBadge from "./StateBadge.svelte";
import { theme } from "./theme.svelte";
import WorkspaceHeader from "./WorkspaceHeader.svelte";

let host: HTMLDivElement;
const sim = new DigitalBeachSim();

// Svelte 5 reactive state
let selectedPhenotype = $state("classic_jansen");
let windSpeed = $state(6.0);
let windGust = $state(2.5);
let windDir = $state(0.0);
let tideLevel = $state(0.05);
let dynamicTide = $state(true);
let isPlaying = $state(true);
let walkerCount = $state(0);
let currentTideZ = $state(0.05);
let currentWindV = $state(6.0);
let walkersList = $state<BeachWalkerState[]>([]);

// Pre-populate with initial herd
sim.scatter(3);
updateStateView();

function updateStateView() {
	walkerCount = sim.walkers.length;
	walkersList = [...sim.walkers];
	currentTideZ = sim.tide.z0;
	currentWindV = sim.wind.v0;
}

function onSpawn() {
	sim.spawnWalker(selectedPhenotype);
	updateStateView();
}

function onScatter() {
	sim.scatter(4);
	updateStateView();
}

function onClear() {
	sim.clear();
	updateStateView();
}

function onResetMarks() {
	sim.contactMarks = [];
}

function onRemoveWalker(id: string) {
	sim.removeWalker(id);
	updateStateView();
}

function togglePlay() {
	isPlaying = !isPlaying;
}

$effect(() => {
	sim.wind.v0 = windSpeed;
	sim.wind.amplitude = windGust;
	sim.wind.directionDeg = windDir;
});

$effect(() => {
	sim.tide.z0 = tideLevel;
	sim.tide.enabled = dynamicTide;
});

$effect(() => {
	theme.mode;
	let disposed = false;
	let raf = 0;
	let cleanup = () => {};

	(async () => {
		const THREE: typeof THREE_NS = await import("three");
		const { OrbitControls } = await import(
			"three/examples/jsm/controls/OrbitControls.js"
		);

		if (disposed || !host) return;

		const dark = document.documentElement.dataset.theme === "dark";
		const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
		renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		renderer.setSize(host.clientWidth, host.clientHeight);
		renderer.shadowMap.enabled = true;
		renderer.shadowMap.type = THREE.PCFSoftShadowMap;
		host.appendChild(renderer.domElement);

		const scene = new THREE.Scene();
		scene.fog = new THREE.FogExp2(dark ? 0x141824 : 0xecf2f8, 0.035);

		const camera = new THREE.PerspectiveCamera(
			45,
			host.clientWidth / host.clientHeight,
			0.1,
			80,
		);
		camera.position.set(6.0, 7.5, 9.5);

		const controls = new OrbitControls(camera, renderer.domElement);
		controls.enableDamping = true;
		controls.dampingFactor = 0.05;
		controls.target.set(0.0, 0.5, 0.0);
		controls.maxPolarAngle = Math.PI / 2 - 0.03; // Keep above sand ground

		// Lighting
		const hemiLight = new THREE.HemisphereLight(
			dark ? 0x90b0e0 : 0xfffae6,
			dark ? 0x242018 : 0xd8caa8,
			1.2,
		);
		scene.add(hemiLight);

		const sunLight = new THREE.DirectionalLight(0xfff5d8, 1.8);
		sunLight.position.set(12, 18, 10);
		sunLight.castShadow = true;
		sunLight.shadow.mapSize.set(2048, 2048);
		sunLight.shadow.camera.near = 1;
		sunLight.shadow.camera.far = 45;
		const shadowRange = 14;
		sunLight.shadow.camera.left = -shadowRange;
		sunLight.shadow.camera.right = shadowRange;
		sunLight.shadow.camera.top = shadowRange;
		sunLight.shadow.camera.bottom = -shadowRange;
		sunLight.shadow.bias = -0.0004;
		scene.add(sunLight);

		// Coordinate transformation: MuJoCo (x fwd, y lateral, z up) -> Three.js
		// Rotates X by -90 deg so Z is up in world space
		const world = new THREE.Group();
		world.quaternion.setFromAxisAngle(new THREE.Vector3(1, 0, 0), -Math.PI / 2);
		scene.add(world);

		// 1. Beach sand dunes heightfield
		const duneSize = 34;
		const duneSegments = 120;
		const duneGeo = new THREE.PlaneGeometry(
			duneSize,
			duneSize,
			duneSegments,
			duneSegments,
		);
		const posAttr = duneGeo.attributes.position;
		if (posAttr) {
			for (let i = 0; i < posAttr.count; i++) {
				const px = posAttr.getX(i);
				const py = posAttr.getY(i);
				const pz = beachDuneHeight(px, py);
				posAttr.setZ(i, pz);
			}
			duneGeo.computeVertexNormals();
		}

		const sandMat = new THREE.MeshStandardMaterial({
			color: dark ? 0xc4a36a : 0xdfc27d,
			roughness: 0.92,
			metalness: 0.05,
			flatShading: false,
		});
		const duneMesh = new THREE.Mesh(duneGeo, sandMat);
		duneMesh.receiveShadow = true;
		world.add(duneMesh);

		// 2. Dynamic translucent tide water plane
		const waterGeo = new THREE.PlaneGeometry(36, 36, 48, 48);
		const waterMat = new THREE.MeshStandardMaterial({
			color: 0x188ea8,
			roughness: 0.12,
			metalness: 0.35,
			transparent: true,
			opacity: 0.65,
			depthWrite: false,
		});
		const waterMesh = new THREE.Mesh(waterGeo, waterMat);
		world.add(waterMesh);

		// 3. High-performance InstancedMesh for linkage bars (capsule/cylinder)
		const MAX_BARS = 3500;
		const barGeo = new THREE.CylinderGeometry(0.007, 0.007, 1.0, 8);
		barGeo.rotateZ(Math.PI / 2); // align along X axis for length scaling
		const barMat = new THREE.MeshStandardMaterial({
			roughness: 0.35,
			metalness: 0.15,
		});
		const barsInstanced = new THREE.InstancedMesh(barGeo, barMat, MAX_BARS);
		barsInstanced.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
		barsInstanced.castShadow = true;
		world.add(barsInstanced);

		// 4. InstancedMesh for linkage joints & feet (spheres)
		const MAX_JOINTS = 3500;
		const jointGeo = new THREE.SphereGeometry(0.013, 10, 10);
		const jointMat = new THREE.MeshStandardMaterial({
			color: 0x333338,
			roughness: 0.3,
			metalness: 0.4,
		});
		const jointsInstanced = new THREE.InstancedMesh(
			jointGeo,
			jointMat,
			MAX_JOINTS,
		);
		jointsInstanced.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
		jointsInstanced.castShadow = true;
		world.add(jointsInstanced);

		// 5. InstancedMesh for footprint contact marks stamped on sand dunes
		const MAX_FOOTPRINTS = 600;
		const footprintGeo = new THREE.CircleGeometry(0.035, 12);
		const footprintMat = new THREE.MeshBasicMaterial({
			color: dark ? 0x8a7248 : 0xaa8e58,
			transparent: true,
			opacity: 0.6,
			depthWrite: false,
		});
		const footprintsInstanced = new THREE.InstancedMesh(
			footprintGeo,
			footprintMat,
			MAX_FOOTPRINTS,
		);
		footprintsInstanced.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
		world.add(footprintsInstanced);

		// 6. InstancedMesh for storm ground-anchor spikes
		const MAX_ANCHORS = 64;
		const spikeGeo = new THREE.CylinderGeometry(0.008, 0.002, 0.18, 8);
		spikeGeo.rotateX(Math.PI / 2);
		const spikeMat = new THREE.MeshStandardMaterial({
			color: 0x1e1e24,
			metalness: 0.85,
			roughness: 0.2,
		});
		const anchorsInstanced = new THREE.InstancedMesh(
			spikeGeo,
			spikeMat,
			MAX_ANCHORS,
		);
		anchorsInstanced.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
		world.add(anchorsInstanced);

		// Scratch 3D math objects for zero-allocation rendering loop
		const _dummy = new THREE.Object3D();
		const _unitX = new THREE.Vector3(1, 0, 0);
		const _vStart = new THREE.Vector3();
		const _vEnd = new THREE.Vector3();
		const _vMid = new THREE.Vector3();
		const _vDir = new THREE.Vector3();
		const _color = new THREE.Color();

		// Handle resize
		const resizeObserver = new ResizeObserver(() => {
			if (!host) return;
			const w = host.clientWidth;
			const h = host.clientHeight;
			camera.aspect = w / h;
			camera.updateProjectionMatrix();
			renderer.setSize(w, h);
		});
		resizeObserver.observe(host);

		let lastTime = performance.now();

		function render() {
			if (disposed) return;
			raf = requestAnimationFrame(render);

			const now = performance.now();
			const dt = Math.min(0.05, (now - lastTime) / 1000);
			lastTime = now;

			if (isPlaying) {
				sim.step(dt);
				updateStateView();
			}

			// Update water surface elevation and subtle traveling waves
			const tideZ = sim.tide.enabled
				? sim.tide.z0 + sim.tide.amplitude * Math.sin(sim.tide.omega * sim.time)
				: sim.tide.z0;
			waterMesh.position.set(0, 0, tideZ);

			// Render multi-walker bodies via InstancedMesh
			let barCount = 0;
			let jointCount = 0;
			let anchorCount = 0;

			for (const w of sim.walkers) {
				const u = w.phenotype.unit;
				const nLegs = w.phenotype.legs;
				const cosH = Math.cos(w.heading);
				const sinH = Math.sin(w.heading);

				// Solve each leg kinematics
				for (let legIdx = 0; legIdx < nLegs; legIdx++) {
					const legPhase = w.crankAngle + (2 * Math.PI * legIdx) / nLegs;
					const pose = solvePose(w.phenotype.spec, legPhase);
					if (!pose) continue;

					const latY =
						(legIdx - (nLegs - 1) / 2) * (w.phenotype.bodyWidth / nLegs);

					// Helper to project local 2D linkage point (x fwd, y up) to 3D world space
					function toWorld(
						pt2: { x: number; y: number },
						target: THREE_NS.Vector3,
					) {
						const lx = pt2.x * u;
						const lz = pt2.y * u; // linkage y is vertical (up in MuJoCo z)
						const ly = latY;

						// Apply walker yaw heading and torso world position
						const wx = w.x + (lx * cosH - ly * sinH);
						const wy = w.y + (lx * sinH + ly * cosH);
						const wz = w.z + lz;
						target.set(wx, wy, wz);
					}

					// Draw linkage joints (spheres)
					for (const ptKey of ["G", "C", "K", "L", "M", "N", "F"]) {
						if (!pose[ptKey] || jointCount >= MAX_JOINTS) continue;
						toWorld(pose[ptKey], _dummy.position);
						_dummy.scale.set(1, 1, 1);
						_dummy.quaternion.identity();
						_dummy.updateMatrix();
						jointsInstanced.setMatrixAt(jointCount++, _dummy.matrix);
					}

					// Linkage bar connectivity pairs
					const links: [string, string][] = [
						["G", "C"],
						["G", "K"],
						["C", "K"],
						["G", "L"],
						["K", "L"],
						["G", "M"],
						["C", "M"],
						["L", "N"],
						["M", "N"],
						["M", "F"],
						["N", "F"],
					];

					_color.setHex(w.phenotype.color);

					for (const [p1, p2] of links) {
						if (!pose[p1] || !pose[p2] || barCount >= MAX_BARS) continue;
						toWorld(pose[p1], _vStart);
						toWorld(pose[p2], _vEnd);

						_vMid.addVectors(_vStart, _vEnd).multiplyScalar(0.5);
						_vDir.subVectors(_vEnd, _vStart);
						const len = _vDir.length();
						if (len < 1e-4) continue;
						_vDir.normalize();

						_dummy.position.copy(_vMid);
						_dummy.quaternion.setFromUnitVectors(_unitX, _vDir);
						_dummy.scale.set(len, 1, 1);
						_dummy.updateMatrix();

						barsInstanced.setMatrixAt(barCount, _dummy.matrix);
						barsInstanced.setColorAt(barCount, _color);
						barCount++;
					}
				}

				// Storm anchor spike rendering
				if ((w.anchorFiring || w.anchorDeployed) && anchorCount < MAX_ANCHORS) {
					_dummy.position.set(
						w.x,
						w.y,
						w.z - 0.16 + 0.05 - w.anchorPenetration,
					);
					_dummy.quaternion.identity();
					_dummy.scale.set(1, 1, 1);
					_dummy.updateMatrix();
					anchorsInstanced.setMatrixAt(anchorCount++, _dummy.matrix);
				}
			}

			barsInstanced.count = barCount;
			barsInstanced.instanceMatrix.needsUpdate = true;
			if (barsInstanced.instanceColor)
				barsInstanced.instanceColor.needsUpdate = true;

			jointsInstanced.count = jointCount;
			jointsInstanced.instanceMatrix.needsUpdate = true;

			anchorsInstanced.count = anchorCount;
			anchorsInstanced.instanceMatrix.needsUpdate = true;

			// Render contact footprints
			let markCount = 0;
			for (const mark of sim.contactMarks) {
				if (markCount >= MAX_FOOTPRINTS) break;
				_dummy.position.set(mark.x, mark.y, mark.z);
				_dummy.quaternion.identity();
				const s = mark.radius * 2 * mark.alpha;
				_dummy.scale.set(s, s, s);
				_dummy.updateMatrix();
				footprintsInstanced.setMatrixAt(markCount++, _dummy.matrix);
			}
			footprintsInstanced.count = markCount;
			footprintsInstanced.instanceMatrix.needsUpdate = true;

			controls.update();
			renderer.render(scene, camera);
		}

		render();

		cleanup = () => {
			disposed = true;
			cancelAnimationFrame(raf);
			resizeObserver.disconnect();
			renderer.dispose();
			duneGeo.dispose();
			sandMat.dispose();
			waterGeo.dispose();
			waterMat.dispose();
			barGeo.dispose();
			barMat.dispose();
			jointGeo.dispose();
			jointMat.dispose();
			footprintGeo.dispose();
			footprintMat.dispose();
			spikeGeo.dispose();
			spikeMat.dispose();
			if (host.contains(renderer.domElement)) {
				host.removeChild(renderer.domElement);
			}
		};
	})();

	return () => cleanup();
});
</script>

<div class="beach-root">
	<WorkspaceHeader eyebrow={t("beach.workspaceEyebrow")} title={t("beach.title")} description={t("beach.subtitle")}>
		{#snippet actions()}
			<StateBadge label={t("beach.modelBadge")} tone="info" />
			<button class="btn primary" onclick={togglePlay}>
				{isPlaying ? t("beach.controls.pause") : t("beach.controls.play")}
			</button>
		{/snippet}
	</WorkspaceHeader>
	<div class="status-summary" aria-label={t("beach.statusSummary")}>
		<span class="badge"><strong>{t("beach.status.walkers")}</strong> {walkerCount}</span>
		<span class="badge"><strong>{t("beach.status.wind")}</strong> {currentWindV.toFixed(1)} m/s</span>
		<span class="badge"><strong>{t("beach.status.waterLevel")}</strong> {currentTideZ.toFixed(2)} m</span>
	</div>

	<div class="main-layout">
		<!-- 3D Canvas Viewport -->
		<div class="canvas-wrap" bind:this={host}>
			<div class="hud-overlay">
				<div class="legend-box">
					<div class="legend-row">
						<span class="dot dry"></span>
						<span>{t("beach.card.dry")}</span>
					</div>
					<div class="legend-row">
						<span class="dot submerged"></span>
						<span>{t("beach.card.submerged")}</span>
					</div>
					<div class="legend-row">
						<span class="dot anchored"></span>
						<span>{t("beach.card.anchored")}</span>
					</div>
				</div>
			</div>
		</div>

		<!-- Control & Telemetry Sidebar -->
		<div class="sidebar">
			<!-- Spawning Section -->
			<div class="card">
				<h3>{t("beach.spawn")}</h3>
				<label class="control-group">
					<span class="label-text">{t("beach.phenotype")}</span>
					<select bind:value={selectedPhenotype}>
						{#each Object.values(PHENOTYPES) as pheno}
							<option value={pheno.id}>{t(pheno.nameKey)}</option>
						{/each}
					</select>
				</label>
				<p class="pheno-desc">
					{t(PHENOTYPES[selectedPhenotype]?.descKey ?? "")}
				</p>
				<div class="btn-row">
					<button class="btn btn-accent" onclick={onSpawn}>
						{t("beach.spawn")}
					</button>
					<button class="btn" onclick={onScatter}>
						{t("beach.controls.scatter")}
					</button>
					<button class="btn btn-danger" onclick={onClear}>
						{t("beach.controls.clear")}
					</button>
				</div>
			</div>

			<!-- Environmental Controls -->
			<div class="card">
				<h3>{t("beach.status.wind")} & {t("beach.status.waterLevel")}</h3>

				<label class="slider-row">
					<span class="slider-label">{t("beach.controls.windSpeed")}: {windSpeed.toFixed(1)} m/s</span>
					<input type="range" min="0" max="24" step="0.5" bind:value={windSpeed} />
				</label>

				<label class="slider-row">
					<span class="slider-label">{t("beach.controls.windGust")}: ±{windGust.toFixed(1)} m/s</span>
					<input type="range" min="0" max="8" step="0.2" bind:value={windGust} />
				</label>

				<label class="slider-row">
					<span class="slider-label">{t("beach.controls.windDir")}: {windDir.toFixed(0)}°</span>
					<input type="range" min="0" max="360" step="5" bind:value={windDir} />
				</label>

				<label class="slider-row">
					<span class="slider-label">{t("beach.controls.tideLevel")}: {tideLevel.toFixed(2)} m</span>
					<input type="range" min="-0.3" max="0.4" step="0.02" bind:value={tideLevel} />
				</label>

				<label class="checkbox-row">
					<input type="checkbox" bind:checked={dynamicTide} />
					<span>{t("beach.controls.dynamicTide")}</span>
				</label>

				<button class="btn btn-sm" onclick={onResetMarks}>
					{t("beach.controls.resetMarks")}
				</button>
			</div>

			<!-- Walker Cards List -->
			<div class="walkers-section">
				<h3>{t("beach.status.walkers")} ({walkersList.length})</h3>
				{#if walkersList.length === 0}
					<p class="empty-hint">{t("beach.emptyHint")}</p>
				{/if}
				{#each walkersList as w}
					<div class="walker-card">
						<div class="card-header">
							<span
								class="color-indicator"
								style="background-color: #{w.phenotype.color.toString(16).padStart(6, '0')}"
							></span>
							<strong>{t(w.phenotype.nameKey)}</strong>
							<button class="delete-btn" aria-label={t("beach.card.remove")} onclick={() => onRemoveWalker(w.id)} title={t("beach.card.remove")}>×</button>
						</div>

						<div class="reflex-tags">
							{#if w.feelerImmersed}
								<span class="tag tag-submerged">{t("beach.card.submerged")}</span>
							{:else}
								<span class="tag tag-dry">{t("beach.card.dry")}</span>
							{/if}

							{#if w.anchorDeployed}
								<span class="tag tag-anchored">{t("beach.card.anchored")}</span>
							{:else}
								<span class="tag tag-armed">{t("beach.card.armed")}</span>
							{/if}
						</div>

						<div class="telemetry-grid">
							<span>{t("beach.card.speed")}: {Math.abs(w.vx).toFixed(2)} m/s</span>
							<span>{t("beach.card.tilt")}: {w.tiltAngleDeg.toFixed(1)}°</span>
							{#if w.repulsionForce > 1.0}
								<span class="warn">{t("beach.card.repulsion")}: {w.repulsionForce.toFixed(0)} N</span>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		</div>
	</div>
</div>

<style>
	.beach-root {
		display: flex;
		flex-direction: column;
		gap: 12px;
		width: 100%;
	}
	.status-summary {
		display: flex;
		gap: 8px;
		align-items: center;
		flex-wrap: wrap;
	}
	.badge {
		display: inline-flex;
		gap: 6px;
		background: var(--surface-inset);
		border: 1px solid var(--line);
		padding: 6px 10px;
		border-radius: var(--radius-sm);
		color: var(--text-soft);
		font-size: 12px;
	}
	.badge strong { color: var(--text-muted); font-weight: 500; }
	.main-layout {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 340px;
		gap: 16px;
		min-height: 600px;
	}
	@media (max-width: 860px) {
		.main-layout { grid-template-columns: minmax(0, 1fr); min-height: 0; }
		.canvas-wrap { min-height: 460px; }
		.sidebar { max-height: none; overflow-y: visible; padding-right: 0; }
	}
	@media (max-width: 480px) {
		.canvas-wrap { min-height: 380px; }
	}
	.canvas-wrap {
		position: relative;
		background: var(--card);
		border: 1px solid var(--line);
		border-radius: 8px;
		min-height: 580px;
		overflow: hidden;
	}
	.hud-overlay {
		position: absolute;
		top: 12px;
		left: 12px;
		pointer-events: none;
	}
	.legend-box {
		background: rgba(25, 27, 36, 0.75);
		color: #ffffff;
		padding: 8px 12px;
		border-radius: 6px;
		font-size: 12px;
		display: flex;
		flex-direction: column;
		gap: 4px;
		backdrop-filter: blur(4px);
	}
	.legend-row {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
	}
	.dot.dry {
		background: #2a9d8f;
	}
	.dot.submerged {
		background: #e76f51;
	}
	.dot.anchored {
		background: #4a4e69;
	}
	.sidebar {
		display: flex;
		flex-direction: column;
		gap: 12px;
		max-height: 780px;
		overflow-y: auto;
		padding-right: 4px;
	}
	.card {
		background: var(--card);
		border: 1px solid var(--line);
		border-radius: 8px;
		padding: 12px 14px;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.card h3, .walkers-section h3 {
		margin: 0;
		font-size: 14px;
		font-weight: 600;
	}
	.control-group {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.label-text {
		font-size: 12px;
		color: var(--muted);
	}
	select, input[type="range"] {
		width: 100%;
	}
	.pheno-desc {
		font-size: 11px;
		color: var(--muted);
		margin: 0;
	}
	.btn-row {
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
		margin-top: 4px;
	}
	.btn {
		font: inherit;
		font-size: 12px;
		padding: 6px 12px;
		border-radius: 6px;
		border: 1px solid var(--line);
		background: var(--card);
		color: var(--ink);
		cursor: pointer;
	}
	.btn:hover {
		background: var(--line);
	}
	.btn.primary, .btn-accent {
		background: var(--accent);
		color: var(--accent-contrast);
		border-color: var(--accent);
	}
	.btn-danger {
		color: var(--danger);
	}
	.btn-sm {
		padding: 4px 8px;
		font-size: 11px;
	}
	.slider-row {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.slider-label {
		font-size: 11px;
		color: var(--muted);
	}
	.checkbox-row {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 12px;
		cursor: pointer;
	}
	.walkers-section {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.empty-hint {
		font-size: 12px;
		color: var(--muted);
		font-style: italic;
	}
	.walker-card {
		background: var(--card);
		border: 1px solid var(--line);
		border-radius: 6px;
		padding: 8px 10px;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.card-header {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 12px;
	}
	.color-indicator {
		width: 10px;
		height: 10px;
		border-radius: 50%;
	}
	.delete-btn {
		margin-left: auto;
		background: transparent;
		border: none;
		color: var(--muted);
		cursor: pointer;
		font-size: 16px;
		line-height: 1;
	}
	.delete-btn:hover {
		color: #d62828;
	}
	.reflex-tags {
		display: flex;
		gap: 4px;
		flex-wrap: wrap;
	}
	.tag {
		font-size: 10px;
		padding: 2px 6px;
		border-radius: 4px;
		font-weight: 600;
	}
	.tag-dry {
		background: rgba(42, 157, 143, 0.15);
		color: #2a9d8f;
	}
	.tag-submerged {
		background: rgba(231, 111, 81, 0.2);
		color: #e76f51;
	}
	.tag-armed {
		background: rgba(140, 140, 150, 0.15);
		color: var(--muted);
	}
	.tag-anchored {
		background: rgba(74, 78, 105, 0.3);
		color: #4a4e69;
	}
	.telemetry-grid {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		font-size: 11px;
		color: var(--muted);
	}
	.warn {
		color: #e76f51;
		font-weight: 600;
	}
</style>
