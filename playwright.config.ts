import { defineConfig } from "@playwright/test";

export default defineConfig({
	testDir: "./tests/browser",
	testMatch: "**/*.spec.ts",
	fullyParallel: false,
	workers: 1,
	forbidOnly: !!process.env.CI,
	retries: 0,
	updateSnapshots: "none",
	timeout: 180_000,
	expect: {
		timeout: 15_000,
		toHaveScreenshot: {
			animations: "disabled",
			maxDiffPixels: 0,
			threshold: 0,
			stylePath: "./tests/browser/screenshot.css",
		},
	},
	outputDir: "test-results/browser",
	snapshotPathTemplate: "{testDir}/baselines/{projectName}/{arg}{ext}",
	reporter: [
		["list"],
		["html", { outputFolder: "playwright-report", open: "never" }],
		["junit", { outputFile: "test-results/browser.xml" }],
	],
	use: {
		browserName: "chromium",
		viewport: { width: 1280, height: 960 },
		deviceScaleFactor: 1,
		colorScheme: "dark",
		reducedMotion: "reduce",
		timezoneId: "UTC",
		trace: "retain-on-failure",
		screenshot: "only-on-failure",
		launchOptions: {
			executablePath: process.env.BEEST_E2E_EXECUTABLE_PATH,
			args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
		},
	},
	projects: ["live", "static"].flatMap((mode) =>
		["zh", "en"].map((language) => ({
			name: `${mode}-${language}`,
			metadata: { mode, language },
			use: {
				baseURL: `http://127.0.0.1:${mode === "live" ? 4173 : 4174}`,
				locale: language === "zh" ? "zh-CN" : "en-US",
			},
		})),
	),
	webServer: [
		{
			command: "node tests/browser/serve.mjs .browser-build/live 4173",
			url: "http://127.0.0.1:4173",
			reuseExistingServer: false,
		},
		{
			command: "node tests/browser/serve.mjs .browser-build/static 4174",
			url: "http://127.0.0.1:4174",
			reuseExistingServer: false,
		},
	],
});
