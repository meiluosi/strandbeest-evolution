import { defineConfig } from "@playwright/test";

export default defineConfig({
	testDir: "./tests",
	fullyParallel: false,
	workers: 1,
	reporter: "list",
	use: {
		baseURL: "http://127.0.0.1:7100",
		channel: "msedge",
		viewport: { width: 1440, height: 1000 },
		reducedMotion: "reduce",
		trace: "retain-on-failure",
	},
	webServer: {
		command: "npm run preview -- --host 127.0.0.1 --port 7100",
		url: "http://127.0.0.1:7100",
		reuseExistingServer: false,
		timeout: 60_000,
	},
});
