import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
	// use the library source directly, as the web demo does
	resolve: {
		alias: {
			"strandbeest-core": fileURLToPath(
				new URL("../core/src/index.ts", import.meta.url),
			),
		},
	},
});
