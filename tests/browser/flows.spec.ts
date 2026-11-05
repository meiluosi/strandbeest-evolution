import { readFileSync } from "node:fs";
import { readFile, writeFile } from "node:fs/promises";
import { expect, type Locator, type Page, test } from "@playwright/test";

const catalogs = Object.fromEntries(
	["zh", "en"].map((lang) => [
		lang,
		JSON.parse(readFileSync(`apps/web-demo/src/i18n/${lang}.json`, "utf8")),
	]),
);
const sampleAtlas = JSON.parse(
	readFileSync("apps/web-demo/src/sample-atlas.json", "utf8"),
);
const api = process.env.BEEST_E2E_API_URL ?? "http://127.0.0.1:8787";
// Fixed Chromium SVG edge rasterization alternates by <= 0.026543 in pixelmatch
// YIQ distance. Zero differing pixels are allowed above this narrow color bound.
// Other component screenshots retain the global threshold of zero.
const ATLAS_COLOR_THRESHOLD = 0.03;
let pageErrors: string[];

function label(language: string, key: string): string {
	const value = catalogs[language][key];
	if (typeof value !== "string") throw new Error(`Missing message: ${key}`);
	return value;
}

async function open(page: Page, language: string, tab = "design") {
	await page.goto(`/?lang=${language}&tab=${tab}`);
	// Mounting alone is insufficient: the application must use the Rust WASM kernel.
	await expect(page.locator("#app")).toHaveAttribute(
		"data-kernel",
		"rust-wasm/0.1.0",
	);
	await expect(page.locator("header h1")).toBeVisible();
}

async function openAtlas(page: Page, language: string) {
	await page
		.locator("nav")
		.getByRole("button", { name: label(language, "nav.evolve"), exact: true })
		.click();
	const atlas = page.locator(".atlas-workspace .qd-container");
	await expect(atlas).toBeVisible();
	return atlas;
}

async function openDesignPanel(page: Page, language: string, key: string) {
	const summary = page
		.locator("details > summary")
		.filter({ hasText: label(language, key) });
	if ((await summary.locator("..").getAttribute("open")) === null)
		await summary.click();
}

async function downloadJson(page: Page, button: Locator) {
	const pending = page.waitForEvent("download");
	await button.click();
	const download = await pending;
	const path = await download.path();
	expect(path).not.toBeNull();
	return JSON.parse(await readFile(path as string, "utf8"));
}

async function pauseAtStart(player: Locator, language: string) {
	await expect(player.locator(".views canvas")).toBeVisible();
	// The range's input handler pauses the replay and seeks to an exact timestamp.
	await player.locator('input[type="range"]').press("End");
	await player.locator('input[type="range"]').press("Home");
	await expect(
		player.getByRole("button", {
			name: label(language, "common.play"),
			exact: true,
		}),
	).toBeVisible();
	await expect(player.locator('input[type="range"]')).toHaveValue("0");
	// Following a moving body changes the camera offset before the first seek.
	// Wait for that seek to render, then use the actual UI preset for a fixed view.
	await player.page().evaluate(
		() =>
			new Promise<void>((resolve) => {
				requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
			}),
	);
	await player
		.getByRole("button", {
			name: label(language, "viewport.cam.iso"),
			exact: true,
		})
		.click();
}

test.beforeEach(async ({ page }) => {
	pageErrors = [];
	page.on("pageerror", (error) =>
		pageErrors.push(error.stack ?? error.message),
	);
	await page.addInitScript((url) => {
		localStorage.clear();
		localStorage.setItem("strandbeest-api", url);
	}, api);
});

test.afterEach(async () => {
	expect(pageErrors, "Unexpected browser exceptions").toEqual([]);
});

