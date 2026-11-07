import { readFileSync } from "node:fs";
import { expect, type Locator, type Page, test } from "@playwright/test";

const catalogs = Object.fromEntries(
	["zh", "en"].map((language) => [
		language,
		JSON.parse(readFileSync(`apps/web-demo/src/i18n/${language}.json`, "utf8")),
	]),
);
const replayFixture = JSON.parse(
	readFileSync("contracts/sim-run/signed-energy-v3.json", "utf8"),
).replay;
const api = process.env.BEEST_E2E_API_URL ?? "http://127.0.0.1:8787";
let browserErrors: string[];

function label(language: string, key: string): string {
	const value = catalogs[language][key];
	if (typeof value !== "string") throw new Error(`Missing message: ${key}`);
	return value;
}

async function open(page: Page, language: string, tab: string, root: string) {
	await page.goto(`/?lang=${language}&tab=${tab}`);
	await expect(page.locator("#app")).toHaveAttribute(
		"data-kernel",
		"rust-wasm/0.1.0",
	);
	await expect(page.locator(root)).toBeVisible();
}

async function checkWidths(
	page: Page,
	root: Locator,
	prefix: string,
	info: { outputPath: (name: string) => string },
) {
	for (const width of [375, 768, 1024, 1440]) {
		await page.setViewportSize({ width, height: 1000 });
		await expect(root).toBeVisible();
		await expect
			.poll(
				() =>
					page.evaluate(
						() => document.documentElement.scrollWidth <= innerWidth,
					),
				`No horizontal document overflow at ${width}px`,
			)
			.toBe(true);
		const box = await root.boundingBox();
		expect(box?.x).toBeGreaterThanOrEqual(0);
		expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(width + 1);
		await page.screenshot({
			path: info.outputPath(`${prefix}-${width}-dark.png`),
			fullPage: true,
		});
	}
}

async function captureThemes(
	page: Page,
	language: string,
	name: string,
	mask: Locator[],
) {
	await expect(page).toHaveScreenshot(`${name}-dark.png`, {
		fullPage: true,
		mask,
	});
	await page
		.getByRole("button", {
			name: label(language, "app.theme.light"),
			exact: true,
		})
		.click();
	await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
	await expect(page).toHaveScreenshot(`${name}-light.png`, {
		fullPage: true,
		mask,
	});
}

test.beforeEach(async ({ page }) => {
	browserErrors = [];
	await page.addInitScript((url) => {
		localStorage.clear();
		localStorage.setItem("strandbeest-api", url);
	}, api);
	page.on("pageerror", (error) => browserErrors.push(error.message));
	page.on("console", (message) => {
		if (message.type() === "error") browserErrors.push(message.text());
	});
	page.on("response", (response) => {
		if (response.status() === 404) browserErrors.push(`404 ${response.url()}`);
	});
});

test.afterEach(() => {
	expect(browserErrors, "Browser console, page and HTTP errors").toEqual([]);
});

test("simulation workbench keeps source, status and timeline responsive @visual", async ({
	page,
}, info) => {
	test.skip(
		info.project.metadata.mode !== "static",
		"Deterministic baked replay",
	);
	const { language, mode } = info.project.metadata;
	await page.route("**/gallery/flat.json", (route) =>
		route.fulfill({ json: replayFixture }),
	);
	await open(page, language, "sim", ".simulation-workspace");
	const player = page.locator(".scene-player");
	const timeline = player.getByLabel(label(language, "scenes.timeline"), {
		exact: true,
	});
	await expect(timeline).toBeVisible();
	await timeline.press("End");
	await timeline.press("Home");
	await expect(timeline).toHaveValue("0");
	await expect(player.locator(".run-provenance .state-badge")).toHaveText(
		label(language, "scenes.source.baked"),
	);
	await expect(player.locator(".stage-status .state-badge")).toHaveAttribute(
		"data-state",
		"ready",
	);
	await checkWidths(
		page,
		page.locator(".simulation-workspace"),
		`simulation-${mode}-${language}`,
		info,
	);
	await captureThemes(page, language, "simulation-workspace", [
		player.locator(".views"),
	]);
});

