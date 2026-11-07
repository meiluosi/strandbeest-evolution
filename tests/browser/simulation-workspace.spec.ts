import { readFileSync } from "node:fs";
import { expect, type Locator, type Page, test } from "@playwright/test";

const catalogs = Object.fromEntries(
	["zh", "en"].map((language) => [
		language,
		JSON.parse(readFileSync(`apps/web-demo/src/i18n/${language}.json`, "utf8")),
	]),
);
const fixture = JSON.parse(
	readFileSync("contracts/sim-run/signed-energy-v3.json", "utf8"),
).replay;
const api = process.env.BEEST_E2E_API_URL ?? "http://127.0.0.1:8787";
let browserErrors: string[];

function label(language: string, key: string): string {
	const value = catalogs[language][key];
	if (typeof value !== "string") throw new Error(`Missing message: ${key}`);
	return value;
}

async function open(page: Page, language: string) {
	await page.goto(`/?lang=${language}&tab=sim`);
	await expect(page.locator("#app")).toHaveAttribute(
		"data-kernel",
		"rust-wasm/0.1.0",
	);
	await expect(page.locator(".simulation-workspace")).toBeVisible();
}

async function pauseAtStart(player: Locator, language: string) {
	const slider = player.getByLabel(label(language, "scenes.timeline"), {
		exact: true,
	});
	await expect(player.locator(".views canvas").first()).toBeVisible();
	await slider.press("End");
	await slider.press("Home");
	await expect(slider).toHaveValue("0");
}

test.beforeEach(async ({ page }) => {
	browserErrors = [];
	page.on("pageerror", (error) => browserErrors.push(error.message));
	page.on("console", (message) => {
		if (message.type() === "error") browserErrors.push(message.text());
	});
	page.on("response", (response) => {
		if (response.status() === 404) browserErrors.push(`404 ${response.url()}`);
	});
	await page.addInitScript((url) => {
		localStorage.clear();
		localStorage.setItem("strandbeest-api", url);
	}, api);
});

test.afterEach(() => {
	expect(browserErrors, "Browser console, page and HTTP errors").toEqual([]);
});

test("baked replay exposes provenance, available layers and one shared clock", async ({
	page,
}, info) => {
	test.skip(info.project.metadata.mode !== "static", "Baked replay test");
	const { language } = info.project.metadata;
	const replay = structuredClone(fixture);
	delete replay.foot_force;
	delete replay.foot_slip;
	delete replay.com;
	await page.route("**/gallery/flat.json", (route) =>
		route.fulfill({ json: replay }),
	);
	await open(page, language);
	const player = page.locator(".scene-player");
	await pauseAtStart(player, language);
	await expect(player.locator(".run-provenance .state-badge")).toHaveText(
		label(language, "scenes.source.baked"),
	);
	await expect(player.locator(".evidence-badge")).toBeVisible();
	for (const key of ["forces", "slip", "com", "wind", "pneumatics"]) {
		await expect(
			player.getByLabel(label(language, `overlay.${key}`), { exact: true }),
		).toBeDisabled();
	}
	await expect(
		player.getByLabel(label(language, "overlay.trails"), { exact: true }),
	).toBeEnabled();
	const slider = player.getByLabel(label(language, "scenes.timeline"), {
		exact: true,
	});
	await slider.press("End");
	const current = Number(await slider.inputValue());
	expect(current).toBeGreaterThan(0);
	const cursors = await player
		.locator(".plots .time-cursor")
		.evaluateAll(
			(nodes, value) =>
				nodes.map((node) => Number(node.getAttribute("x1")) / 300),
			current / Number(await slider.getAttribute("max")),
		);
	expect(cursors).toHaveLength(2);
	expect(cursors[0]).toBeCloseTo(cursors[1] ?? 0, 6);
	await expect(player.locator(".analysis-heading span")).toHaveText(
		`${current.toFixed(2)} s`,
	);
	const event = player.locator(".timeline .ev").first();
	await expect(event).toBeVisible();
	await event.click();
	expect(Number(await slider.inputValue())).toBeCloseTo(fixture.events[0].t, 6);
});