test("measurement import preserves provenance, calibration applies to a real run", async ({
	page,
	request,
}, info) => {
	const { language, mode } = info.project.metadata;
	test.skip(mode !== "live", "Calibration requires the live API");
	const t = (key: string) => label(language, key);
	const design = JSON.parse(
		readFileSync("schemas/examples/design-jansen-small-6leg.json", "utf8"),
	);
	design.walker.legs = 2;
	await open(page, language);
	await openDesignPanel(page, language, "design.file");
	await page.getByLabel(t("design.importJson"), { exact: true }).setInputFiles({
		name: "calibration-design.json",
		mimeType: "application/json",
		buffer: Buffer.from(JSON.stringify(design)),
	});
	await expect(page.locator(".project-context strong")).toHaveAttribute(
		"title",
		design.id,
	);
	const loaded = await downloadJson(
		page,
		page
			.locator(".project-actions")
			.getByRole("button", { name: t("design.downloadJson"), exact: true }),
	);
	expect(loaded).toEqual(design);
	const started = await request.post(`${api}/runs`, {
		data: {
			design,
			ensemble: false,
			overrides: { run: { revolutions: 1.1, settle: 0.1, frame_rate: 0 } },
		},
	});
	expect(started.ok()).toBeTruthy();
	const { job_id } = await started.json();
	let source: any;
	await expect
		.poll(
			async () => {
				const job = await (await request.get(`${api}/jobs/${job_id}`)).json();
				if (job.status === "failed") throw new Error(job.error);
				source = job.result;
				return job.status;
			},
			{ timeout: 60_000 },
		)
		.toBe("done");
	const channels = await (
		await request.get(`${api}/runs/${source.id}/series?max_points=600`)
	).json();
	const measurement = {
		schema_version: 2,
		id:
			language === "zh"
				? "01K00000000000000000001001"
				: "01K00000000000000000001002",
		name: `browser-synthetic-${language}`,
		design_id: design.id,
		synthetic: true,
		conditions: { kind: "motor_no_wind", omega_rad_s: 2.0 },
		channels: {
			t: channels.t,
			psi: channels.psi,
			torque: channels.torque,
			x: channels.x,
		},
		provenance: {
			source: "simulator",
			raw_file: "native-browser-fixture.json",
			calibration: {
				generator: "real API synthetic fixture",
				source_run_id: source.id,
				units: { torque: "N·m" },
			},
		},
	};
	await page.getByRole("button", { name: t("nav.lab"), exact: true }).click();
	await page.locator('input[type="file"][accept=".csv,.json"]').setInputFiles({
		name: "measurement.json",
		mimeType: "application/json",
		buffer: Buffer.from(JSON.stringify(measurement)),
	});
	await expect(
		page.getByText(t("lab.import.preserveDocument"), { exact: true }),
	).toBeVisible();
	await expect(
		page.getByLabel(t("lab.import.synthetic"), { exact: true }),
	).toBeChecked();
	await expect(
		page.getByLabel(t("lab.import.synthetic"), { exact: true }),
	).toBeDisabled();
	const saved = page.waitForResponse(
		(response) =>
			response.url().endsWith("/measurements") &&
			response.request().method() === "POST",
	);
	await page
		.getByRole("button", { name: t("lab.import.save"), exact: true })
		.click();
	expect((await saved).request().postDataJSON()).toEqual(measurement);
	expect(
		await (await request.get(`${api}/measurements/${measurement.id}`)).json(),
	).toEqual(measurement);
	await page
		.getByRole("button", { name: t("lab.calib.run"), exact: true })
		.click();
	const apply = page.getByRole("button", {
		name: t("lab.calib.apply"),
		exact: true,
	});
	await expect(apply).toBeEnabled({ timeout: 150_000 });
	await expect(
		page.getByText(t("lab.calib.syntheticWarning"), { exact: true }),
	).toBeVisible();
	const submitted = page.waitForRequest(
		(req) => req.url().endsWith("/runs") && req.method() === "POST",
	);
	await apply.click();
	const appliedPayload = (await submitted).postDataJSON();
	expect(appliedPayload.profile_id).toBeTruthy();
	await expect(
		page.getByText(t("lab.calib.applied"), { exact: true }),
	).toBeVisible({ timeout: 60_000 });
	const rid = await page
		.getByRole("combobox", { name: t("lab.compare.simRun"), exact: true })
		.inputValue();
	const actual = await (await request.get(`${api}/runs/${rid}`)).json();
	const profile = await (
		await request.get(`${api}/profiles/${appliedPayload.profile_id}`)
	).json();
	expect(actual.provenance.calibration_profile_id).toBe(profile.id);
	expect(actual.scenario.solver.contact_stiffness).toBe(
		profile.parameters.contact_stiffness,
	);
	expect(profile.provenance.measurement_ids).toEqual([measurement.id]);
	expect(profile.provenance.synthetic).toBe(true);
	await info.attach("applied-calibration", {
		body: JSON.stringify({ profile, run: actual }),
		contentType: "application/json",
	});
});

