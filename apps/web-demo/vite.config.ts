import { fileURLToPath } from "node:url";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

export default defineConfig({
	plugins: [svelte()],
	base: "./",
	worker: { format: "es" },
	// Use the library source directly so the demo needs no build step for core.
	resolve: {
		alias: {
			"strandbeest-core": fileURLToPath(
				new URL("../../packages/core/src/index.ts", import.meta.url),
			),
		},
	},
});
