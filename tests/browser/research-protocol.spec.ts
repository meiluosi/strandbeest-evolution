import { readFileSync } from "node:fs";
import {
	type APIRequestContext,
	expect,
	type Page,
	test,
} from "@playwright/test";

const catalogs = Object.fromEntries(
	["zh", "en"].map((language) => [
		language,
		JSON.parse(readFileSync(`apps/web-demo/src/i18n/${language}.json`, "utf8")),
	]),
);
const api = process.env.BEEST_E2E_API_URL ?? "http://127.0.0.1:8787";
let browserErrors: string[];

function label(language: string, key: string): string {
	const value = catalogs[language][key];
	if (typeof value !== "string") throw new Error(`Missing message: ${key}`);
	return value;
}

async function open(page: Page, language: string) {
	await page.goto(`/?lang=${language}&tab=research&view=protocol`);
	await expect(page.locator("#app")).toHaveAttribute(
		"data-kernel",
		"rust-wasm/0.1.0",
	);
	await expect(page.locator(".research-workspace")).toBeVisible();
}

async function createRun(
	request: APIRequestContext,
	id: string,
	name: string,
	lengthOffset = 0,
) {
	const design = JSON.parse(
		readFileSync("schemas/examples/design-jansen-small-6leg.json", "utf8"),
	);
	design.id = id;
	design.name = name;
	design.walker.legs = 2;
	design.linkage.params.a += lengthOffset;
	const saved = await request.post(`${api}/designs`, { data: design });
	expect(saved.ok(), await saved.text()).toBeTruthy();
	const started = await request.post(`${api}/runs`, {
		data: {
			design,
			ensemble: false,
			overrides: { run: { revolutions: 0.2, settle: 0.1, frame_rate: 0 } },
		},
	});
	expect(started.ok(), await started.text()).toBeTruthy();
	const { job_id } = await started.json();
	let result: { id: string; design_id: string } | undefined;
	await expect
		.poll(
			async () => {
				const response = await request.get(`${api}/jobs/${job_id}`);
				expect(response.ok()).toBeTruthy();
				const job = await response.json();
				if (job.status === "failed") throw new Error(job.error);
				result = job.result;
				return job.status;
			},
			{ timeout: 90_000 },
		)
		.toBe("done");
	if (!result) throw new Error("Run completed without a result");
	return result;
}