test("manufacturing previews real parts and downloads a verifiable local pack", async ({
	page,
	request,
}, info) => {
	const { language, mode } = info.project.metadata;
	test.skip(mode !== "live", "Manufacturing requires the live API");
	const t = (key: string) => label(language, key);
	const design = JSON.parse(
		readFileSync("schemas/examples/design-jansen-small-6leg.json", "utf8"),
	);
	await open(page, language);
	await openDesignPanel(page, language, "design.file");
	await page.getByLabel(t("design.importJson"), { exact: true }).setInputFiles({
		name: "manufacturing-design.json",
		mimeType: "application/json",
		buffer: Buffer.from(JSON.stringify(design)),
	});
	await expect(page.locator(".project-context strong")).toHaveAttribute(
		"title",
		design.id,
	);
	await page.getByRole("button", { name: t("nav.fab"), exact: true }).click();
	const clearance = page.getByRole("spinbutton", {
		name: t("fab.clearance"),
		exact: true,
	});
	await clearance.fill("0.35");
	await clearance.press("Tab");
	design.manufacturing.clearance_mm = 0.35;
	const exported = page.waitForResponse(
		(response) =>
			response.url().endsWith("/exports") &&
			response.request().method() === "POST",
	);
	await page
		.getByRole("button", { name: t("fab.checkExport"), exact: true })
		.click();
	const response = await exported;
	expect(response.ok()).toBeTruthy();
	expect(response.request().postDataJSON()).toEqual(design);
	const pack = await response.json();
	const manifest = await (
		await request.get(`${api}/exports/${pack.export_id}/parts`)
	).json();
	expect(pack.parts).toBe(Object.keys(manifest.parts).length);
	expect(manifest.crank_phase_deg).toHaveLength(design.walker.legs);
	expect(
		pack.checks.filter((check: { status: string }) => check.status === "fail"),
	).toEqual([]);
	await expect(page.locator(".host canvas")).toBeVisible();
	const partLoaded = page.waitForResponse((result) =>
		result.url().endsWith(`/exports/${pack.export_id}/stl/frame_plate`),
	);
	await page
		.getByRole("button", { name: t("viewer3d.singlePart"), exact: true })
		.click();
	expect((await partLoaded).ok()).toBeTruthy();
	await expect(
		page.getByText(t("viewer3d.loadingParts"), { exact: true }),
	).toHaveCount(0);
	await expect(page.locator(".host canvas")).toBeVisible();
	const downloaded = page.waitForEvent("download");
	await page
		.getByRole("link", { name: t("fab.download"), exact: true })
		.click();
	const archive = await downloaded;
	expect(archive.suggestedFilename()).toBe(`${design.name}-print-pack.zip`);
	await archive.saveAs(info.outputPath("manufacturing-pack.zip"));
	await writeFile(
		info.outputPath("manufacturing-input.json"),
		JSON.stringify({ design, pack, manifest }),
	);
	// The host runner independently opens this exact download and checks every mesh.
	await info.attach("manufacturing-pack", {
		path: info.outputPath("manufacturing-pack.zip"),
		contentType: "application/zip",
	});
});

