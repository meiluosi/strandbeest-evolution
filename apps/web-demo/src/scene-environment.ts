import * as THREE from "three";
import type { EnvironmentPreset } from "./environment-preset";

export interface SceneEnvironment {
	group: THREE.Group;
	sand: THREE.MeshStandardMaterial;
	updateTarget: (target: THREE.Vector3) => void;
	setEnabled: (enabled: boolean, usePvc?: boolean) => void;
	dispose: () => void;
}

function canvasTexture(
	size: number,
	paint: (context: CanvasRenderingContext2D, size: number) => void,
): THREE.CanvasTexture {
	const canvas = document.createElement("canvas");
	canvas.width = size;
	canvas.height = size;
	const context = canvas.getContext("2d");
	if (!context) throw new Error("Canvas 2D is unavailable");
	paint(context, size);
	const texture = new THREE.CanvasTexture(canvas);
	texture.colorSpace = THREE.SRGBColorSpace;
	return texture;
}

function moonTexture(color: number): THREE.CanvasTexture {
	const tint = new THREE.Color(color);
	return canvasTexture(256, (context, size) => {
		const gradient = context.createRadialGradient(
			size * 0.38,
			size * 0.32,
			4,
			size / 2,
			size / 2,
			size / 2,
		);
		gradient.addColorStop(0, `#${tint.getHexString()}`);
		gradient.addColorStop(
			0.72,
			`#${tint.clone().multiplyScalar(0.78).getHexString()}`,
		);
		gradient.addColorStop(
			1,
			`#${tint.clone().multiplyScalar(0.42).getHexString()}`,
		);
		context.fillStyle = gradient;
		context.beginPath();
		context.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2);
		context.fill();
		context.save();
		context.beginPath();
		context.arc(size / 2, size / 2, size / 2 - 1, 0, Math.PI * 2);
		context.clip();
		for (let i = 0; i < 22; i++) {
			const x = ((i * 83 + 29) % 211) + 20;
			const y = ((i * 47 + 61) % 197) + 24;
			const radius = 3 + ((i * 17) % 13);
			context.fillStyle = `rgba(25, 35, 50, ${0.025 + (i % 4) * 0.015})`;
			context.beginPath();
			context.ellipse(x, y, radius * 1.35, radius, i * 0.4, 0, Math.PI * 2);
			context.fill();
		}
		context.restore();
	});
}

function haloTexture(color: number): THREE.CanvasTexture {
	const tint = new THREE.Color(color);
	return canvasTexture(128, (context, size) => {
		const gradient = context.createRadialGradient(
			size / 2,
			size / 2,
			size * 0.15,
			size / 2,
			size / 2,
			size / 2,
		);
		gradient.addColorStop(
			0,
			`rgba(${Math.round(tint.r * 255)}, ${Math.round(tint.g * 255)}, ${Math.round(tint.b * 255)}, 0.28)`,
		);
		gradient.addColorStop(
			0.42,
			`rgba(${Math.round(tint.r * 255)}, ${Math.round(tint.g * 255)}, ${Math.round(tint.b * 255)}, 0.1)`,
		);
		gradient.addColorStop(1, "rgba(80, 130, 180, 0)");
		context.fillStyle = gradient;
		context.fillRect(0, 0, size, size);
	});
}

function sandTexture(): THREE.CanvasTexture {
	const texture = canvasTexture(128, (context, size) => {
		const image = context.createImageData(size, size);
		for (let i = 0; i < size * size; i++) {
			const value = 115 + ((i * 73 + Math.floor(i / size) * 31) % 61);
			image.data[i * 4] = value;
			image.data[i * 4 + 1] = value;
			image.data[i * 4 + 2] = value;
			image.data[i * 4 + 3] = 255;
		}
		context.putImageData(image, 0, 0);
	});
	texture.wrapS = THREE.RepeatWrapping;
	texture.wrapT = THREE.RepeatWrapping;
	texture.repeat.set(36, 18);
	texture.colorSpace = THREE.NoColorSpace;
	return texture;
}

function skyMaterial(preset: EnvironmentPreset): THREE.ShaderMaterial {
	return new THREE.ShaderMaterial({
		side: THREE.BackSide,
		depthWrite: false,
		fog: false,
		uniforms: {
			topColor: { value: new THREE.Color(preset.skyTop) },
			horizonColor: { value: new THREE.Color(preset.skyHorizon) },
		},
		vertexShader: `
			varying vec3 vLocal;
			void main() {
				vLocal = position;
				gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
			}
		`,
		fragmentShader: `
			uniform vec3 topColor;
			uniform vec3 horizonColor;
			varying vec3 vLocal;
			void main() {
				float height = smoothstep(-0.08, 0.72, normalize(vLocal).y);
				gl_FragColor = vec4(mix(horizonColor, topColor, height), 1.0);
			}
		`,
	});
}