test.beforeEach(async ({ page }) => {
	browserErrors = [];
	await page.addInitScript((url) => {
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

test("immutable protocols, independent trials, real snapshots and deep links", async ({
	page,
	request,
}, info) => {
	const { language, mode } = info.project.metadata;
	test.skip(mode !== "live", "Harness writes require the live API");
	const t = (key: string) => label(language, key);
	const suffix = language === "zh" ? "01" : "02";
	const runs = await Promise.all([
		createRun(
			request,
			`01K000000000000000000010${suffix}`,
			`HF04 train ${language}`,
		),
		createRun(
			request,
			`01K000000000000000000011${suffix}`,
			`HF04 test ${language}`,
			0.5,
		),
	]);
	await open(page, language);
	await page
		.getByRole("button", { name: t("harness.createExperiment"), exact: true })
		.click();
	const submit = page.getByRole("button", {
		name: t("harness.createAndFreeze"),
		exact: true,
	});
	await submit.click();
	await expect(page.locator(".protocol-content")).toHaveCount(0);
	await page
		.getByLabel(t("harness.experimentTitle"), { exact: true })
		.fill(`HF04 protocol ${language}`);
	await page
		.getByLabel(t("harness.question"), { exact: true })
		.fill("Can an independent trial preserve the protocol and its provenance?");
	const created = page.waitForResponse(
		(response) =>
			response.url().endsWith("/api/harness/v1/experiments") &&
			response.request().method() === "POST" &&
			response.status() === 201,
	);
	await submit.click();
	const creation = await (await created).json();
	const first = creation.revision;
	expect(first.revision).toBe(1);
	expect(first.trials).toHaveLength(1);
	await expect(page.locator(".revision-stamp")).toContainText("R1");
	await expect(page.locator(".revision-stamp small")).toHaveText(first.id);
	await expect(page.locator(".reference-grid")).toContainText(
		first.inputs.design.id,
	);
	await expect(page.locator(".reference-grid")).toContainText(
		first.inputs.design.digest,
	);
	await expect(page.locator("tbody tr")).toContainText(
		t("harness.initialTrial"),
	);
	await expect(page.locator(".lineage-list")).toContainText("uses_input");
	await expect(page).toHaveURL(
		new RegExp(`experiment=${creation.experiment.id}&revision=${first.id}`),
	);
	await page.reload();
	await expect(page.locator(".revision-stamp small")).toHaveText(first.id);
	await expect(page.locator(".protocol-overview h3")).toHaveText(
		`HF04 protocol ${language}`,
	);
	await page
		.getByRole("button", { name: t("harness.validateProtocol"), exact: true })
		.click();
	await expect(page.getByRole("status")).toContainText(
		t("harness.protocolValid"),
	);

	await page
		.getByRole("button", { name: t("harness.deriveRevision"), exact: true })
		.click();
	await page
		.getByLabel(t("harness.trialPurpose"), { exact: true })
		.selectOption("independent_replication");
	const derived = page.waitForResponse(
		(response) =>
			response
				.url()
				.endsWith(
					`/api/harness/v1/experiments/${creation.experiment.id}/revisions`,
				) && response.status() === 201,
	);
	await page
		.getByRole("button", { name: t("harness.freezeRevision"), exact: true })
		.click();
	const second = await (await derived).json();
	expect(second.revision).toBe(2);
	expect(second.base_id).toBe(first.id);
	expect(second.trials[0].id).not.toBe(first.trials[0].id);
	expect(second.trials[0].purpose).toBe("independent_replication");
	await expect(page.locator(".revision-stamp")).toContainText("R2");
	await expect(page.locator(".revision-diff")).toContainText(
		t("harness.diff.trials"),
	);
	await expect(page.locator(".revision-diff")).not.toContainText(
		t("harness.diff.design"),
	);
	await expect(page.locator(".revision-diff")).not.toContainText(
		t("harness.diff.conditions"),
	);
	await expect(page.locator(".lineage-list")).toContainText("derived_from");

	await page
		.getByRole("button", { name: t("harness.createSnapshot"), exact: true })
		.click();
	for (const run of runs)
		await page.locator(`.run-picker input[value="${run.id}"]`).check();
	await page.getByLabel(t("harness.channels"), { exact: true }).fill("t, psi");
	await expect(page.locator(".group-splits select")).toHaveCount(2);
	await expect(page.locator(".group-splits select").first()).toHaveValue(
		"train",
	);
	await expect(page.locator(".group-splits select").last()).toHaveValue("test");
	const snapshotResponse = page.waitForResponse(
		(response) =>
			response.url().endsWith("/api/harness/v1/dataset-snapshots") &&
			response.status() === 201,
	);
	await page
		.getByRole("button", { name: t("harness.freezeSnapshot"), exact: true })
		.click();
	const snapshot = await (await snapshotResponse).json();
	expect(snapshot.sources).toHaveLength(2);
	expect(snapshot.observation.channels).toEqual(["t", "psi"]);
	expect(snapshot.total_samples).toBe(
		snapshot.sources.reduce(
			(total: number, source: { sample_count: number }) =>
				total + source.sample_count,
			0,
		),
	);
	expect(
		new Set(
			snapshot.sources.map((source: { group_id: string }) => source.group_id),
		).size,
	).toBe(2);
	await expect(page.locator(".snapshot-identity")).toContainText(snapshot.id);
	await expect(page.locator(".split-card")).toHaveCount(2);
	await expect(page.locator(".snapshot-count")).toContainText(
		String(snapshot.total_samples),
	);
	await page
		.getByRole("button", { name: t("harness.validateSnapshot"), exact: true })
		.click();
	await expect(page.getByRole("status")).toContainText(
		t("harness.snapshotValid"),
	);
	await page
		.getByRole("button", { name: t("harness.deriveRevision"), exact: true })
		.click();
	await page.getByLabel(t("harness.attachSnapshot"), { exact: true }).check();
	const attached = page.waitForResponse(
		(response) =>
			response
				.url()
				.endsWith(
					`/api/harness/v1/experiments/${creation.experiment.id}/revisions`,
				) && response.status() === 201,
	);
	await page
		.getByRole("button", { name: t("harness.freezeRevision"), exact: true })
		.click();
	const third = await (await attached).json();
	expect(third.inputs.dataset_snapshot.id).toBe(snapshot.id);
	await expect(page.locator(".revision-stamp")).toContainText("R3");
	await expect(page.locator(".reference-grid")).toContainText(snapshot.id);
	await expect(page.locator(".revision-diff")).toContainText(
		t("harness.diff.snapshot"),
	);
	await expect(page.locator(".lineage-list")).toContainText(
		`dataset_snapshot · ${snapshot.id}`,
	);
	await page.reload();
	await expect(page.locator(".revision-stamp small")).toHaveText(third.id);
	await expect(page.locator(".snapshot-identity")).toContainText(snapshot.id);

	for (const width of [375, 768, 1024, 1440]) {
		await page.setViewportSize({ width, height: 1000 });
		await expect
			.poll(
				() =>
					page.evaluate(
						() => document.documentElement.scrollWidth <= innerWidth,
					),
				`No horizontal document overflow at ${width}px`,
			)
			.toBe(true);
		await page.screenshot({
			path: info.outputPath(`protocol-${language}-${width}-dark.png`),
			fullPage: true,
		});
	}
	await page.getByRole("button", { name: t("app.theme.light") }).click();
	await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
	await expect(page.locator(".protocol-content")).toBeVisible();
	const other = language === "zh" ? "en" : "zh";
	await page
		.getByRole("combobox", { name: t("app.language") })
		.selectOption(other);
	await expect(
		page.getByRole("button", {
			name: label(other, "harness.deriveRevision"),
			exact: true,
		}),
	).toBeVisible();
});

test("static research stays read-only without Harness writes", async ({
	page,
}, info) => {
	const { language, mode } = info.project.metadata;
	test.skip(mode !== "static", "Static-only read-only contract");
	const t = (key: string) => label(language, key);
	const writes: string[] = [];
	page.on("request", (request) => {
		if (request.url().includes("/api/harness/") && request.method() !== "GET")
			writes.push(`${request.method()} ${request.url()}`);
	});
	await open(page, language);
	await expect(page.locator(".research-empty")).toContainText(
		t("harness.staticWriteDisabled"),
	);
	await expect(
		page.getByRole("button", { name: t("harness.createExperiment") }),
	).toHaveCount(0);
	await expect(page.locator(".create-form, #snapshot-form")).toHaveCount(0);
	await page
		.getByRole("button", { name: t("research.openDesign"), exact: true })
		.click();
	await expect(page.locator(".design-workspace")).toBeVisible();
	expect(writes).toEqual([]);
});
