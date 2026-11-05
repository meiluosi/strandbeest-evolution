import { readFileSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";

const catalogs = Object.fromEntries(
	["zh", "en"].map((language) => [
		language,
		JSON.parse(readFileSync(`apps/web-demo/src/i18n/${language}.json`, "utf8")),
	]),
);

type WorkerState = {
	generation: number;
	best: number[];
	bestFitness: number;
	meanFitness: number;
};
type WorkerMessage = {
	type: string;
	kernel?: string;
	state?: WorkerState;
};
type WorkerRecord = {
	messages: WorkerMessage[];
	terminated: boolean;
};

function label(language: string, key: string): string {
	const value = catalogs[language][key];
	if (typeof value !== "string") throw new Error(`Missing message: ${key}`);
	return value;
}

async function installWorkerProbe(page: Page) {
	await page.addInitScript((api) => {
		localStorage.clear();
		localStorage.setItem("strandbeest-api", api);
		const records: WorkerRecord[] = [];
		Object.defineProperty(window, "__beestGaWorkers", { value: records });
		const OriginalWorker = window.Worker;
		window.Worker = class extends OriginalWorker {
			private readonly record: WorkerRecord;

			constructor(url: string | URL, options?: WorkerOptions) {
				super(url, options);
				this.record = { messages: [], terminated: false };
				records.push(this.record);
				this.addEventListener("message", (event) => {
					this.record.messages.push(event.data as WorkerMessage);
				});
			}

			terminate() {
				this.record.terminated = true;
				super.terminate();
			}
		};
	}, process.env.BEEST_E2E_API_URL ?? "http://127.0.0.1:8787");
}

async function open(page: Page, language: string) {
	await page.goto("/?lang=" + language + "&tab=evolve");
	await expect(page.locator("#app")).toHaveAttribute(
		"data-kernel",
		"rust-wasm/0.1.0",
	);
	await expect(page.locator(".evolution-workspace")).toBeVisible();
}

async function workers(page: Page): Promise<WorkerRecord[]> {
	return page.evaluate(() => {
		return (
			window as unknown as { __beestGaWorkers: WorkerRecord[] }
		).__beestGaWorkers.map((record) => ({
			messages: record.messages,
			terminated: record.terminated,
		}));
	});
}

async function configure(
	page: Page,
	language: string,
	generations = 2,
	population = 10,
	seed = 11,
) {
	const evolver = page.locator(".evolver");
	await evolver
		.getByLabel(label(language, "evolve.generations"), { exact: true })
		.fill(String(generations));
	await evolver
		.getByLabel(label(language, "evolve.population"), { exact: true })
		.fill(String(population));
	await evolver
		.getByLabel(label(language, "evolve.seed"), { exact: true })
		.fill(String(seed));
}

async function start(page: Page, language: string) {
	await page
		.locator(".evolver")
		.getByRole("button", { name: label(language, "evolve.start"), exact: true })
		.click();
}

async function waitForStatus(page: Page, language: string, key: string) {
	await expect(page.locator(".evolver .run-status")).toHaveText(
		label(language, key),
	);
}

let browserErrors: string[];

test.beforeEach(async ({ page }) => {
	browserErrors = [];
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

test("fixed seed reproduces real states and best applies as an undoable child", async ({
	page,
}, info) => {
	const { language } = info.project.metadata;
	await installWorkerProbe(page);
	await open(page, language);
	await expect(
		page.locator(".evolver .fitness-panel .chart-empty"),
	).toBeVisible();
	await expect(page.locator(".evolver .path-chart")).toHaveCount(0);
	await configure(page, language, 8, 24, 7);
	await start(page, language);
	await waitForStatus(page, language, "evolve.status.done");
	const first = (await workers(page))[0];
	expect(first.terminated).toBe(true);
	const firstStates = first.messages
		.filter((message) => message.type === "state")
		.map((message) => message.state);
	expect(firstStates).toHaveLength(9);
	expect(first.messages.at(-1)?.type).toBe("done");
	expect(
		first.messages.every((message) => message.kernel === "rust-wasm/0.1.0"),
	).toBe(true);
	const final = firstStates.at(-1) as WorkerState;
	await expect(page.locator(".evolver .generation-value")).toHaveText(
		String(final.generation),
	);
	await expect(page.locator(".evolver .best-fitness")).toHaveText(
		final.bestFitness.toFixed(6),
	);
	await expect(page.locator(".evolver .mean-fitness")).toHaveText(
		final.meanFitness.toFixed(6),
	);
	const beforePath = await page
		.locator(".evolver .path-before")
		.getAttribute("points");
	const bestPath = await page
		.locator(".evolver .path-best")
		.getAttribute("points");
	expect(beforePath).toBeTruthy();
	expect(bestPath).toBeTruthy();
	await page.locator(".evolver").screenshot({
		path: info.outputPath(`evolution-completed-${language}.png`),
	});

	await start(page, language);
	await waitForStatus(page, language, "evolve.status.done");
	const second = (await workers(page))[1];
	expect(second.messages.filter((message) => message.type === "state")).toEqual(
		first.messages.filter((message) => message.type === "state"),
	);

	const parentName = await page
		.locator(".project-context strong")
		.textContent();
	const parentId = await page
		.locator(".project-context strong")
		.getAttribute("title");
	await page
		.locator(".evolver")
		.getByRole("button", {
			name: label(language, "evolve.loadBest"),
			exact: true,
		})
		.click();
	await expect(page.locator(".project-context strong")).toHaveText(
		`${parentName}-evolved`,
	);
	expect(
		await page.locator(".project-context strong").getAttribute("title"),
	).not.toBe(parentId);
	const saved = await page.evaluate(() => {
		const raw = localStorage.getItem("strandbeest-editor-v1");
		return raw
			? (JSON.parse(raw) as {
					base: { linkage: { params: Record<string, number> } };
					steps: {
						type: string;
						args: { name: string; value: number };
						actor: { kind: string; id: string };
					}[][];
				})
			: null;
	});
	expect(saved?.steps).toHaveLength(1);
	const names = Object.keys(saved?.base.linkage.params ?? {});
	for (const operation of saved?.steps[0] ?? []) {
		expect(operation.type).toBe("set_param");
		expect(operation.actor).toEqual({ kind: "algorithm", id: "ga" });
		expect(operation.args.value).toBe(
			final.best[names.indexOf(operation.args.name)],
		);
	}
	await page
		.locator("nav")
		.getByRole("button", { name: label(language, "nav.design"), exact: true })
		.click();
	await page
		.getByRole("button", { name: label(language, "history.undo"), exact: true })
		.click();
	const undone = await page.evaluate(() => {
		const raw = localStorage.getItem("strandbeest-editor-v1");
		return raw ? (JSON.parse(raw) as { steps: unknown[] }).steps.length : -1;
	});
	expect(undone).toBe(0);
});

test("stop retains a partial run and a new run can complete", async ({
	page,
}, info) => {
	const { language } = info.project.metadata;
	await installWorkerProbe(page);
	await open(page, language);
	await configure(page, language, 80, 60);
	await start(page, language);
	await expect
		.poll(async () => (await workers(page))[0]?.messages.length ?? 0)
		.toBeGreaterThan(0);
	await page
		.locator(".evolver")
		.getByRole("button", { name: label(language, "common.stop"), exact: true })
		.click();
	await waitForStatus(page, language, "evolve.status.stopped");
	const stopped = (await workers(page))[0];
	expect(stopped.terminated).toBe(true);
	expect(stopped.messages.some((message) => message.type === "done")).toBe(
		false,
	);
	const count = stopped.messages.length;
	await page.waitForTimeout(100);
	expect((await workers(page))[0].messages).toHaveLength(count);
	await expect(page.locator(".evolver .best-fitness")).not.toHaveText("—");
	await configure(page, language);
	await start(page, language);
	await waitForStatus(page, language, "evolve.status.done");
	expect(await workers(page)).toHaveLength(2);
});

test("unchanged best disables apply without creating an empty child", async ({
	page,
}, info) => {
	const { language } = info.project.metadata;
	await installWorkerProbe(page);
	await open(page, language);
	await configure(page, language, 2, 10, 11);
	await start(page, language);
	await waitForStatus(page, language, "evolve.status.done");
	await expect(
		page.locator(".evolver").getByRole("button", {
			name: label(language, "evolve.loadBest"),
			exact: true,
		}),
	).toBeDisabled();
	await expect(page.locator(".evolver .apply-bar")).toContainText(
		label(language, "evolve.noChanges"),
	);
	const steps = await page.evaluate(() => {
		const raw = localStorage.getItem("strandbeest-editor-v1");
		return raw ? (JSON.parse(raw) as { steps: unknown[] }).steps.length : 0;
	});
	expect(steps).toBe(0);
});

test("worker initialization failure is visible and recoverable", async ({
	page,
}, info) => {
	const { language } = info.project.metadata;
	await installWorkerProbe(page);
	await open(page, language);
	await page.route("**/beest_kernel_bg-*.wasm", (route) => route.abort());
	await configure(page, language);
	await start(page, language);
	await expect(page.locator(".evolver").getByRole("alert")).toContainText(
		label(language, "evolve.failed").split("{message}")[0],
	);
	await waitForStatus(page, language, "evolve.status.error");
	expect((await workers(page))[0].terminated).toBe(true);
	await page.unroute("**/beest_kernel_bg-*.wasm");
	await start(page, language);
	await waitForStatus(page, language, "evolve.status.done");
	expect((await workers(page))[1].terminated).toBe(true);
});

test("navigation terminates the worker and ignores stale completion", async ({
	page,
}, info) => {
	const { language } = info.project.metadata;
	await installWorkerProbe(page);
	await open(page, language);
	await configure(page, language, 80, 60);
	await start(page, language);
	await expect
		.poll(async () => (await workers(page))[0]?.messages.length ?? 0)
		.toBeGreaterThan(0);
	await expect(
		page.locator(".evolver").getByRole("button", {
			name: label(language, "evolve.start"),
			exact: true,
		}),
	).toHaveCount(0);
	await page
		.locator("nav")
		.getByRole("button", { name: label(language, "nav.design"), exact: true })
		.click();
	expect((await workers(page))[0].terminated).toBe(true);
	await page
		.locator("nav")
		.getByRole("button", { name: label(language, "nav.evolve"), exact: true })
		.click();
	await waitForStatus(page, language, "evolve.status.idle");
	await expect(
		page.locator(".evolver .fitness-panel .chart-empty"),
	).toBeVisible();
	expect(await workers(page)).toHaveLength(1);
	const count = (await workers(page))[0].messages.length;
	await page.waitForTimeout(100);
	expect((await workers(page))[0].messages).toHaveLength(count);
});

test("GA and atlas remain distinct, responsive and readable in both themes", async ({
	page,
}, info) => {
	const { language } = info.project.metadata;
	await installWorkerProbe(page);
	await open(page, language);
	await expect(page.locator(".evolver .run-status")).toHaveText(
		label(language, "evolve.status.idle"),
	);
	await expect(page.locator(".atlas-workspace .qd-container")).toBeVisible();
	await expect(page.locator(".evolver .candidate-card")).toHaveCount(0);
	await expect(page.locator(".evolver .constraint-result")).toHaveCount(0);
	for (const width of [375, 768, 1024, 1440]) {
		await page.setViewportSize({ width, height: 1000 });
		expect(
			await page.evaluate(
				() => document.documentElement.scrollWidth <= innerWidth,
			),
			`No horizontal document overflow at ${width}px`,
		).toBe(true);
		await expect(page.locator(".evolver .run-control")).toBeVisible();
		await page.screenshot({
			path: info.outputPath(`evolution-${language}-${width}-dark.png`),
			fullPage: true,
		});
	}
	await page
		.getByRole("button", { name: label(language, "app.theme.light") })
		.click();
	await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
	await page.screenshot({
		path: info.outputPath(`evolution-${language}-1440-light.png`),
		fullPage: true,
	});
});