function waterMaterial(preset: EnvironmentPreset): THREE.ShaderMaterial {
	return new THREE.ShaderMaterial({
		uniforms: {
			deepColor: { value: new THREE.Color(preset.waterDeep) },
			lightColor: { value: new THREE.Color(preset.waterLight) },
			moonColor: { value: new THREE.Color(preset.moon) },
		},
		vertexShader: `
			varying vec2 vUv;
			void main() {
				vUv = uv;
				gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
			}
		`,
		fragmentShader: `
			uniform vec3 deepColor;
			uniform vec3 lightColor;
			uniform vec3 moonColor;
			varying vec2 vUv;
			void main() {
				float ripple = sin(vUv.y * 92.0 + sin(vUv.x * 24.0) * 1.4) * 0.5 + 0.5;
				float horizon = smoothstep(0.0, 0.88, vUv.y);
				vec3 water = mix(lightColor, deepColor, horizon);
				water += lightColor * ripple * 0.022;
				float reflectionWidth = mix(0.022, 0.1, 1.0 - vUv.y);
				float reflection = exp(-pow((vUv.x - 0.445) / reflectionWidth, 2.0));
				reflection *= (0.1 + ripple * 0.18) * (1.0 - smoothstep(0.72, 1.0, vUv.y));
				gl_FragColor = vec4(mix(water, moonColor, reflection), 1.0);
			}
		`,
	});
}

function addMegastructure(group: THREE.Group): void {
	const monument = new THREE.Group();
	monument.position.set(0.85, 0.04, -5.2);
	monument.rotation.z = -0.22;
	monument.scale.setScalar(0.72);
	const metal = new THREE.MeshStandardMaterial({
		color: 0x243745,
		emissive: 0x0a1c28,
		emissiveIntensity: 0.55,
		roughness: 0.72,
		metalness: 0.68,
	});
	monument.add(
		new THREE.Mesh(
			new THREE.TorusGeometry(1.12, 0.019, 8, 180, Math.PI * 1.76),
			metal,
		),
	);
	const inner = new THREE.Mesh(
		new THREE.TorusGeometry(1.04, 0.006, 6, 160, Math.PI * 1.7),
		metal,
	);
	inner.rotation.z = 0.035;
	monument.add(inner);
	const beaconMaterial = new THREE.MeshBasicMaterial({
		color: 0x8cd7e7,
		toneMapped: false,
	});
	for (let i = 0; i < 9; i++) {
		const angle = 0.24 + i * 0.57;
		const beacon = new THREE.Mesh(
			new THREE.SphereGeometry(0.012, 8, 6),
			beaconMaterial,
		);
		beacon.position.set(Math.cos(angle) * 1.12, Math.sin(angle) * 1.12, 0.012);
		monument.add(beacon);
	}
	const supportGeometry = new THREE.BoxGeometry(0.035, 0.7, 0.055);
	for (const x of [-0.48, 0.48]) {
		const support = new THREE.Mesh(supportGeometry, metal);
		support.position.set(x, -0.88, 0);
		monument.add(support);
	}
	const causeway = new THREE.Mesh(
		new THREE.BoxGeometry(4.8, 0.025, 0.07),
		metal,
	);
	causeway.position.set(-1.25, -1.17, 0);
	monument.add(causeway);
	group.add(monument);
}