test("atlas slices, locale switching and invalid import @visual", async ({
	page,
}, info) => {
	const { language, mode } = info.project.metadata;
	const t = (key: string) => label(language, key);
	await open(page, language);
	const atlas = await openAtlas(page, language);
	await expect(atlas.locator("select")).toHaveValue("1");
	await expect(atlas.locator("select option")).toHaveCount(6);
	await atlas
		.getByRole("button", { name: t("map_elites.showBest"), exact: true })
		.click();
	await expect(atlas.locator(".select-card")).toContainText("1, 1, 1");
	await page.mouse.move(0, 0);
	const visualProbe = process.env.BEEST_E2E_VISUAL_PROBE;
	if (visualProbe === "1" || visualProbe === "color") {
		// Explicit negative control: this must fail and produce a real pixel diff.
		await page.addStyleTag({
			content: ".qd-stats-bar { background: #ff00ff !important; }",
		});
	}
	if (visualProbe === "cell-shift") {
		await atlas
			.locator('.cell-group rect[stroke="#ffffff"]')
			.evaluate((element) => {
				const rect = element as SVGRectElement;
				const scale = rect.getScreenCTM()?.a;
				if (!scale) throw new Error("Selected cell has no screen transform");
				rect.setAttribute(
					"x",
					String(Number(rect.getAttribute("x")) + 1 / scale),
				);
			});
	}
	if (visualProbe === "label") {
		await atlas
			.locator(".axis-title")
			.first()
			.evaluate((element) => {
				element.textContent += ".";
			});
	}
	await expect(atlas).toHaveScreenshot("atlas-best.png", {
		timeout: 60_000,
		threshold: ATLAS_COLOR_THRESHOLD,
	});

	await atlas.locator("select").selectOption("2");
	await expect(atlas.locator(".select-card")).toHaveCount(0);
	const otherCell = sampleAtlas.cells.find(
		(cell: { cell: number[] }) => cell.cell[2] !== 1,
	);
	expect(otherCell).toBeTruthy();
	await atlas.locator("select").selectOption(String(otherCell.cell[2]));
	const coordinates = otherCell.cell.join(", ");
	await atlas
		.getByRole("button", {
			name: t("map_elites.cellCoordinates").replace(
				"{coordinates}",
				coordinates,
			),
			exact: true,
		})
		.click();
	await expect(atlas.locator(".select-card")).toContainText(coordinates);

	const otherLanguage = language === "zh" ? "en" : "zh";
	await page.locator("header .lang select").selectOption(otherLanguage);
	await expect(atlas.locator("h3")).toHaveText(
		label(otherLanguage, "map_elites.title"),
	);
	await expect(
		atlas.getByRole("button", {
			name: label(otherLanguage, "map_elites.loadViewer"),
			exact: true,
		}),
	).toBeVisible();
	await page.locator("header .lang select").selectOption(language);
	await atlas
		.getByRole("button", { name: t("map_elites.showBest"), exact: true })
		.click();

	const originalStats = await atlas.locator(".qd-stats-bar").textContent();
	await atlas.locator('input[type="file"]').setInputFiles({
		name: "broken.json",
		mimeType: "application/json",
		buffer: Buffer.from("{broken"),
	});
	await expect(atlas.locator(".notice.error")).toHaveText(
		t("map_elites.invalidJson"),
	);
	await expect(atlas.locator(".qd-stats-bar")).toHaveText(originalStats ?? "");
	await page.mouse.move(0, 0);
	await expect(atlas).toHaveScreenshot("atlas-invalid-import.png", {
		timeout: 60_000,
		threshold: ATLAS_COLOR_THRESHOLD,
	});
	await atlas.locator('input[type="file"]').setInputFiles({
		name: "wrong-contract.json",
		mimeType: "application/json",
		buffer: Buffer.from('{"kind":"design"}'),
	});
	await expect(atlas.locator(".notice.error")).toContainText(
		t("map_elites.invalidAtlas").split("{field}")[0],
	);
	await expect(atlas.locator(".qd-stats-bar")).toHaveText(originalStats ?? "");
	await expect(
		atlas.getByRole("button", { name: t("map_elites.runQd"), exact: true }),
	).toHaveCount(mode === "static" ? 0 : 1);
});