test("digital beach exposes its model boundary and remains usable across the shell @visual", async ({
	page,
}, info) => {
	const { language, mode } = info.project.metadata;
	await open(page, language, "beach", ".beach-root");
	await expect(page.locator(".canvas-wrap canvas")).toBeVisible();
	await expect(
		page.getByText(label(language, "beach.modelBadge"), { exact: true }),
	).toBeVisible();
	await expect(page.locator(".beach-root")).not.toContainText("MAP-Elites");
	await expect(page.locator(".walker-card")).toHaveCount(3);
	await page
		.getByRole("button", { name: label(language, "beach.spawn"), exact: true })
		.click();
	await expect(page.locator(".walker-card")).toHaveCount(4);
	await page
		.getByRole("button", {
			name: label(language, "beach.card.remove"),
			exact: true,
		})
		.first()
		.click();
	await expect(page.locator(".walker-card")).toHaveCount(3);
	await page
		.getByRole("button", {
			name: label(language, "beach.controls.pause"),
			exact: true,
		})
		.click();
	await expect(
		page.getByRole("button", {
			name: label(language, "beach.controls.play"),
			exact: true,
		}),
	).toBeVisible();
	await checkWidths(
		page,
		page.locator(".beach-root"),
		`beach-${mode}-${language}`,
		info,
	);
	await captureThemes(page, language, "digital-beach", [
		page.locator(".canvas-wrap"),
		page.locator(".status-summary"),
		page.locator(".walkers-section"),
	]);
});

test("fabrication workbench retains real design context and export actions @visual", async ({
	page,
}, info) => {
	test.skip(
		info.project.metadata.mode !== "live",
		"Fabrication requires the live API",
	);
	const { language, mode } = info.project.metadata;
	await open(page, language, "fab", ".fab-workspace");
	await expect(
		page.getByRole("heading", {
			name: label(language, "fab.workspaceTitle"),
			exact: true,
		}),
	).toBeVisible();
	await expect(page.locator(".design-context-bar")).toContainText(
		label(language, "research.localDesign"),
	);
	await expect(
		page.getByRole("button", {
			name: label(language, "fab.checkExport"),
			exact: true,
		}),
	).toBeEnabled();
	await expect(
		page.getByLabel(label(language, "fab.clearance"), { exact: true }),
	).toBeVisible();
	await checkWidths(
		page,
		page.locator(".fab-workspace"),
		`fabrication-${mode}-${language}`,
		info,
	);
	await captureThemes(page, language, "fabrication-workspace", [
		page.locator(".design-context-bar dd").first(),
	]);
});

test("laboratory workbench preserves the ordered measurement and calibration path @visual", async ({
	page,
}, info) => {
	test.skip(
		info.project.metadata.mode !== "live",
		"Laboratory requires the live API",
	);
	const { language, mode } = info.project.metadata;
	await open(page, language, "lab", ".lab-workspace");
	for (const key of [
		"lab.raw.title",
		"lab.import.title",
		"lab.compare.title",
		"lab.calib.title",
	]) {
		await expect(
			page.getByRole("heading", { name: label(language, key), exact: true }),
		).toBeVisible();
	}
	await page
		.getByRole("button", { name: label(language, "lab.refresh"), exact: true })
		.click();
	await expect(
		page.locator(".lab-workspace .workspace-actions .state-badge"),
	).toHaveCount(0);
	await checkWidths(
		page,
		page.locator(".lab-workspace"),
		`laboratory-${mode}-${language}`,
		info,
	);
	await captureThemes(page, language, "laboratory-workspace", [
		page.locator(".design-context-bar dd").first(),
	]);
});
