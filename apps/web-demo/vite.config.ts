import { fileURLToPath } from "node:url";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { configDefaults, defineConfig } from "vitest/config";

export default defineConfig({
	plugins: [svelte()],
	base: "./",
	worker: { format: "es" },
	test: { exclude: [...configDefaults.exclude, "product-demo/**"] },
	// three.js is loaded on demand (3D views), so its size does not affect first paint
	build: { chunkSizeWarningLimit: 800 },
	// Use the library source directly so the demo needs no build step for core.
	resolve: {
		alias: {
			"strandbeest-core": fileURLToPath(
				new URL("../../packages/core/src/index.ts", import.meta.url),
			),
		},
	},
});