test("evolves the current design through the real API and loads its elite", async ({
	page,
}, info) => {
	test.skip(
		info.project.metadata.mode !== "live",
		"Evolution requires the API",
	);
	const { language } = info.project.metadata;
	const t = (key: string) => label(language, key);
	await open(page, language);
	await openDesignPanel(page, language, "design.configuration");
	const name = `browser-current-${language}`;
	await page.locator('.schema-field[title="name"] input').fill(name);
	await page.locator('.schema-field[title="name"] input').blur();
	await page.locator('.schema-field[title="walker.legs"] input').fill("4");
	await page.locator('.schema-field[title="walker.legs"] input').blur();
	const atlas = await openAtlas(page, language);
	const posted = page.waitForRequest(
		(request) =>
			request.method() === "POST" && request.url() === `${api}/evolve/qd`,
	);
	await atlas
		.getByRole("button", { name: t("map_elites.runQd"), exact: true })
		.click();
	const payload = (await posted).postDataJSON();
	expect(payload.design.name).toBe(name);
	expect(payload.design.walker.legs).toBe(4);
	expect(payload.evals).toBe(200);
	await expect(
		atlas.getByRole("button", { name: t("map_elites.runQd"), exact: true }),
	).toBeEnabled({ timeout: 150_000 });
	await expect(atlas.locator(".notice.error")).toHaveCount(0);
	const evolved = await downloadJson(
		page,
		atlas.getByRole("button", {
			name: t("map_elites.exportAtlas"),
			exact: true,
		}),
	);
	expect(evolved.base_design_id).toBe(payload.design.id);
	expect(evolved.evals).toBe(200);
	expect(evolved.cells.length).toBeGreaterThan(0);
	const best = evolved.cells.reduce(
		(a: { fitness: number }, b: { fitness: number }) =>
			a.fitness >= b.fitness ? a : b,
	);
	await atlas
		.getByRole("button", { name: t("map_elites.showBest"), exact: true })
		.click();
	await atlas
		.getByRole("button", { name: t("map_elites.loadViewer"), exact: true })
		.click();
	const loaded = await downloadJson(
		page,
		page
			.locator(".project-actions")
			.getByRole("button", { name: t("design.downloadJson"), exact: true }),
	);
	expect(loaded).toEqual(best.design);
	await info.attach("evolved-atlas", {
		body: JSON.stringify(evolved),
		contentType: "application/json",
	});
});