test("scene loading clears old results and supports cancellation and failure recovery", async ({
	page,
}, info) => {
	test.skip(info.project.metadata.mode !== "static", "Baked loading test");
	const { language } = info.project.metadata;
	let slopeAttempts = 0;
	let releaseFirst: () => void = () => {};
	await page.route("**/gallery/flat.json", (route) =>
		route.fulfill({ json: fixture }),
	);
	await page.route("**/gallery/slope.json", async (route) => {
		slopeAttempts += 1;
		if (slopeAttempts === 1) {
			await new Promise<void>((resolve) => {
				releaseFirst = resolve;
			});
		}
		try {
			await route.fulfill({ json: fixture });
		} catch {
			return;
		}
	});
	await open(page, language);
	const player = page.locator(".scene-player");
	await pauseAtStart(player, language);
	await player
		.getByRole("button", {
			name: label(language, "scene.slope.name"),
			exact: true,
		})
		.click();
	await expect(player.locator(".stage-status")).toContainText(
		label(language, "scenes.status.loading"),
	);
	await expect(player.locator(".views")).toHaveCount(0);
	await expect(player.locator(".summary")).toHaveCount(0);
	await expect(player.locator(".run-provenance .state-badge")).toHaveCount(0);
	await player
		.getByRole("button", {
			name: label(language, "common.cancel"),
			exact: true,
		})
		.click();
	await expect(player.locator(".stage-status")).toContainText(
		label(language, "scenes.status.cancelled"),
	);
	await expect(player.locator(".notice.info")).toContainText(
		label(language, "scenes.cancelled"),
	);
	releaseFirst();
	await player
		.getByRole("button", {
			name: label(language, "scene.slope.name"),
			exact: true,
		})
		.click();
	await pauseAtStart(player, language);
	await page.unroute("**/gallery/slope.json");
	await page.route("**/gallery/slope.json", (route) =>
		route.fulfill({ status: 503, body: "unavailable" }),
	);
	await player
		.getByRole("button", {
			name: label(language, "scene.flat.name"),
			exact: true,
		})
		.click();
	await pauseAtStart(player, language);
	await player
		.getByRole("button", {
			name: label(language, "scene.slope.name"),
			exact: true,
		})
		.click();
	await expect(player.getByRole("alert")).toContainText("503");
	await expect(player.locator(".stage-status")).toContainText(
		label(language, "scenes.status.error"),
	);
	await expect(player.locator(".views")).toHaveCount(0);
	browserErrors = browserErrors.filter(
		(message) => !message.includes("status of 503"),
	);
});

test("A/B comparison keeps labels, units, deltas and mobile layout readable", async ({
	page,
}, info) => {
	test.skip(info.project.metadata.mode !== "static", "Baked A/B test");
	const { language } = info.project.metadata;
	const next = structuredClone(fixture);
	next.metrics.stride_per_rev += 0.1;
	await page.route("**/gallery/flat.json", (route) =>
		route.fulfill({ json: fixture }),
	);
	await page.route("**/gallery/slope.json", (route) =>
		route.fulfill({ json: next }),
	);
	await open(page, language);
	const player = page.locator(".scene-player");
	await pauseAtStart(player, language);
	await player
		.getByRole("button", {
			name: label(language, "scene.slope.name"),
			exact: true,
		})
		.click();
	await pauseAtStart(player, language);
	await player.locator(".compare-toggle input").check();
	await expect(player.locator(".views canvas")).toHaveCount(2);
	await expect(player.locator(".views .label").first()).toContainText("A ·");
	await expect(player.locator(".views .label").last()).toContainText("B ·");
	const comparison = player.getByRole("table", {
		name: label(language, "compare.title"),
		exact: true,
	});
	await expect(comparison).toContainText(label(language, "compare.delta"));
	const stride = comparison.locator("tbody tr").first();
	await expect(stride.locator("td").first()).toContainText(
		label(language, "compare.stride"),
	);
	const expectedDelta = (
		next.metrics.stride_per_rev - fixture.metrics.stride_per_rev
	).toFixed(4);
	await expect(stride.locator("td").last()).toHaveText(expectedDelta);
	await player
		.getByLabel(label(language, "scenes.timeline"), { exact: true })
		.press("End");
	const cursors = await player
		.locator(".plots .time-cursor")
		.evaluateAll((nodes) => nodes.map((node) => node.getAttribute("x1")));
	expect(cursors[0]).toBe(cursors[1]);
	await page
		.getByRole("button", {
			name: label(language, "app.theme.light"),
			exact: true,
		})
		.click();
	await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
	for (const width of [375, 768, 1024, 1440]) {
		await page.setViewportSize({ width, height: 1000 });
		expect(
			await page.evaluate(
				() => document.documentElement.scrollWidth <= innerWidth,
			),
			`No horizontal document overflow at ${width}px`,
		).toBe(true);
		if (width === 375) {
			const columns = await player
				.locator(".views.two")
				.evaluate((node) => getComputedStyle(node).gridTemplateColumns);
			expect(columns.trim().split(/\s+/)).toHaveLength(1);
		}
		await player.screenshot({
			path: info.outputPath(`simulation-${language}-${width}-light.png`),
		});
	}
});

