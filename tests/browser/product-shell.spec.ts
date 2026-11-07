import { readFileSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { expect, type Page, test } from "@playwright/test";

const catalogs = Object.fromEntries(
	["zh", "en"].map((language) => [
		language,
		JSON.parse(readFileSync(`apps/web-demo/src/i18n/${language}.json`, "utf8")),
	]),
);

function label(language: string, key: string): string {
	const value = catalogs[language][key];
	if (typeof value !== "string") throw new Error(`Missing message: ${key}`);
	return value;
}

async function open(page: Page, language: string, tab = "design") {
	await page.goto(`/?lang=${language}&tab=${tab}`);
	await expect(page.locator("#app")).toHaveAttribute(
		"data-kernel",
		"rust-wasm/0.1.0",
	);
	const workspace =
		tab === "evolve"
			? ".evolution-workspace"
			: tab === "research"
				? ".research-workspace"
				: ".design-workspace";
	await expect(page.locator(workspace)).toBeVisible();
}

async function navigate(page: Page, language: string, key: string) {
	await page
		.locator("nav")
		.getByRole("button", { name: label(language, key), exact: true })
		.click();
}

let browserErrors: string[];

test.beforeEach(async ({ page }) => {
	browserErrors = [];
	await page.addInitScript((url) => {
		localStorage.setItem("strandbeest-api", url);
	}, process.env.BEEST_E2E_API_URL ?? "http://127.0.0.1:8787");
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

test("shell deep links, primary workflows and command keyboard access", async ({
	page,
}, info) => {
	const { language, mode } = info.project.metadata;
	await open(page, language, "evolve");
	await expect(page.locator(".evolution-workspace")).toBeVisible();
	await expect(page.locator(".evolver")).toBeVisible();
	await expect(page.locator(".design-workspace")).toHaveCount(0);
	await expect(
		page.getByRole("button", { name: label(language, "history.undo") }),
	).toBeDisabled();
	await navigate(page, language, "nav.sim");
	await expect(
		page.getByRole("heading", { name: label(language, "scenes.title") }),
	).toBeVisible();
	await expect(page).toHaveURL(/[?&]tab=sim/);
	await page.reload();
	await expect(
		page.getByRole("heading", { name: label(language, "scenes.title") }),
	).toBeVisible();
	await navigate(page, language, "nav.design");
	await page.keyboard.press("Control+K");
	await expect(
		page.getByRole("dialog", { name: label(language, "palette.title") }),
	).toBeVisible();
	await page.keyboard.press("Escape");
	await expect(page.getByRole("dialog")).toHaveCount(0);
	await navigate(page, language, "nav.beach");
	await expect(
		page.getByRole("heading", { name: label(language, "beach.title") }),
	).toBeVisible();
	if (mode === "live") {
		await navigate(page, language, "nav.fab");
		await expect(
			page.getByRole("heading", {
				name: label(language, "fab.workspaceTitle"),
				exact: true,
			}),
		).toBeVisible();
		await navigate(page, language, "nav.lab");
		await expect(
			page.getByRole("heading", { name: label(language, "lab.title") }),
		).toBeVisible();
	}
});

test("research shell deep links keep honest empty states and domain access", async ({
	page,
}, info) => {
	const { language } = info.project.metadata;
	await open(page, language, "research");
	await expect(page.locator(".project-context")).toContainText(
		label(language, "research.noExperimentShort"),
	);
	await expect(page.locator("#research-panel")).toContainText(
		label(language, "research.emptyProtocolTitle"),
	);
	await page.locator("#research-tab-evidence").click();
	await expect(page).toHaveURL(/[?&]view=evidence/);
	await expect(page.locator("#research-panel")).toContainText(
		label(language, "research.emptyEvidenceTitle"),
	);
	await page.reload();
	await expect(page.locator("#research-tab-evidence")).toHaveAttribute(
		"aria-selected",
		"true",
	);
	await expect(page.locator(".research-workspace .bar")).toHaveCount(0);
	await page.locator("#research-tab-runs").focus();
	await page.keyboard.press("Enter");
	await expect(page).toHaveURL(/[?&]view=runs/);
	await expect(page.locator("#research-panel")).toContainText(
		label(language, "research.emptyRunsTitle"),
	);
	await page
		.getByRole("button", {
			name: label(language, "research.openDesign"),
			exact: true,
		})
		.click();
	await expect(page.locator(".design-workspace")).toBeVisible();
	await expect(page).toHaveURL(/[?&]tab=design/);
	await navigate(page, language, "nav.research");
	await expect(page.locator(".research-workspace")).toBeVisible();
});

test("research shell responsive and visual states @visual", async ({
	page,
}, info) => {
	const { language, mode } = info.project.metadata;
	await open(page, language, "research");
	for (const width of [375, 768, 1024, 1440]) {
		await page.setViewportSize({ width, height: 1000 });
		await expect(page.locator("#research-panel")).toBeVisible();
		await expect
			.poll(
				() =>
					page.evaluate(
						() => document.documentElement.scrollWidth <= innerWidth,
					),
				`No horizontal document overflow at ${width}px`,
			)
			.toBe(true);
		const panel = await page.locator("#research-panel").boundingBox();
		expect(panel?.x).toBeGreaterThanOrEqual(0);
		expect((panel?.x ?? 0) + (panel?.width ?? 0)).toBeLessThanOrEqual(
			width + 1,
		);
		await page.screenshot({
			path: info.outputPath(`research-${mode}-${language}-${width}-dark.png`),
			fullPage: true,
		});
	}
	const dynamicDesignId = page.locator(".domain-context dd").first();
	await expect(page).toHaveScreenshot("research-shell-dark.png", {
		fullPage: true,
		mask: [dynamicDesignId],
	});
	await page
		.getByRole("button", { name: label(language, "app.theme.light") })
		.click();
	await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
	await expect(page).toHaveScreenshot("research-shell-light.png", {
		fullPage: true,
		mask: [dynamicDesignId],
	});
});

test("theme and language preferences survive reload", async ({
	page,
}, info) => {
	const language: string = info.project.metadata.language;
	const other = language === "zh" ? "en" : "zh";
	await open(page, language);
	const canvas = page.locator(".viewer canvas");
	const darkCanvas = await canvas.evaluate((element: HTMLCanvasElement) =>
		element.toDataURL(),
	);
	await page
		.getByRole("button", { name: label(language, "app.theme.light") })
		.click();
	await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
	await expect
		.poll(() =>
			canvas.evaluate((element: HTMLCanvasElement) => element.toDataURL()),
		)
		.not.toBe(darkCanvas);
	await page
		.getByRole("combobox", { name: label(language, "app.language") })
		.selectOption(other);
	await expect(page.locator(".workspace-header h2")).toHaveText(
		label(other, "design.workspaceTitle"),
	);
	await page.reload();
	await expect(page.locator("#app")).toHaveAttribute(
		"data-kernel",
		"rust-wasm/0.1.0",
	);
	await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
	await expect(page.locator(".workspace-header h2")).toHaveText(
		label(other, "design.workspaceTitle"),
	);
});

test("slider preview commits one operation with shell undo and redo", async ({
	page,
}, info) => {
	const { language } = info.project.metadata;
	await open(page, language);
	const parameter = page.locator(".parameter").nth(2);
	const slider = parameter.locator('input[type="range"]');
	const number = parameter.locator('input[type="number"]');
	const stepCount = () =>
		page.evaluate(() => {
			const raw = localStorage.getItem("strandbeest-editor-v1");
			return raw ? (JSON.parse(raw) as { steps: unknown[] }).steps.length : 0;
		});
	const before = await stepCount();
	const box = await slider.boundingBox();
	if (!box) throw new Error("Slider has no pointer target");
	const minimum = Number(await slider.getAttribute("min"));
	const maximum = Number(await slider.getAttribute("max"));
	const initial = Number(await slider.inputValue());
	const startX =
		box.x + ((initial - minimum) / (maximum - minimum)) * box.width;
	await page.mouse.move(startX, box.y + box.height / 2);
	await page.mouse.down();
	await page.mouse.move(startX - 8, box.y + box.height / 2, { steps: 4 });
	await expect(page.locator(".save-state")).toContainText(
		label(language, "app.previewing"),
	);
	expect(await stepCount()).toBe(before);
	await page.mouse.up();
	await expect.poll(stepCount).toBe(before + 1);
	const committed = await number.inputValue();
	await page
		.getByRole("button", { name: label(language, "history.undo"), exact: true })
		.click();
	await expect(number).not.toHaveValue(committed);
	await page
		.getByRole("button", { name: label(language, "history.redo"), exact: true })
		.click();
	await expect(number).toHaveValue(committed);
	const pending = page.waitForEvent("download");
	await page
		.locator(".project-actions")
		.getByRole("button", {
			name: label(language, "design.downloadJson"),
			exact: true,
		})
		.click();
	const downloaded = await pending;
	expect(downloaded.suggestedFilename()).toMatch(/\.json$/);
	const path = await downloaded.path();
	if (!path) throw new Error("JSON download has no local path");
	const design = JSON.parse(await readFile(path, "utf8"));
	expect(design.linkage.params).toBeTruthy();
	await navigate(page, language, "nav.sim");
	await expect(
		page.getByRole("button", { name: label(language, "history.redo") }),
	).toBeDisabled();
});

test("invalid preview clears stale metrics and rejection restores the design", async ({
	page,
}, info) => {
	const { language } = info.project.metadata;
	await open(page, language);
	await expect(page.locator(".metric-strip")).toBeVisible();
	const number = page
		.locator(".parameter")
		.first()
		.locator('input[type="number"]');
	const maximum = await number.getAttribute("max");
	if (!maximum) throw new Error("Length input has no maximum");
	await number.fill(maximum);
	await expect(
		page.getByRole("alert").filter({
			hasText: label(language, "design.unassemblable"),
		}),
	).toBeVisible();
	await expect(page.locator(".metric-strip")).toHaveCount(0);
	await number.press("Tab");
	await expect(page.locator(".notice.error").first()).toContainText(
		"cannot_assemble",
	);
	await expect(page.locator(".metric-strip")).toBeVisible();
	await expect(
		page.getByRole("button", { name: label(language, "history.undo") }),
	).toBeDisabled();
});

test("reduced motion and responsive layouts keep the canvas reachable @visual", async ({
	page,
}, info) => {
	const { language, mode } = info.project.metadata;
	await open(page, language);
	await expect(
		page.getByRole("button", {
			name: label(language, "common.play"),
			exact: true,
		}),
	).toBeVisible();
	for (const width of [375, 768, 1024, 1440]) {
		await page.setViewportSize({ width, height: 1000 });
		await expect(page.locator(".viewer canvas")).toBeVisible();
		expect(
			await page.evaluate(
				() => document.documentElement.scrollWidth <= innerWidth,
			),
			`No horizontal document overflow at ${width}px`,
		).toBe(true);
		const box = await page.locator(".viewer canvas").boundingBox();
		expect(box?.x).toBeGreaterThanOrEqual(0);
		expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(width + 1);
		await page.screenshot({
			path: info.outputPath(`design-${mode}-${language}-${width}-dark.png`),
			fullPage: true,
		});
	}
	const dynamicDesignId = page.locator(".design-context-bar dd").first();
	await expect(page).toHaveScreenshot("design-workspace-dark.png", {
		fullPage: true,
		mask: [dynamicDesignId],
	});
	await page
		.getByRole("button", { name: label(language, "app.theme.light") })
		.click();
	await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
	await expect(page).toHaveScreenshot("design-workspace-light.png", {
		fullPage: true,
		mask: [dynamicDesignId],
	});
	await page.screenshot({
		path: info.outputPath(`design-${mode}-${language}-1440-light.png`),
		fullPage: true,
	});
});