test("saves a design, simulates it and replays real telemetry", async ({
	page,
}, info) => {
	test.skip(
		info.project.metadata.mode !== "live",
		"Persistence requires the API",
	);
	const { language } = info.project.metadata;
	const t = (key: string) => label(language, key);
	await open(page, language);
	await openDesignPanel(page, language, "design.configuration");
	const name = `browser-saved-${language}`;
	await page.locator('.schema-field[title="name"] input').fill(name);
	await page.locator('.schema-field[title="name"] input').blur();
	await page
		.locator('.schema-field[title="walker.body_mass_kg"] input')
		.fill("0.42");
	await page.locator('.schema-field[title="walker.body_mass_kg"] input').blur();
	await openDesignPanel(page, language, "design.file");
	const saveRequest = page.waitForRequest(
		(request) =>
			request.method() === "POST" && request.url() === `${api}/designs`,
	);
	const saveResponse = page.waitForResponse(
		(response) =>
			response.request().method() === "POST" &&
			response.url() === `${api}/designs`,
	);
	await page
		.getByRole("button", { name: t("design.saveBackend"), exact: true })
		.click();
	const saved = (await saveRequest).postDataJSON();
	expect(saved.walker.body_mass_kg).toBe(0.42);
	const response = await saveResponse;
	expect(response.ok()).toBe(true);
	expect((await response.json()).id).toBe(saved.id);
	const persisted = await page.request.get(`${api}/designs/${saved.id}`);
	expect(persisted.ok()).toBe(true);
	expect(await persisted.json()).toEqual(saved);
	await expect(page.locator(".notice.info").first()).toHaveText(
		t("design.saved").replace("{name}", name),
	);
	await page
		.locator("nav")
		.getByRole("button", { name: t("nav.sim"), exact: true })
		.click();
	const player = page.locator(".card").filter({
		has: page.getByRole("heading", { name: t("scenes.title"), exact: true }),
	});
	const runRequest = page.waitForRequest(
		(request) => request.method() === "POST" && request.url() === `${api}/runs`,
	);
	const telemetry = page.waitForResponse(
		(response) =>
			/\/runs\/[^/]+\/(telemetry|replay)/.test(response.url()) && response.ok(),
	);
	await player
		.getByRole("button", { name: t("scenes.run"), exact: true })
		.click();
	expect((await runRequest).postDataJSON().design).toEqual(saved);
	await telemetry;
	await pauseAtStart(player, language);
	await expect(player.locator(".summary")).not.toBeEmpty();
	await expect(player.locator(".notice.error")).toHaveCount(0);
	await info.attach("real-arrow-replay", {
		body: await player.locator(".views").screenshot(),
		contentType: "image/png",
	});
	await player.locator('input[type="range"]').press("ArrowRight");
	await expect(player.locator('input[type="range"]')).not.toHaveValue("0");
	await info.attach("saved-design", {
		body: JSON.stringify(saved),
		contentType: "application/json",
	});
});

test("backend failures are visible and preserve the atlas", async ({
	page,
}, info) => {
	test.skip(
		info.project.metadata.mode !== "live",
		"Static mode has no backend controls",
	);
	const { language } = info.project.metadata;
	const t = (key: string) => label(language, key);
	await open(page, language);
	const atlas = await openAtlas(page, language);
	const before = await atlas.locator(".qd-stats-bar").textContent();
	// Only the failure tests inject HTTP faults; success paths use the actual API.
	await page.route(`${api}/evolve/qd`, (route) =>
		route.fulfill({
			status: 503,
			contentType: "application/json",
			body: '{"detail":"browser-test-unavailable"}',
		}),
	);
	await atlas
		.getByRole("button", { name: t("map_elites.runQd"), exact: true })
		.click();
	await expect(atlas.locator(".notice.error")).toContainText("503");
	await expect(atlas.locator(".qd-stats-bar")).toHaveText(before ?? "");
	await expect(
		atlas.getByRole("button", { name: t("map_elites.runQd"), exact: true }),
	).toBeEnabled();
	await page
		.locator("nav")
		.getByRole("button", { name: t("nav.sim"), exact: true })
		.click();
	const player = page.locator(".card").filter({
		has: page.getByRole("heading", { name: t("scenes.title"), exact: true }),
	});
	await page.route(`${api}/runs`, (route) =>
		route.fulfill({
			status: 503,
			contentType: "application/json",
			body: '{"detail":"browser-test-unavailable"}',
		}),
	);
	await player
		.getByRole("button", { name: t("scenes.run"), exact: true })
		.click();
	await expect(player.locator(".notice.error")).toContainText("503");
	await expect(
		player.getByRole("button", { name: t("scenes.run"), exact: true }),
	).toBeEnabled();
	await expect(player.locator(".views canvas")).toHaveCount(0);
});