test("backend cancellation is explicit and advanced run tools remain available", async ({
	page,
}, info) => {
	test.skip(info.project.metadata.mode !== "live", "Backend cancellation test");
	const { language } = info.project.metadata;
	await page.route(`${api}/runs`, (route) =>
		route.fulfill({ json: { job_id: "p2-cancel" } }),
	);
	await page.route(`${api}/jobs/p2-cancel`, (route) =>
		route.fulfill({
			json: {
				id: "p2-cancel",
				kind: "run",
				status: "running",
				result: null,
				error: null,
				progress: { done: 0, total: 1, message: "running" },
			},
		}),
	);
	const cancelled = page.waitForRequest(
		(request) =>
			request.method() === "POST" &&
			request.url() === `${api}/jobs/p2-cancel/cancel`,
	);
	await page.route(`${api}/jobs/p2-cancel/cancel`, (route) =>
		route.fulfill({ json: { status: "cancelled" } }),
	);
	await open(page, language);
	const player = page.locator(".scene-player");
	await expect(page.locator(".advanced-tools")).toBeVisible();
	await expect(
		page.getByRole("heading", {
			name: label(language, "sweep.title"),
			exact: true,
		}),
	).toBeVisible();
	await expect(
		page.getByRole("heading", {
			name: label(language, "history.title"),
			exact: true,
		}),
	).toBeVisible();
	await player
		.getByRole("button", { name: label(language, "scenes.run"), exact: true })
		.click();
	await player
		.getByRole("button", {
			name: label(language, "common.cancel"),
			exact: true,
		})
		.click();
	await cancelled;
	await expect(player.locator(".stage-status")).toContainText(
		label(language, "scenes.status.cancelled"),
	);
	await expect(player.getByRole("alert")).toHaveCount(0);
	await expect(
		player.getByRole("button", {
			name: label(language, "scenes.run"),
			exact: true,
		}),
	).toBeEnabled();
});

test("browser run warns in a background tab and cancels without a false result", async ({
	page,
}, info) => {
	const { language } = info.project.metadata;
	await open(page, language);
	if (info.project.metadata.mode === "static") {
		await expect(page.locator(".scene-player .views canvas")).toBeVisible();
	}
	const player = page.locator(".scene-player");
	await player
		.getByRole("button", {
			name: label(language, "scenes.browserRun"),
			exact: true,
		})
		.click();
	await page.evaluate(() => {
		Object.defineProperty(document, "hidden", {
			configurable: true,
			get: () => true,
		});
		document.dispatchEvent(new Event("visibilitychange"));
	});
	await expect(player.locator(".notice.warning")).toContainText(
		label(language, "scenes.browserBackgroundWarning"),
	);
	await player
		.getByRole("button", {
			name: label(language, "common.cancel"),
			exact: true,
		})
		.click();
	await expect(player.locator(".stage-status")).toContainText(
		label(language, "scenes.status.cancelled"),
	);
	await expect(player.locator(".summary")).toHaveCount(0);
	await expect(player.getByRole("alert")).toHaveCount(0);
	await expect(
		player.getByRole("button", {
			name: label(language, "scenes.browserRun"),
			exact: true,
		}),
	).toBeEnabled();
});

test("environment art switches independently of replay data and remains usable on mobile", async ({
	page,
}, info) => {
	test.skip(info.project.metadata.mode !== "static", "Baked environment test");
	const { language } = info.project.metadata;
	await page.setViewportSize({ width: 375, height: 812 });
	await page.route("**/gallery/flat.json", (route) =>
		route.fulfill({ json: fixture }),
	);
	await open(page, language);
	const player = page.locator(".scene-player");
	await pauseAtStart(player, language);
	const toggle = player.getByLabel(label(language, "overlay.environment"), {
		exact: true,
	});
	const canvas = player.locator(".views canvas").first();
	await expect(toggle).toBeChecked();
	const artistic = await canvas.screenshot();
	await toggle.uncheck();
	await expect(toggle).not.toBeChecked();
	const analytical = await canvas.screenshot();
	expect(artistic.equals(analytical)).toBe(false);
	await toggle.check();
	await expect(toggle).toBeChecked();
	expect(
		await page.evaluate(
			() => document.documentElement.scrollWidth <= innerWidth,
		),
	).toBe(true);
});
