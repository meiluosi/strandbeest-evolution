import { expect, test } from "@playwright/test";

test("product demo primary workflows and visual states", async ({ page }) => {
	const errors: string[] = [];
	page.on("pageerror", (error) => errors.push(error.message));
	page.on("console", (message) => {
		if (message.type() === "error") errors.push(message.text());
	});
	page.on("response", (response) => {
		if (response.status() >= 400)
			errors.push(`${response.status()} ${response.url()}`);
	});

	await page.goto("/");
	await expect(page.getByRole("heading", { name: "机构设计" })).toBeVisible();
	await expect(page.locator("#main-links line")).toHaveCount(10);
	await expect(page.locator(".geometry-status")).toHaveClass(/valid/);

	const crank = page.locator("#param-m-number");
	await crank.fill("17");
	await crank.press("Tab");
	await expect(crank).toHaveValue("17.0");
	await expect(page.locator("#save-state")).toContainText("有未保存修改");
	await page.locator('[data-action="undo"]').click();
	await expect(page.locator("#param-m-number")).toHaveValue("15.0");
	await page.locator('[data-action="redo"]').click();
	await expect(page.locator("#param-m-number")).toHaveValue("17.0");

	await page.locator("#path-focus").click();
	await expect(page.locator("#mechanism-canvas")).toHaveClass(/path-emphasis/);
	await page.locator("#mechanism-view").click();
	await expect(page.locator("#mechanism-canvas")).not.toHaveClass(
		/path-emphasis/,
	);
	await page.locator("#design-play").click();
	await page.waitForTimeout(250);
	await expect(page.locator("#design-play")).toHaveAttribute(
		"aria-label",
		"暂停",
	);
	await page.locator("#design-play").click();
	await page.locator("#reset-design").click();
	await expect(page.locator(".geometry-status")).toHaveClass(/valid/);
	await page.locator("#toast").evaluate((el) => {
		el.setAttribute("class", "toast");
	});
	await page.screenshot({
		path: "test-results/design-desktop.png",
		fullPage: true,
	});

	await page.locator('[data-page="evolve"]').click();
	await expect(page.getByRole("heading", { name: "演化实验室" })).toBeVisible();
	await page.locator("#evolve-start").click();
	await expect(page.locator("#evolution-status")).toContainText("正在评估", {
		timeout: 3000,
	});
	await page.locator("#evolve-start").click();
	await page.locator('[data-candidate="1"]').click();
	await expect(page.locator('[data-candidate="1"]')).toHaveAttribute(
		"aria-pressed",
		"true",
	);
	await page.locator("#toast").evaluate((el) => {
		el.setAttribute("class", "toast");
	});
	await page.screenshot({
		path: "test-results/evolve-desktop.png",
		fullPage: true,
	});
	await page.locator("#apply-candidate").click();
	await expect(page.getByRole("heading", { name: "机构设计" })).toBeVisible();
	await expect(page.locator("#param-m-number")).toHaveValue("15.8");

	await page.locator('[data-page="sim"]').click();
	await expect(page.getByRole("heading", { name: "仿真回放" })).toBeVisible();
	const flatGround = await page.locator("#scene-ground").getAttribute("d");
	await page.locator('[data-scene="slope"]').click();
	expect(await page.locator("#scene-ground").getAttribute("d")).not.toBe(
		flatGround,
	);
	await page.locator('[data-scene="wind"]').click();
	expect(await page.locator("#wind-field path").count()).toBeGreaterThan(0);
	await page.locator("#compare-toggle").check();
	expect(
		await page.locator("#previous-walker .walker-link").count(),
	).toBeGreaterThan(0);
	await page.locator('[data-overlay="trails"]').uncheck();
	await expect(page.locator("#trail-overlay")).toBeEmpty();
	await page.locator('.diagnosis-list [data-seek="2.8"]').click();
	await expect(page.locator("#sim-timeline")).toHaveValue("2.8");
	await expect(page.locator("#sim-play-state")).toHaveText("已暂停");
	await page.locator('[data-camera="top"]').click();
	await expect(page.locator("#camera-world")).toHaveAttribute(
		"transform",
		/scale/,
	);
	await page.locator("#toast").evaluate((el) => {
		el.setAttribute("class", "toast");
	});
	await page.screenshot({
		path: "test-results/sim-desktop.png",
		fullPage: true,
	});

	await page.locator('[data-action="theme"]').click();
	await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
	await page.locator("#toast").evaluate((el) => {
		el.setAttribute("class", "toast");
	});
	await page.screenshot({ path: "test-results/sim-dark.png", fullPage: true });
	await page.locator('[data-action="language"]').click();
	await expect(
		page.getByRole("heading", { name: "Simulation replay" }),
	).toBeVisible();
	await page.locator('[data-action="language"]').click();
	await expect(page.getByRole("heading", { name: "仿真回放" })).toBeVisible();
	expect(errors).toEqual([]);
});

test("responsive layouts do not overflow the page", async ({ page }) => {
	for (const width of [375, 768, 1024, 1440]) {
		await page.setViewportSize({ width, height: 900 });
		await page.goto("/");
		await expect(page.locator("#mechanism-svg")).toBeVisible();
		const dimensions = await page.evaluate(() => ({
			page: document.documentElement.scrollWidth,
			viewport: window.innerWidth,
		}));
		expect(dimensions.page, `design at ${width}px`).toBeLessThanOrEqual(
			dimensions.viewport,
		);
		if (width === 375)
			await page.screenshot({
				path: "test-results/design-mobile.png",
				fullPage: true,
			});

		await page.locator('[data-page="evolve"]').click();
		expect(
			await page.evaluate(() => document.documentElement.scrollWidth),
			`evolve at ${width}px`,
		).toBeLessThanOrEqual(width);
		await page.locator('[data-page="sim"]').click();
		expect(
			await page.evaluate(() => document.documentElement.scrollWidth),
			`sim at ${width}px`,
		).toBeLessThanOrEqual(width);
		if (width === 375)
			await page.screenshot({
				path: "test-results/sim-mobile.png",
				fullPage: true,
			});
	}
});