test("static mode plays the baked scene without backend requests @visual", async ({
	page,
}, info) => {
	test.skip(
		info.project.metadata.mode !== "static",
		"Baked replays belong to the static build",
	);
	const { language } = info.project.metadata;
	const t = (key: string) => label(language, key);
	const backendRequests: string[] = [];
	page.on("request", (request) => {
		if (request.url().startsWith(api)) backendRequests.push(request.url());
	});
	await open(page, language, "sim");
	const player = page.locator(".card").filter({
		has: page.getByRole("heading", { name: t("scenes.title"), exact: true }),
	});
	await pauseAtStart(player, language);
	await expect(player).toContainText(t("scenes.recorded"));
	await expect(
		player.getByRole("button", { name: t("scenes.run"), exact: true }),
	).toHaveCount(0);
	await expect(page.locator(".api")).toHaveCount(0);
	await page.mouse.move(0, 0);
	await expect(player.locator(".views")).toHaveScreenshot("baked-replay.png", {
		timeout: 60_000,
	});
	await expect(player.locator(".cards")).toHaveScreenshot("baked-metrics.png", {
		timeout: 60_000,
	});
	await expect(player.locator(".energy")).toHaveScreenshot("baked-energy.png", {
		timeout: 60_000,
	});
	await player.locator('input[type="range"]').press("ArrowRight");
	await expect(player.locator('input[type="range"]')).not.toHaveValue("0");
	expect(backendRequests).toEqual([]);
});

test("absorbed energy stays signed and missing invariants stay unavailable", async ({
	page,
}, info) => {
	test.skip(
		info.project.metadata.mode !== "static",
		"Recorded replay display uses the static build",
	);
	const { language } = info.project.metadata;
	const t = (key: string) => label(language, key);
	const fixture = JSON.parse(
		readFileSync("contracts/sim-run/signed-energy-v3.json", "utf8"),
	);
	let missing = false;
	await page.route("**/gallery/flat.json", async (route) => {
		const replay = structuredClone(fixture.replay);
		if (missing) {
			// Deliberately corrupt only the displayed evidence, not the physical
			// fixture; missing measurements must never appear as zero/passing.
			for (const key of [
				"max_loop_violation",
				"max_penetration",
				"energy_residual_share",
			])
				delete replay.metrics[key];
		}
		await route.fulfill({ json: replay });
	});
	await open(page, language, "sim");
	const player = page.locator(".card").filter({
		has: page.getByRole("heading", { name: t("scenes.title"), exact: true }),
	});
	await pauseAtStart(player, language);
	const energy = player.locator(".energy");
	await expect(energy).toContainText(t("energy.absorbed"));
	await expect(energy.locator("svg")).toHaveCount(0);
	const metrics = fixture.replay.metrics;
	const input = metrics.energy_in_per_rev;
	const values = [
		["energy.netWork", input],
		["energy.contact", input * metrics.energy_contact_share],
		["energy.loops", input * metrics.energy_loops_share],
		["energy.friction", input * metrics.energy_friction_share],
		[
			"energy.stored",
			input *
				(1 -
					metrics.energy_contact_share -
					metrics.energy_loops_share -
					metrics.energy_friction_share),
		],
	] as const;
	for (const [key, joules] of values)
		await expect(
			energy.locator(".signed-energy tr").filter({ hasText: t(key) }),
		).toContainText(`${(joules * 1000).toFixed(2)} mJ`);
	await expect(
		energy.locator("tr").filter({ hasText: t("invariants.residual") }),
	).toHaveClass(/(?:^|\s)ok(?:\s|$)/);
	await energy.screenshot({ path: info.outputPath("signed-energy.png") });
	missing = true;
	await page.reload();
	await pauseAtStart(player, language);
	for (const key of [
		"invariants.loop",
		"invariants.penetration",
		"invariants.residual",
	]) {
		const row = energy.locator("tr").filter({ hasText: t(key) });
		await expect(row).toHaveClass(/(?:^|\s)na(?:\s|$)/);
		await expect(row.locator("td").nth(1)).toHaveText("–");
	}
});