export function createSceneEnvironment(
	scene: THREE.Scene,
	preset: EnvironmentPreset,
	dark: boolean,
): SceneEnvironment {
	const group = new THREE.Group();
	group.name = `environment-${preset.kind}`;
	const celestial = new THREE.Group();
	group.add(celestial);
	const sky = new THREE.Mesh(
		new THREE.SphereGeometry(15, 40, 24),
		skyMaterial(preset),
	);
	sky.renderOrder = -100;
	celestial.add(sky);

	if (preset.stars) {
		const positions = new Float32Array(120 * 3);
		for (let i = 0; i < 120; i++) {
			positions[i * 3] = -7 + (((i * 137) % 997) / 997) * 14;
			positions[i * 3 + 1] = 0.42 + (((i * 263) % 991) / 991) * 4.8;
			positions[i * 3 + 2] = -5.5 - (((i * 71) % 100) / 100) * 3;
		}
		const geometry = new THREE.BufferGeometry();
		geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
		celestial.add(
			new THREE.Points(
				geometry,
				new THREE.PointsMaterial({
					color: preset.moon,
					size: 0.009,
					transparent: true,
					opacity: 0.58,
					depthWrite: false,
					fog: false,
				}),
			),
		);
	}

	if (preset.moonDisc) {
		const halo = new THREE.Sprite(
			new THREE.SpriteMaterial({
				map: haloTexture(preset.moon),
				transparent: true,
				depthWrite: false,
				fog: false,
				toneMapped: false,
			}),
		);
		halo.position.set(-1.1, 0.85, -4.8);
		halo.scale.set(1.1, 1.1, 1);
		celestial.add(halo);
		const moon = new THREE.Sprite(
			new THREE.SpriteMaterial({
				map: moonTexture(preset.moon),
				transparent: true,
				depthWrite: false,
				fog: false,
				toneMapped: false,
			}),
		);
		moon.position.copy(halo.position);
		moon.scale.set(0.5, 0.5, 1);
		celestial.add(moon);
	}

	if (preset.sea) {
		const water = new THREE.Mesh(
			new THREE.PlaneGeometry(20, 8),
			waterMaterial(preset),
		);
		water.rotation.x = -Math.PI / 2;
		water.position.set(0, -0.001, -6);
		group.add(water);
		const wetSand = new THREE.Mesh(
			new THREE.PlaneGeometry(10, 0.62),
			new THREE.ShaderMaterial({
				transparent: true,
				depthWrite: false,
				uniforms: { tint: { value: new THREE.Color(preset.wetSand) } },
				vertexShader: `
					varying vec2 vUv;
					void main() {
						vUv = uv;
						gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
					}
				`,
				fragmentShader: `
					uniform vec3 tint;
					varying vec2 vUv;
					void main() {
						float edge = smoothstep(0.0, 0.22, vUv.y) * (1.0 - smoothstep(0.68, 1.0, vUv.y));
						float tide = 0.44 + sin(vUv.x * 32.0) * 0.035;
						gl_FragColor = vec4(tint, edge * tide);
					}
				`,
			}),
		);
		wetSand.rotation.x = -Math.PI / 2;
		wetSand.position.set(0, -0.00035, -1.72);
		group.add(wetSand);
	}

	addMegastructure(group);
	const moonlight = new THREE.DirectionalLight(preset.moon, 0.72);
	moonlight.position.set(-1.5, 2.4, -2.5);
	group.add(moonlight);
	group.add(moonlight.target);
	scene.add(group);

	const grain = sandTexture();
	const sand = new THREE.MeshStandardMaterial({
		color: preset.sand,
		roughness: 0.88,
		metalness: 0.02,
		bumpMap: grain,
		bumpScale: 0.00035,
	});
	let enabled = true;
	return {
		group,
		sand,
		updateTarget(target) {
			celestial.position.copy(target);
		},
		setEnabled(next, usePvc = true) {
			enabled = next;
			group.visible = next;
			scene.background = next ? new THREE.Color(preset.skyTop) : null;
			scene.fog = next ? new THREE.Fog(preset.skyHorizon, 1.8, 10) : null;
			sand.color.setHex(
				next ? preset.sand : dark ? 0x1e2028 : usePvc ? 0xf3ead8 : 0xeeeae0,
			);
			sand.roughness = next ? 0.88 : 0.92;
			sand.bumpScale = next ? 0.00035 : 0;
		},
		dispose() {
			scene.remove(group);
			if (enabled) {
				scene.background = null;
				scene.fog = null;
			}
			const textures = new Set<THREE.Texture>();
			group.traverse((object) => {
				if (
					!(
						object instanceof THREE.Mesh ||
						object instanceof THREE.Points ||
						object instanceof THREE.Sprite
					)
				)
					return;
				if (!(object instanceof THREE.Sprite)) object.geometry?.dispose();
				const materials = Array.isArray(object.material)
					? object.material
					: [object.material];
				for (const material of materials) {
					for (const value of Object.values(material)) {
						if (value instanceof THREE.Texture) textures.add(value);
					}
					material.dispose();
				}
			});
			grain.dispose();
			sand.dispose();
		},
	};
}
