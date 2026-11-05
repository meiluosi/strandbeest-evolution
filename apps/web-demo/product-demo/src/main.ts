import {
	Activity,
	ArrowLeftRight,
	ArrowRight,
	ArrowUpFromLine,
	Box,
	Check,
	ChevronDown,
	CircleGauge,
	createIcons,
	Dna,
	Download,
	DraftingCompass,
	Expand,
	Footprints,
	Gauge,
	History,
	Info,
	Languages,
	Layers3,
	Moon,
	MoreHorizontal,
	MoveHorizontal,
	Pause,
	Play,
	Redo2,
	RotateCcw,
	Save,
	Settings2,
	Share2,
	ShieldCheck,
	Sparkles,
	Sun,
	Undo2,
	Waypoints,
	Wind,
	X,
	Zap,
} from "lucide";
import "@fontsource/manrope/400.css";
import "@fontsource/manrope/500.css";
import "@fontsource/manrope/600.css";
import "@fontsource/manrope/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/600.css";
import "./styles.css";
import { getLocale, setLocale, t } from "./i18n";
import {
	DEFAULT_PARAMS,
	dragParams,
	LINKS,
	metrics,
	PARAM_GROUPS,
	type Params,
	type Point,
	type Pose,
	solve,
	svgPoint,
	trace,
} from "./kinematics";

const iconSet = {
	Activity,
	ArrowLeftRight,
	ArrowRight,
	ArrowUpFromLine,
	Box,
	Check,
	ChevronDown,
	CircleGauge,
	Dna,
	Download,
	DraftingCompass,
	Expand,
	Footprints,
	Gauge,
	History,
	Info,
	Languages,
	Layers3,
	Moon,
	MoreHorizontal,
	MoveHorizontal,
	Pause,
	Play,
	Redo2,
	RotateCcw,
	Save,
	Settings2,
	Share2,
	ShieldCheck,
	Sparkles,
	Sun,
	Undo2,
	Waypoints,
	Wind,
	X,
	Zap,
};
const refreshIcons = () =>
	createIcons({ icons: iconSet, attrs: { "stroke-width": 1.7 } });
const icon = (name: string, cls = "") =>
	`<i data-lucide="${name}" class="icon ${cls}"></i>`;
const app = document.querySelector<HTMLDivElement>("#app")!;
const reducedMotion = window.matchMedia(
	"(prefers-reduced-motion: reduce)",
).matches;

type Page = "design" | "evolve" | "sim";
type Theme = "light" | "dark";
const state = {
	page: "design" as Page,
	theme: "light" as Theme,
	params: { ...DEFAULT_PARAMS },
	theta: 0.3,
	playing: !reducedMotion,
	speed: 1,
	legs: 6,
	ghosts: true,
	truss: true,
	pathFocus: false,
	inspector: "links" as "links" | "body" | "drive",
	expanded: false,
	saved: true,
	history: [] as Params[],
	future: [] as Params[],
	evolveRunning: false,
	generation: 0,
	selectedCandidate: 0,
	simScene: "flat",
	simPlaying: !reducedMotion,
	simTime: 0,
	simSpeed: 1,
	simCamera: "perspective",
	compare: false,
	overlays: { forces: true, trails: true, com: true },
};
let main: HTMLElement;
let toastTimer = 0;
let evolveTimer = 0;
let dragStart: Params | null = null;
let sliderStart: Params | null = null;

function toast(message: string, kind: "ok" | "info" = "ok") {
	const el = document.querySelector<HTMLDivElement>("#toast")!;
	el.innerHTML = `${icon(kind === "ok" ? "check" : "info")}<span>${message}</span>`;
	el.className = `toast show ${kind}`;
	refreshIcons();
	window.clearTimeout(toastTimer);
	toastTimer = window.setTimeout(() => {
		el.className = "toast";
	}, 2600);
}

function shell() {
	app.innerHTML = `
    <div class="app-shell">
      <header class="project-bar">
        <div class="brand">${icon("waypoints")}<div><b>Strandbeest <span>Studio</span></b><small>${t("brand.subtitle")}</small></div></div>
        <div class="project-context">
          <span class="project-kicker">${t("project.current")}</span>
          <button class="project-name" data-action="rename">${t("project.name")} ${icon("chevron-down")}</button>
          <span class="save-state" id="save-state"><span></span>${t("save.saved")}</span>
        </div>
        <div class="project-actions">
          <div class="history-actions">
            <button class="icon-btn" data-action="undo" aria-label="${t("action.undo")}" title="${t("action.undo")}">${icon("undo-2")}</button>
            <button class="icon-btn" data-action="redo" aria-label="${t("action.redo")}" title="${t("action.redo")}">${icon("redo-2")}</button>
          </div>
          <button class="button quiet save-button" data-action="save">${icon("save")}<span>${t("action.save")}</span></button>
          <button class="button quiet" data-action="share">${icon("share-2")}<span>${t("action.share")}</span></button>
          <button class="button quiet" data-action="export">${icon("download")}<span>${t("action.export")}</span></button>
          <button class="icon-btn" data-action="language" aria-label="${t("action.language")}" title="${t("action.language")}">${icon("languages")}</button>
          <button class="icon-btn theme-toggle" data-action="theme" aria-label="${t("action.theme")}">${icon(state.theme === "light" ? "moon" : "sun")}</button>
        </div>
      </header>
      <aside class="sidebar">
        <div class="nav-label">${t("workspace.label")}</div>
        <nav aria-label="${t("workspace.label")}">
          ${navItem("design", "drafting-compass", t("nav.design"), t("nav.designSub"))}
          ${navItem("evolve", "dna", t("nav.evolve"), t("nav.evolveSub"))}
          ${navItem("sim", "activity", t("nav.sim"), t("nav.simSub"))}
        </nav>
        <div class="sidebar-spacer"></div>
        <div class="demo-note"><span class="pulse-dot"></span><div><b>${t("demo.note")}</b><small>${t("demo.noteSub")}</small></div></div>
        <button class="sidebar-settings" data-action="settings">${icon("settings-2")}<span>${t("settings.label")}</span></button>
      </aside>
      <main id="workspace" tabindex="-1"></main>
    </div>
    <div id="toast" class="toast" role="status" aria-live="polite"></div>`;
	main = document.querySelector<HTMLElement>("#workspace")!;
	document.querySelectorAll<HTMLElement>("[data-page]").forEach((el) => {
		el.addEventListener("click", () => navigate(el.dataset.page as Page));
	});
	document.querySelectorAll<HTMLElement>("[data-action]").forEach((el) => {
		el.addEventListener("click", () => globalAction(el.dataset.action!));
	});
	refreshIcons();
}

function navItem(page: Page, iconName: string, label: string, sub: string) {
	return `<button class="nav-item" data-page="${page}" aria-label="${label}">${icon(iconName)}<span><b>${label}</b><small>${sub}</small></span><span class="nav-indicator"></span></button>`;
}

function navigate(page: Page) {
	state.page = page;
	document.querySelectorAll("[data-page]").forEach((el) => {
		el.classList.toggle("active", (el as HTMLElement).dataset.page === page);
		if ((el as HTMLElement).dataset.page === page)
			el.setAttribute("aria-current", "page");
		else el.removeAttribute("aria-current");
	});
	window.clearInterval(evolveTimer);
	state.evolveRunning = false;
	if (page === "design") renderDesign();
	if (page === "evolve") renderEvolve();
	if (page === "sim") renderSim();
	main.focus({ preventScroll: true });
}

function globalAction(action: string) {
	if (action === "theme") {
		state.theme = state.theme === "light" ? "dark" : "light";
		document.documentElement.dataset.theme = state.theme;
		const button = document.querySelector<HTMLButtonElement>(".theme-toggle")!;
		button.innerHTML = icon(state.theme === "light" ? "moon" : "sun");
		refreshIcons();
		return;
	}
	if (action === "language") {
		setLocale(getLocale() === "zh" ? "en" : "zh");
		shell();
		navigate(state.page);
		return;
	}
	if (action === "undo") {
		const previous = state.history.pop();
		if (!previous) return toast(t("toast.earliest"), "info");
		state.future.push({ ...state.params });
		state.params = previous;
		state.saved = false;
		if (state.page === "design") renderDesign();
		updateSaveState();
		return;
	}
	if (action === "redo") {
		const next = state.future.pop();
		if (!next) return toast(t("toast.noRedo"), "info");
		state.history.push({ ...state.params });
		state.params = next;
		state.saved = false;
		if (state.page === "design") renderDesign();
		updateSaveState();
		return;
	}
	if (action === "save") {
		state.saved = true;
		updateSaveState();
		toast(t("toast.saved"));
		return;
	}
	if (action === "share") {
		const url = `${location.origin}${location.pathname}#design=jansen-demo`;
		navigator.clipboard?.writeText(url).catch(() => undefined);
		toast(t("toast.shared"));
		return;
	}
	if (action === "export") {
		const blob = new Blob(
			[
				JSON.stringify(
					{ name: "jansen-demo", linkage: state.params, legs: state.legs },
					null,
					2,
				),
			],
			{ type: "application/json" },
		);
		const link = document.createElement("a");
		link.href = URL.createObjectURL(blob);
		link.download = "jansen-demo.json";
		link.click();
		URL.revokeObjectURL(link.href);
		toast(t("toast.exported"));
		return;
	}
	if (action === "rename") return toast(t("toast.rename"), "info");
	if (action === "settings") return toast(t("toast.settings"), "info");
}

function updateSaveState() {
	const el = document.querySelector<HTMLSpanElement>("#save-state");
	if (el)
		el.innerHTML = `<span></span>${state.saved ? t("save.saved") : t("save.dirty")}`;
	el?.classList.toggle("dirty", !state.saved);
}

function remember(previous: Params) {
	state.history.push({ ...previous });
	if (state.history.length > 40) state.history.shift();
	state.future = [];
	state.saved = false;
	updateSaveState();
}

function workspaceHeader(
	eyebrow: string,
	title: string,
	description: string,
	actions = "",
) {
	return `<div class="workspace-header"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p>${description}</p></div><div class="workspace-actions">${actions}</div></div>`;
}

function renderDesign() {
	const m = metrics(state.params);
	main.scrollTop = 0;
	main.innerHTML = `
    <section class="workspace design-workspace">
      ${workspaceHeader(
				t("design.eyebrow"),
				t("design.title"),
				t("design.description"),
				`
        <button class="button quiet" id="reset-design">${icon("rotate-ccw")}${t("design.reset")}</button>
        <button class="button primary" id="to-sim">${t("design.toSim")}${icon("arrow-right")}</button>`,
			)}
      <div class="design-grid">
        <section class="mechanism-panel">
          <div class="panel-toolbar">
            <div class="segmented"><button id="mechanism-view" data-view="mechanism" class="${state.pathFocus ? "" : "active"}">${t("design.mechanism")}</button><button id="path-focus" data-view="path" class="${state.pathFocus ? "active" : ""}">${t("design.path")}</button></div>
            <div class="view-options">
              <label><input type="checkbox" id="ghost-toggle" ${state.ghosts ? "checked" : ""}/><span>${t("design.ghosts")}</span></label>
              <label><input type="checkbox" id="truss-toggle" ${state.truss ? "checked" : ""}/><span>${t("design.truss")}</span></label>
              <button class="icon-btn" id="fit-view" aria-label="${t("design.fit")}" title="${t("design.fit")}">${icon("expand")}</button>
            </div>
          </div>
          <div class="mechanism-canvas ${state.pathFocus ? "path-emphasis" : ""}" id="mechanism-canvas">
            <div class="canvas-meta"><span class="topology-badge">${t("design.topology")}</span><span>${t("design.dof")}</span></div>
            <div class="angle-readout"><small>${t("design.angle")}</small><b id="angle-value">17°</b></div>
            ${mechanismSvg()}
            <div class="canvas-legend"><span><i class="legend-line orange"></i>${t("design.crankLegend")}</span><span><i class="legend-line green"></i>${t("design.stanceLegend")}</span><span><i class="legend-dot"></i>${t("design.jointLegend")}</span></div>
          </div>
          <div class="playback-bar">
            <button class="play-button" id="design-play" aria-label="${t(state.playing ? "design.pause" : "design.play")}">${icon(state.playing ? "pause" : "play")}</button>
            <div class="phase-track"><div class="phase-labels"><span>${t("design.stance")}</span><span>${t("design.swing")}</span></div><input id="phase-slider" type="range" min="0" max="360" value="${(state.theta * 180) / Math.PI}" aria-label="${t("design.angle")}"/></div>
            <label class="speed-control">${t("design.speed")}<select id="design-speed"><option value="0.5" ${state.speed === 0.5 ? "selected" : ""}>0.5×</option><option value="1" ${state.speed === 1 ? "selected" : ""}>1×</option><option value="2" ${state.speed === 2 ? "selected" : ""}>2×</option></select></label>
          </div>
        </section>
        <aside class="inspector">
          <div class="inspector-tabs" role="tablist">
            <button role="tab" data-inspector="links" aria-selected="${state.inspector === "links"}" class="${state.inspector === "links" ? "active" : ""}">${t("design.links")}</button>
            <button role="tab" data-inspector="body" aria-selected="${state.inspector === "body"}" class="${state.inspector === "body" ? "active" : ""}">${t("design.body")}</button>
            <button role="tab" data-inspector="drive" aria-selected="${state.inspector === "drive"}" class="${state.inspector === "drive" ? "active" : ""}">${t("design.drive")}</button>
          </div>
          <div id="inspector-content">${inspectorContent()}</div>
        </aside>
      </div>
      <section class="metric-strip" aria-label="${t("design.metrics")}">
        ${metricCard(t("metric.duty"), m ? `${Math.round(m.duty * 100)}%` : "—", t("metric.dutyNote"), "footprints")}
        ${metricCard(t("metric.lift"), m ? m.lift.toFixed(1) : "—", t("metric.liftNote"), "arrow-up-from-line")}
        ${metricCard(t("metric.stroke"), m ? m.stroke.toFixed(1) : "—", t("metric.strokeNote"), "move-horizontal")}
        <div class="geometry-status ${m ? "valid" : "invalid"}">${icon(m ? "shield-check" : "info")}<div><b>${t(m ? "geometry.valid" : "geometry.invalid")}</b><small>${t(m ? "geometry.validNote" : "geometry.invalidNote")}</small></div></div>
      </section>
    </section>`;
	bindDesign();
	updateDesignDrawing();
	refreshIcons();
}

function metricCard(
	label: string,
	value: string,
	note: string,
	iconName: string,
) {
	return `<div class="metric"><span class="metric-icon">${icon(iconName)}</span><div><small>${label}</small><b>${value}</b><span>${note}</span></div></div>`;
}

function inspectorContent() {
	if (state.inspector === "body") {
		return `<div class="inspector-section"><div class="section-title"><div><h2>${t("body.title")}</h2><p>${t("body.description")}</p></div></div>
      <label class="field-label">${t("body.legs")}</label><div class="stepper"><button id="legs-minus" aria-label="−">−</button><b>${state.legs}</b><button id="legs-plus" aria-label="+">＋</button></div>
      <div class="phase-visual">${Array.from({ length: state.legs }, (_, i) => `<span style="--i:${i};--n:${state.legs}"></span>`).join("")}</div>
      <p class="field-hint">${t("body.phaseHint", { legs: state.legs, angle: (360 / state.legs).toFixed(0) })}</p>
      <label class="field-label" for="body-length">${t("body.length")} <span>mm</span></label><input class="text-input" id="body-length" type="number" value="240" min="120" max="400"/>
      <label class="field-label" for="body-mass">${t("body.mass")} <span>${t("body.assumption")}</span></label><input class="text-input" id="body-mass" type="number" value="0.35" step="0.05" min="0"/>
      <div class="inline-note">${icon("info")}${t("body.note")}</div></div>`;
	}
	if (state.inspector === "drive") {
		return `<div class="inspector-section"><div class="section-title"><div><h2>${t("drive.title")}</h2><p>${t("drive.description")}</p></div></div>
      <div class="drive-options"><div class="drive-card active">${icon("zap")}<b>${t("drive.motor")}</b><small>${t("drive.motorNote")}</small></div><button class="drive-card" id="wind-drive">${icon("wind")}<b>${t("drive.wind")}</b><small>${t("drive.windNote")}</small></button></div>
      <label class="field-label" for="motor-speed">${t("drive.speed")} <span>rad/s</span></label><input class="text-input" id="motor-speed" type="number" value="2.0" step="0.1" min="0.2" max="6"/>
      <label class="field-label" for="gear-ratio">${t("drive.ratio")}</label><select class="text-input" id="gear-ratio"><option>1 : 1</option><option>1 : 2</option><option>1 : 4</option></select>
      <div class="inline-note">${icon("info")}${t("drive.note")}</div></div>`;
	}
	return `<div class="inspector-section"><div class="section-title"><div><h2>${t("links.title")}</h2><p>${t("links.description")}</p></div><span class="count-badge">13</span></div>
    <div class="parameter-scroll">${PARAM_GROUPS.map((group, groupIndex) => `<section class="param-group"><div class="param-group-title"><b>${t(group.title)}</b><small>${t(group.hint)}</small></div>${group.items.map(([key, label], index) => paramSlider(key, t(label), groupIndex === 1 && index >= (state.expanded ? 999 : 5))).join("")}</section>`).join("")}</div>
    <button class="expand-params" id="expand-params">${t(state.expanded ? "links.collapse" : "links.expand")}${icon("chevron-down", state.expanded ? "rotated" : "")}</button></div>`;
}

function paramSlider(key: string, label: string, hidden: boolean) {
	const value = state.params[key]!;
	const min = Math.max(2, value * 0.45);
	const max = value * 1.55;
	return `<div class="param-row ${hidden ? "param-hidden" : ""}" data-param-row="${key}"><div class="param-label"><label for="param-${key}"><span class="param-key">${key}</span>${label}</label><div class="number-wrap"><input id="param-${key}-number" data-number="${key}" type="number" value="${value.toFixed(1)}" step="0.1" aria-label="${t("links.value", { label })}"/><span>mm</span></div></div><input id="param-${key}" data-param="${key}" type="range" min="${min}" max="${max}" step="0.1" value="${value}" style="--fill:${((value - min) / (max - min)) * 100}%"/></div>`;
}

function mechanismSvg() {
	return `<svg id="mechanism-svg" viewBox="-58 -105 158 200" role="img" aria-label="${t("design.svgLabel")}">
    <defs><pattern id="micro-grid" width="8" height="8" patternUnits="userSpaceOnUse"><path d="M 8 0 L 0 0 0 8" fill="none" stroke="var(--grid-line)" stroke-width="0.22"/></pattern><filter id="soft-shadow"><feDropShadow dx="0" dy="1" stdDeviation="0.8" flood-opacity="0.14"/></filter></defs>
    <rect x="-60" y="-110" width="170" height="150" fill="url(#micro-grid)"/>
    <g id="ground"><line x1="-50" x2="92" y1="76" y2="76" class="ground-line"/>${Array.from({ length: 22 }, (_, i) => `<line x1="${-48 + i * 6.5}" y1="76" x2="${-51 + i * 6.5}" y2="80" class="ground-tick"/>`).join("")}</g>
    <path id="foot-path-shadow" class="foot-path-shadow"/><path id="foot-path" class="foot-path"/><path id="stance-path" class="stance-path"/>
    <g id="ghost-legs"></g><g id="trusses"></g><g id="main-links"></g><g id="main-joints"></g>
  </svg>`;
}

function updateDesignDrawing() {
	if (state.page !== "design" || !document.querySelector("#mechanism-svg"))
		return;
	const path = trace(state.params);
	const footPath = path.length
		? path.map((p, i) => `${i ? "L" : "M"}${svgPoint(p)}`).join(" ") + " Z"
		: "";
	setAttr("#foot-path", "d", footPath);
	setAttr("#foot-path-shadow", "d", footPath);
	if (path.length) {
		const low = Math.min(...path.map((p) => p.y));
		const stance = path
			.map((p, i) => ({ p, next: path[(i + 1) % path.length]! }))
			.filter(({ p, next }) => p.y <= low + 2 && next.y <= low + 2);
		setAttr(
			"#stance-path",
			"d",
			stance
				.map(({ p, next }) => `M${svgPoint(p)}L${svgPoint(next)}`)
				.join(" "),
		);
		const groundY = -low + 2;
		document.querySelectorAll(".ground-line,.ground-tick").forEach((el) => {
			if (el.classList.contains("ground-line")) {
				el.setAttribute("y1", `${groundY}`);
				el.setAttribute("y2", `${groundY}`);
			} else {
				const x = Number(el.getAttribute("x1"));
				el.setAttribute("y1", `${groundY}`);
				el.setAttribute("x2", `${x - 3}`);
				el.setAttribute("y2", `${groundY + 4}`);
			}
		});
	}
	drawPose(state.theta);
}

function poseMarkup(pose: Pose, ghost = false) {
	const lines = LINKS.map(
		([a, b]) =>
			`<line x1="${pose[a]!.x}" y1="${-pose[a]!.y}" x2="${pose[b]!.x}" y2="${-pose[b]!.y}"/>`,
	).join("");
	const joints = ghost
		? ""
		: Object.entries(pose)
				.filter(([id]) => id !== "G")
				.map(
					([id, p]) =>
						`<g class="joint ${id === "F" ? "foot" : ""}" data-joint="${id}" transform="translate(${p.x} ${-p.y})"><circle class="joint-hit" r="5"/><circle class="joint-ring" r="${id === "F" ? 2.6 : 2.1}"/><circle class="joint-pin" r="0.65"/><text x="3.5" y="-3">${id}</text></g>`,
				)
				.join("");
	return lines + joints;
}

function drawPose(theta: number) {
	if (state.page !== "design") return;
	const pose = solve(state.params, theta);
	const links = document.querySelector<SVGGElement>("#main-links");
	const joints = document.querySelector<SVGGElement>("#main-joints");
	if (!links || !joints) return;
	if (!pose) {
		links.innerHTML = "";
		joints.innerHTML = "";
		return;
	}
	const markup = poseMarkup(pose);
	links.innerHTML = LINKS.map(
		([a, b]) =>
			`<line x1="${pose[a]!.x}" y1="${-pose[a]!.y}" x2="${pose[b]!.x}" y2="${-pose[b]!.y}" class="${a === "C" || b === "C" ? "crank-link" : ""}"/>`,
	).join("");
	joints.innerHTML = markup.slice(markup.indexOf('<g class="joint'));
	const truss = document.querySelector<SVGGElement>("#trusses")!;
	truss.innerHTML = state.truss
		? `<polygon points="${svgPoint(pose.G!)} ${svgPoint(pose.K!)} ${svgPoint(pose.L!)}"/><polygon points="${svgPoint(pose.M!)} ${svgPoint(pose.N!)} ${svgPoint(pose.F!)}"/>`
		: "";
	const ghosts = document.querySelector<SVGGElement>("#ghost-legs")!;
	ghosts.innerHTML = state.ghosts
		? Array.from({ length: state.legs - 1 }, (_, i) => {
				const p = solve(
					state.params,
					theta + ((i + 1) * Math.PI * 2) / state.legs,
				);
				return p ? `<g class="ghost-leg">${poseMarkup(p, true)}</g>` : "";
			}).join("")
		: "";
	const deg = Math.round(((((theta * 180) / Math.PI) % 360) + 360) % 360);
	const angle = document.querySelector("#angle-value");
	if (angle) angle.textContent = `${deg}°`;
	const slider = document.querySelector<HTMLInputElement>("#phase-slider");
	if (slider && document.activeElement !== slider && !dragStart)
		slider.value = `${deg}`;
}

function setAttr(selector: string, name: string, value: string) {
	document.querySelector(selector)?.setAttribute(name, value);
}

function bindDesign() {
	document.querySelector("#reset-design")?.addEventListener("click", () => {
		const previous = { ...state.params };
		state.params = { ...DEFAULT_PARAMS };
		remember(previous);
		renderDesign();
		toast(t("design.resetDone"));
	});
	document
		.querySelector("#to-sim")
		?.addEventListener("click", () => navigate("sim"));
	document.querySelector("#design-play")?.addEventListener("click", () => {
		state.playing = !state.playing;
		const button = document.querySelector<HTMLButtonElement>("#design-play")!;
		button.innerHTML = icon(state.playing ? "pause" : "play");
		button.setAttribute(
			"aria-label",
			t(state.playing ? "design.pause" : "design.play"),
		);
		refreshIcons();
	});
	document.querySelector("#design-speed")?.addEventListener("change", (e) => {
		state.speed = Number((e.target as HTMLSelectElement).value);
	});
	document.querySelector("#phase-slider")?.addEventListener("input", (e) => {
		state.playing = false;
		state.theta =
			(Number((e.target as HTMLInputElement).value) * Math.PI) / 180;
		drawPose(state.theta);
	});
	document.querySelector("#ghost-toggle")?.addEventListener("change", (e) => {
		state.ghosts = (e.target as HTMLInputElement).checked;
		drawPose(state.theta);
	});
	document.querySelector("#truss-toggle")?.addEventListener("change", (e) => {
		state.truss = (e.target as HTMLInputElement).checked;
		drawPose(state.theta);
	});
	document.querySelector("#fit-view")?.addEventListener("click", () => {
		const svg = document.querySelector("#mechanism-svg");
		svg?.classList.add("view-pulse");
		setTimeout(() => svg?.classList.remove("view-pulse"), 220);
	});
	document
		.querySelectorAll<HTMLButtonElement>("[data-view]")
		.forEach((button) =>
			button.addEventListener("click", () => {
				state.pathFocus = button.dataset.view === "path";
				document
					.querySelectorAll("[data-view]")
					.forEach((b) => b.classList.toggle("active", b === button));
				document
					.querySelector("#mechanism-canvas")
					?.classList.toggle("path-emphasis", state.pathFocus);
			}),
		);
	document
		.querySelectorAll<HTMLButtonElement>("[data-inspector]")
		.forEach((button) =>
			button.addEventListener("click", () => {
				state.inspector = button.dataset.inspector as typeof state.inspector;
				renderDesign();
			}),
		);
	document.querySelector("#expand-params")?.addEventListener("click", () => {
		state.expanded = !state.expanded;
		renderDesign();
	});
	bindParameters();
	bindBody();
	bindDragging();
}

function bindParameters() {
	document
		.querySelectorAll<HTMLInputElement>("[data-param]")
		.forEach((input) => {
			input.addEventListener("pointerdown", () => {
				sliderStart = { ...state.params };
			});
			input.addEventListener("focus", () => {
				sliderStart ??= { ...state.params };
			});
			input.addEventListener("input", () => {
				state.params[input.dataset.param!] = Number(input.value);
				input.style.setProperty(
					"--fill",
					`${((Number(input.value) - Number(input.min)) / (Number(input.max) - Number(input.min))) * 100}%`,
				);
				const number = document.querySelector<HTMLInputElement>(
					`[data-number="${input.dataset.param}"]`,
				);
				if (number) number.value = Number(input.value).toFixed(1);
				updateDesignDrawing();
				updateMetricValues();
			});
			input.addEventListener("change", () => {
				if (sliderStart) remember(sliderStart);
				sliderStart = null;
			});
		});
	document
		.querySelectorAll<HTMLInputElement>("[data-number]")
		.forEach((input) => {
			input.addEventListener("focus", () => {
				sliderStart = { ...state.params };
			});
			input.addEventListener("change", () => {
				const value = Number(input.value);
				if (!Number.isFinite(value) || value <= 0)
					return toast(t("links.invalid"), "info");
				state.params[input.dataset.number!] = value;
				if (sliderStart) remember(sliderStart);
				sliderStart = null;
				renderDesign();
			});
		});
}

function updateMetricValues() {
	const m = metrics(state.params);
	const values = document.querySelectorAll<HTMLElement>(".metric b");
	if (values.length >= 3) {
		values[0]!.textContent = m ? `${Math.round(m.duty * 100)}%` : "—";
		values[1]!.textContent = m ? m.lift.toFixed(1) : "—";
		values[2]!.textContent = m ? m.stroke.toFixed(1) : "—";
	}
	const status = document.querySelector<HTMLElement>(".geometry-status");
	if (status) {
		status.className = `geometry-status ${m ? "valid" : "invalid"}`;
		status.innerHTML = `${icon(m ? "shield-check" : "info")}<div><b>${t(m ? "geometry.valid" : "geometry.invalid")}</b><small>${t(m ? "geometry.validNote" : "geometry.invalidNote")}</small></div>`;
		refreshIcons();
	}
}

function bindBody() {
	document.querySelector("#legs-minus")?.addEventListener("click", () => {
		state.legs = Math.max(2, state.legs - 1);
		renderDesign();
	});
	document.querySelector("#legs-plus")?.addEventListener("click", () => {
		state.legs = Math.min(12, state.legs + 1);
		renderDesign();
	});
	document.querySelector("#wind-drive")?.addEventListener("click", () => {
		state.simScene = "wind";
		navigate("sim");
	});
	document
		.querySelectorAll<HTMLElement>(".text-input")
		.forEach((input) =>
			input.addEventListener("change", () => toast(t("design.updated"), "ok")),
		);
}

function bindDragging() {
	const svg = document.querySelector<SVGSVGElement>("#mechanism-svg")!;
	svg.addEventListener("pointerdown", (event) => {
		const joint = (event.target as Element).closest<SVGGElement>(
			"[data-joint]",
		);
		if (!joint) return;
		activeDragId = joint.dataset.joint ?? null;
		dragStart = { ...state.params };
		state.playing = false;
		svg.setPointerCapture(event.pointerId);
		svg.classList.add("dragging");
		event.preventDefault();
	});
	svg.addEventListener("pointermove", (event) => {
		if (!dragStart || !activeDragId) return;
		const matrix = svg.getScreenCTM();
		if (!matrix) return;
		const p = new DOMPoint(event.clientX, event.clientY).matrixTransform(
			matrix.inverse(),
		);
		state.params = dragParams(state.params, state.theta, activeDragId, {
			x: p.x,
			y: -p.y,
		});
		updateDesignDrawing();
		updateMetricValues();
	});
	const finish = () => {
		if (!dragStart) return;
		remember(dragStart);
		dragStart = null;
		activeDragId = null;
		svg.classList.remove("dragging");
		renderDesign();
	};
	svg.addEventListener("pointerup", finish);
	svg.addEventListener("pointercancel", finish);
}
let activeDragId: string | null = null;

let maxGenerations = 80;
let population = 60;

function renderEvolve() {
	const candidates = candidateData();
	main.scrollTop = 0;
	main.innerHTML = `<section class="workspace evolve-workspace">
    ${workspaceHeader(t("evolve.eyebrow"), t("evolve.title"), t("evolve.description"), `<button class="button primary" id="evolve-start">${icon(state.evolveRunning ? "pause" : "sparkles")}${t(state.evolveRunning ? "evolve.pause" : "evolve.start")}</button>`)}
    <div class="evolve-grid">
      <aside class="evolve-config panel"><div class="panel-heading"><span>${icon("settings-2")}</span><div><h2>${t("evolve.config")}</h2><p>${t("evolve.configNote")}</p></div></div>
        <label class="field-label">${t("evolve.objective")}</label><div class="objective-list"><button class="objective active"><b>${t("objective.stable")}</b><small>${t("objective.stableNote")}</small></button><button class="objective"><b>${t("objective.obstacle")}</b><small>${t("objective.obstacleNote")}</small></button><button class="objective"><b>${t("objective.efficiency")}</b><small>${t("objective.efficiencyNote")}</small></button></div>
        <div class="config-pair"><label>${t("evolve.population")}<input class="text-input" id="population" value="${population}" type="number" min="10" max="200"/></label><label>${t("evolve.generations")}<input class="text-input" id="max-generations" value="${maxGenerations}" type="number" min="10" max="200"/></label></div>
        <div class="constraint-box"><b>${icon("shield-check")}${t("evolve.guard")}</b><label><input type="checkbox" checked/>${t("constraint.assembly")}</label><label><input type="checkbox" checked/>${t("constraint.branch")}</label><label><input type="checkbox" checked/>${t("constraint.body")}</label></div>
        <div class="inline-note">${icon("info")}${t("evolve.note")}</div>
      </aside>
      <section class="candidate-area panel"><div class="panel-heading"><div><h2>${t("evolve.candidates")}</h2><p id="evolution-status">${t("evolve.readyStatus", { generation: state.generation })}</p></div><div class="live-badge ${state.evolveRunning ? "running" : ""}"><span></span>${state.evolveRunning ? "LIVE" : "READY"}</div></div>
        <div class="generation-progress"><div id="generation-bar" style="width:${(state.generation / maxGenerations) * 100}%"></div></div>
        <div class="candidate-grid">${candidates.map((c, i) => candidateCard(c, i)).join("")}</div>
        <div class="candidate-footer"><span>${icon("history")}${t("evolve.branchNote")}</span><button class="button primary" id="apply-candidate">${t("evolve.apply")}${icon("arrow-right")}</button></div>
      </section>
      <aside class="evidence-panel panel"><div class="panel-heading"><div><h2>${t("evolve.search")}</h2><p>${t("evolve.searchNote")}</p></div></div>
        <div class="fitness-chart">${fitnessSvg()}<div class="chart-legend"><span><i class="legend-line orange"></i>${t("evolve.bestLine")}</span><span><i class="legend-line blue"></i>${t("evolve.meanLine")}</span></div></div>
        <div class="search-stats"><div><small>${t("evolve.best")}</small><b id="best-fitness">0.684</b></div><div><small>${t("evolve.valid")}</small><b>92%</b></div><div><small>${t("evolve.mutation")}</small><b>0.06</b></div><div><small>${t("evolve.seed")}</small><b>42</b></div></div>
        <div class="diversity-map"><div class="section-caption">${t("evolve.atlas")} <span>${t("evolve.atlasCount")}</span></div><div class="atlas-grid">${Array.from({ length: 36 }, (_, i) => `<button class="atlas-cell level-${(i * 7 + 3) % 5}" aria-label="${t("evolve.atlasCell", { index: i + 1 })}"></button>`).join("")}</div><div class="atlas-axis"><span>${t("evolve.lowLift")}</span><span>${t("evolve.highLift")}</span></div></div>
      </aside>
    </div></section>`;
	bindEvolve();
	refreshIcons();
}

type Candidate = {
	name: string;
	fit: string;
	duty: number;
	lift: number;
	delta: number[];
};
function candidateData(): Candidate[] {
	return [
		{
			name: t("evolve.current"),
			fit: "0.642",
			duty: 43,
			lift: 22.5,
			delta: [],
		},
		{
			name: "A-17",
			fit: "0.684",
			duty: 47,
			lift: 23.8,
			delta: [2.1, -1.4, 0.8],
		},
		{
			name: "B-08",
			fit: "0.671",
			duty: 45,
			lift: 26.1,
			delta: [-1.2, 2.8, -1.0],
		},
		{
			name: "C-21",
			fit: "0.659",
			duty: 51,
			lift: 20.9,
			delta: [1.1, 0.7, -2.1],
		},
	];
}
function candidateCard(c: Candidate, index: number) {
	const params = { ...state.params };
	c.delta.forEach((delta, i) => {
		const key = ["b", "e", "m"][i]!;
		params[key] = params[key]! + delta;
	});
	const path = trace(params, 70);
	const d = path.length
		? path.map((p, i) => `${i ? "L" : "M"}${svgPoint(p)}`).join(" ") + " Z"
		: "";
	return `<button class="candidate-card ${state.selectedCandidate === index ? "selected" : ""}" data-candidate="${index}" aria-pressed="${state.selectedCandidate === index}"><div class="candidate-title"><span>${c.name}</span>${state.selectedCandidate === index ? icon("check") : ""}</div><svg viewBox="-45 -20 110 110"><path d="${d}" class="candidate-path"/><line x1="-42" x2="60" y1="78" y2="78" class="candidate-ground"/></svg><div class="candidate-score"><b>${c.fit}</b><small>${t("evolve.fitness")}</small></div><div class="candidate-metrics"><span>${t("evolve.duty", { value: c.duty })}</span><span>${t("evolve.lift", { value: c.lift })}</span></div></button>`;
}
function fitnessSvg() {
	const best = Array.from(
		{ length: 32 },
		(_, i) =>
			`${i * 9},${112 - 75 * (1 - Math.exp(-i / 9)) - Math.sin(i * 0.8) * 2}`,
	).join(" ");
	const mean = Array.from(
		{ length: 32 },
		(_, i) =>
			`${i * 9},${120 - 45 * (1 - Math.exp(-i / 8)) - Math.sin(i * 0.5) * 3}`,
	).join(" ");
	return `<svg viewBox="0 0 280 135" aria-label="${t("evolve.chartLabel")}"><g class="chart-grid"><line x1="0" x2="280" y1="30" y2="30"/><line x1="0" x2="280" y1="70" y2="70"/><line x1="0" x2="280" y1="110" y2="110"/></g><polyline points="${best}" class="best-line"/><polyline points="${mean}" class="mean-line"/><text x="0" y="132">0</text><text x="250" y="132">${t("evolve.generationAxis")}</text></svg>`;
}
function bindEvolve() {
	document
		.querySelectorAll<HTMLButtonElement>("[data-candidate]")
		.forEach((button) =>
			button.addEventListener("click", () => {
				state.selectedCandidate = Number(button.dataset.candidate);
				renderEvolve();
			}),
		);
	document.querySelector("#population")?.addEventListener("change", (event) => {
		population = Math.max(
			10,
			Math.min(200, Number((event.target as HTMLInputElement).value) || 60),
		);
	});
	document
		.querySelector("#max-generations")
		?.addEventListener("change", (event) => {
			maxGenerations = Math.max(
				10,
				Math.min(200, Number((event.target as HTMLInputElement).value) || 80),
			);
			state.generation = Math.min(state.generation, maxGenerations);
		});
	document.querySelector("#evolve-start")?.addEventListener("click", () => {
		if (state.evolveRunning) {
			state.evolveRunning = false;
			window.clearInterval(evolveTimer);
			renderEvolve();
			return;
		}
		if (state.generation >= maxGenerations) state.generation = 0;
		state.evolveRunning = true;
		renderEvolve();
		evolveTimer = window.setInterval(() => {
			state.generation = Math.min(maxGenerations, state.generation + 1);
			const status = document.querySelector("#evolution-status");
			if (status)
				status.textContent = t("evolve.runningStatus", {
					generation: state.generation,
					population,
				});
			const bar = document.querySelector<HTMLElement>("#generation-bar");
			if (bar)
				bar.style.width = `${(state.generation / maxGenerations) * 100}%`;
			const best = document.querySelector("#best-fitness");
			if (best)
				best.textContent = (
					0.642 +
					0.042 * (1 - Math.exp(-state.generation / 18))
				).toFixed(3);
			if (state.generation >= maxGenerations) {
				state.evolveRunning = false;
				window.clearInterval(evolveTimer);
				toast(t("evolve.complete", { count: maxGenerations }));
				renderEvolve();
			}
		}, 180);
	});
	document.querySelector("#apply-candidate")?.addEventListener("click", () => {
		const candidate = candidateData()[state.selectedCandidate]!;
		if (!candidate.delta.length) return toast(t("evolve.noApply"), "info");
		const previous = { ...state.params };
		(["b", "e", "m"] as const).forEach((key, i) => {
			state.params[key] = state.params[key]! + candidate.delta[i]!;
		});
		remember(previous);
		navigate("design");
		toast(t("evolve.applied", { name: candidate.name }));
	});
	document.querySelectorAll<HTMLButtonElement>(".objective").forEach((button) =>
		button.addEventListener("click", () => {
			document.querySelectorAll(".objective").forEach((b) => {
				b.classList.toggle("active", b === button);
				b.setAttribute("aria-pressed", String(b === button));
			});
		}),
	);
	document
		.querySelectorAll<HTMLButtonElement>(".atlas-cell")
		.forEach((button) =>
			button.addEventListener("click", () =>
				toast(
					t("evolve.atlasSelected", {
						name: button.getAttribute("aria-label") ?? "",
					}),
					"info",
				),
			),
		);
}

const SCENES = [
	{
		id: "flat",
		icon: "footprints",
		name: "scene.flat",
		note: "scene.flatNote",
		factor: 1,
	},
	{
		id: "slope",
		icon: "activity",
		name: "scene.slope",
		note: "scene.slopeNote",
		factor: 0.87,
	},
	{
		id: "step",
		icon: "layers-3",
		name: "scene.step",
		note: "scene.stepNote",
		factor: 0.72,
	},
	{
		id: "wind",
		icon: "wind",
		name: "scene.wind",
		note: "scene.windNote",
		factor: 0.79,
	},
	{
		id: "mars",
		icon: "circle-gauge",
		name: "scene.mars",
		note: "scene.marsNote",
		factor: 1.12,
	},
] as const;

function renderSim() {
	const scene = SCENES.find((s) => s.id === state.simScene)!;
	const m = metrics(state.params) ?? { width: 0, lift: 0, duty: 0, stroke: 0 };
	main.scrollTop = 0;
	main.innerHTML = `<section class="workspace sim-workspace">
    ${workspaceHeader(t("sim.eyebrow"), t("sim.title"), t("sim.description"), `<span class="evidence-badge">${icon("shield-check")}${t("sim.evidence")}</span><button class="button primary" id="rerun-sim">${icon("play")}${t("sim.rerun")}</button>`)}
    <div class="sim-grid">
      <aside class="scene-panel"><div class="side-heading">${t("sim.scenes")}<span>5</span></div><div class="scene-list">${SCENES.map((s) => `<button class="scene-item ${s.id === state.simScene ? "active" : ""}" data-scene="${s.id}" aria-pressed="${s.id === state.simScene}">${icon(s.icon)}<span><b>${t(s.name)}</b><small>${t(s.note)}</small></span></button>`).join("")}</div>
        <div class="run-config"><div class="side-heading">${t("sim.runConfig")}</div><label class="field-label">${t("sim.revolutions")}</label><select class="text-input"><option>${t("sim.revolutions2")}</option><option>${t("sim.revolutions4")}</option></select>${scene.id === "wind" ? `<label class="field-label">${t("sim.windSpeed")}</label><div class="unit-input"><input class="text-input" value="3.0" type="number" min="0" step="0.1"/><span>m/s</span></div>` : ""}<button class="button quiet full-width" id="advanced-sim">${icon("settings-2")}${t("sim.advanced")}</button></div>
      </aside>
      <section class="replay-panel">
        <div class="replay-toolbar"><div><span class="run-label">${t("sim.runLabel")}</span><b>${t(scene.name)}</b><small>${t("sim.designLabel", { legs: state.legs })}</small></div><div class="camera-switch"><button data-camera="perspective" class="${state.simCamera === "perspective" ? "active" : ""}">${t("sim.perspective")}</button><button data-camera="side" class="${state.simCamera === "side" ? "active" : ""}">${t("sim.side")}</button><button data-camera="top" class="${state.simCamera === "top" ? "active" : ""}">${t("sim.top")}</button></div></div>
        <div class="replay-stage ${state.compare ? "compare-mode" : ""}" id="replay-stage"><div class="demo-watermark">${t(state.compare ? "sim.compareWatermark" : "sim.watermark")}</div><svg id="sim-svg" viewBox="150 0 500 430" role="img" aria-label="${t("sim.svgLabel")}"><defs><linearGradient id="ground-fade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--ground-start)"/><stop offset="1" stop-color="var(--ground-end)"/></linearGradient><filter id="walker-shadow"><feDropShadow dx="0" dy="5" stdDeviation="4" flood-opacity="0.2"/></filter></defs><rect width="800" height="430" fill="var(--stage-bg)"/><path id="scene-ground" fill="url(#ground-fade)"/><g class="perspective-grid">${Array.from({ length: 13 }, (_, i) => `<line x1="${i * 70 - 40}" y1="430" x2="${350 + i * 9}" y2="240"/>`).join("")}${Array.from({ length: 6 }, (_, i) => `<line x1="0" x2="800" y1="${250 + i * i * 7}" y2="${250 + i * i * 7}"/>`).join("")}</g><g id="camera-world"><g id="wind-field"></g><g id="previous-walker" class="previous-walker"></g><g id="walker" filter="url(#walker-shadow)"></g><g id="trail-overlay"></g><g id="force-overlay"></g><g id="com-overlay"></g></g></svg>
          <div class="viewport-hud"><span>${icon("box")}${t("sim.camera")}</span><span>${t("sim.cameraHint")}</span></div><div class="sim-status"><span class="pulse-dot"></span><span id="sim-play-state">${t(state.simPlaying ? "sim.playing" : "sim.paused")}</span><b id="sim-time-label">${state.simTime.toFixed(2)} s</b></div>
        </div>
        <div class="timeline-panel"><div class="transport"><button class="play-button" id="sim-play" aria-label="${t(state.simPlaying ? "design.pause" : "design.play")}">${icon(state.simPlaying ? "pause" : "play")}</button><button class="icon-btn" id="sim-reset" aria-label="${t("sim.reset")}">${icon("rotate-ccw")}</button></div><div class="timeline-track"><div class="timeline-events"><span style="left:18%" data-seek="1.1">${t("sim.contact")}</span><span style="left:47%" data-seek="2.8">${t("sim.slip")}</span><span style="left:74%" data-seek="4.4">${t("sim.stable")}</span></div><input id="sim-timeline" type="range" min="0" max="6" step="0.01" value="${state.simTime}" aria-label="${t("sim.timeline")}"/><div class="timeline-labels"><span>0.0 s</span><span>2.0</span><span>4.0</span><span>6.0 s</span></div></div><select id="sim-speed" class="speed-select"><option value="0.5" ${state.simSpeed === 0.5 ? "selected" : ""}>0.5×</option><option value="1" ${state.simSpeed === 1 ? "selected" : ""}>1×</option><option value="2" ${state.simSpeed === 2 ? "selected" : ""}>2×</option></select></div>
        <div class="overlay-bar"><b>${t("sim.layers")}</b>${(["forces", "trails", "com"] as const).map((key) => `<label><input data-overlay="${key}" type="checkbox" ${state.overlays[key] ? "checked" : ""}/>${t(`overlay.${key}`)}</label>`).join("")}<label class="compare-toggle"><input id="compare-toggle" type="checkbox" ${state.compare ? "checked" : ""}/>${t("sim.compare")}</label></div>
      </section>
      <aside class="diagnostic-panel"><div class="side-heading">${t("sim.results")}<span class="result-ok">${t("sim.completed")}</span></div><div class="result-metrics"><div><small>${t("result.stride")}</small><b>${(m.stroke * 0.002 * scene.factor).toFixed(3)}<span>m</span></b><em>${scene.factor >= 1 ? "+4.2%" : "−8.6%"}</em></div><div><small>${t("result.speed")}</small><b>${(0.084 * scene.factor).toFixed(3)}<span>m/s</span></b><em>${t("result.demo")}</em></div><div><small>${t("result.torque")}</small><b>0.041<span>N·m</span></b><em>${t("result.torqueRange")}</em></div><div><small>${t("result.slip")}</small><b>3.2<span>%</span></b><em class="good">${t("result.slipGood")}</em></div></div>
        <div class="diagnosis-heading"><h3>${t("sim.diagnosis")}</h3><span>${t("sim.diagnosisCount")}</span></div><div class="diagnosis-list"><button data-seek="1.1"><span class="diag-icon ok">${icon("check")}</span><div><b>${t("diag.continuous")}</b><p>${t("diag.continuousNote", { legs: state.legs })}</p><small>1.10 s · ${t("diag.gait")}</small></div></button><button data-seek="2.8"><span class="diag-icon warn">${icon("info")}</span><div><b>${t("diag.slip")}</b><p>${t("diag.slipNote")}</p><small>2.80 s · ${t("diag.contact")}</small></div></button><button data-seek="4.4"><span class="diag-icon ok">${icon("shield-check")}</span><div><b>${t("diag.closed")}</b><p>${t("diag.closedNote")}</p><small>4.40 s · ${t("diag.audit")}</small></div></button></div>
        <div class="evidence-note">${icon("info")}<p>${t("sim.evidenceNote")}</p></div>
      </aside>
    </div></section>`;
	bindSim();
	drawSimulation();
	refreshIcons();
}

function drawSimulation() {
	if (state.page !== "sim") return;
	const walker = document.querySelector<SVGGElement>("#walker");
	if (!walker) return;
	const theta = state.simTime * Math.PI * 1.5;
	const bodyShift = Math.sin(theta * 0.5) * 5;
	const renderWalker = (params: Params, shift: number) => {
		const parts: string[] = [];
		for (let leg = 0; leg < state.legs; leg++) {
			const pose = solve(params, theta + (leg * Math.PI * 2) / state.legs);
			if (!pose) continue;
			const depth = leg % 2;
			const baseX = 270 + Math.floor(leg / 2) * 52 + depth * 28 + shift;
			const baseY = 145 + depth * 54 + Math.floor(leg / 2) * 3;
			const scale = 0.83;
			const map = (p: Point) => ({
				x: baseX + p.x * scale,
				y: baseY - p.y * scale,
			});
			parts.push(`<g opacity="${depth ? 0.58 : 1}">`);
			LINKS.forEach(([a, b]) => {
				const pa = map(pose[a]!);
				const pb = map(pose[b]!);
				parts.push(
					`<line x1="${pa.x}" y1="${pa.y}" x2="${pb.x}" y2="${pb.y}" class="walker-link ${a === "C" || b === "C" ? "walker-crank" : ""}"/>`,
				);
			});
			Object.entries(pose)
				.filter(([id]) => !["G", "P"].includes(id))
				.forEach(([id, p]) => {
					const sp = map(p);
					const stance = id === "F" && p.y < -58;
					parts.push(
						`<circle cx="${sp.x}" cy="${sp.y}" r="${id === "F" ? 4.5 : 3}" class="walker-joint ${id === "F" ? (stance ? "stance" : "swing") : ""}"/>`,
					);
				});
			parts.push("</g>");
		}
		parts.push(
			`<g class="torso"><path d="M${260 + shift} 145 L${450 + shift} 142 L${480 + shift} 173 L${280 + shift} 178Z"/><path d="M${278 + shift} 177 L${465 + shift} 174"/>${state.simScene === "wind" ? `<path d="M${360 + shift} 142 L${360 + shift} 35 L${438 + shift} 124Z" class="sail"/><line x1="${360 + shift}" y1="35" x2="${360 + shift}" y2="142"/>` : ""}</g>`,
		);
		return parts.join("");
	};
	walker.innerHTML = renderWalker(state.params, bodyShift);
	const previousParams = state.history.at(-1) ?? {
		...state.params,
		b: state.params.b! + 1.8,
		e: state.params.e! - 1.2,
		m: state.params.m! + 0.6,
	};
	const previous = document.querySelector<SVGGElement>("#previous-walker")!;
	previous.innerHTML = state.compare
		? renderWalker(previousParams, bodyShift - 12)
		: "";
	const groundPaths: Record<string, string> = {
		flat: "M0 240 L800 240 L800 430 L0 430Z",
		slope: "M0 265 L800 188 L800 430 L0 430Z",
		step: "M0 240 L505 240 L505 211 L800 211 L800 430 L0 430Z",
		wind: "M0 240 L800 240 L800 430 L0 430Z",
		mars: "M0 244 Q170 226 330 244 T800 232 L800 430 L0 430Z",
	};
	setAttr("#scene-ground", "d", groundPaths[state.simScene]!);
	const camera = document.querySelector<SVGGElement>("#camera-world")!;
	camera.setAttribute(
		"transform",
		state.simCamera === "top"
			? "translate(30 10) scale(1 .82)"
			: state.simCamera === "side"
				? "translate(0 20) scale(1 .94)"
				: "",
	);
	const trail = document.querySelector<SVGGElement>("#trail-overlay")!;
	trail.innerHTML = state.overlays.trails
		? trace(state.params, 36)
				.filter((p) => p.y < -54)
				.map(
					(p, i) =>
						`<circle cx="${270 + bodyShift + p.x * 0.83}" cy="${145 - p.y * 0.83}" r="${i % 3 === 0 ? 2.4 : 1.5}" class="trail-dot"/>`,
				)
				.join("")
		: "";
	const force = document.querySelector<SVGGElement>("#force-overlay")!;
	force.innerHTML = state.overlays.forces
		? Array.from(
				{ length: 4 },
				(_, i) =>
					`<g class="force-arrow" transform="translate(${330 + i * 50} ${332 + (i % 2) * 8})"><line x1="0" y1="0" x2="0" y2="-32"/><path d="M-4 -26 L0 -34 L4 -26"/></g>`,
			).join("")
		: "";
	const com = document.querySelector<SVGGElement>("#com-overlay")!;
	com.innerHTML = state.overlays.com
		? `<g class="com-marker"><circle cx="375" cy="158" r="6"/><line x1="375" y1="164" x2="375" y2="300"/><path d="M320 300 L410 296 L445 318 L345 322Z"/></g>`
		: "";
	const wind = document.querySelector<SVGGElement>("#wind-field")!;
	wind.innerHTML =
		state.simScene === "wind"
			? Array.from(
					{ length: 9 },
					(_, i) =>
						`<path d="M${-80 + ((state.simTime * 90 + i * 113) % 900)} ${65 + i * 22} h70" class="wind-line"/>`,
				).join("")
			: "";
	const timeline = document.querySelector<HTMLInputElement>("#sim-timeline");
	if (timeline && document.activeElement !== timeline)
		timeline.value = `${state.simTime}`;
	const timeLabel = document.querySelector("#sim-time-label");
	if (timeLabel) timeLabel.textContent = `${state.simTime.toFixed(2)} s`;
	const playState = document.querySelector("#sim-play-state");
	if (playState)
		playState.textContent = t(state.simPlaying ? "sim.playing" : "sim.paused");
	const playButton = document.querySelector<HTMLButtonElement>("#sim-play");
	if (playButton) {
		playButton.innerHTML = icon(state.simPlaying ? "pause" : "play");
		playButton.setAttribute(
			"aria-label",
			t(state.simPlaying ? "design.pause" : "design.play"),
		);
	}
	refreshIcons();
}

function bindSim() {
	document
		.querySelectorAll<HTMLButtonElement>("[data-scene]")
		.forEach((button) =>
			button.addEventListener("click", () => {
				state.simScene = button.dataset.scene!;
				state.simTime = 0;
				renderSim();
			}),
		);
	document.querySelector("#sim-play")?.addEventListener("click", () => {
		state.simPlaying = !state.simPlaying;
		renderSim();
	});
	document.querySelector("#sim-reset")?.addEventListener("click", () => {
		state.simTime = 0;
		state.simPlaying = false;
		renderSim();
	});
	document.querySelector("#sim-timeline")?.addEventListener("input", (e) => {
		state.simPlaying = false;
		state.simTime = Number((e.target as HTMLInputElement).value);
		drawSimulation();
	});
	document.querySelector("#sim-speed")?.addEventListener("change", (e) => {
		state.simSpeed = Number((e.target as HTMLSelectElement).value);
	});
	document.querySelectorAll<HTMLElement>("[data-seek]").forEach((el) =>
		el.addEventListener("click", () => {
			state.simTime = Number(el.dataset.seek);
			state.simPlaying = false;
			renderSim();
			toast(t("sim.seek", { time: state.simTime.toFixed(2) }), "info");
		}),
	);
	document
		.querySelectorAll<HTMLInputElement>("[data-overlay]")
		.forEach((input) =>
			input.addEventListener("change", () => {
				state.overlays[input.dataset.overlay as keyof typeof state.overlays] =
					input.checked;
				drawSimulation();
			}),
		);
	document.querySelector("#compare-toggle")?.addEventListener("change", (e) => {
		state.compare = (e.target as HTMLInputElement).checked;
		document
			.querySelector("#replay-stage")
			?.classList.toggle("compare-mode", state.compare);
		const watermark = document.querySelector(".demo-watermark");
		if (watermark)
			watermark.textContent = t(
				state.compare ? "sim.compareWatermark" : "sim.watermark",
			);
		drawSimulation();
		toast(t(state.compare ? "sim.compareOn" : "sim.compareOff"), "info");
	});
	document.querySelector("#rerun-sim")?.addEventListener("click", () => {
		state.simTime = 0;
		state.simPlaying = true;
		renderSim();
		toast(t("sim.rerunDone"));
	});
	document
		.querySelector("#advanced-sim")
		?.addEventListener("click", () => toast(t("sim.advancedNote"), "info"));
	document
		.querySelectorAll<HTMLElement>(".run-config .text-input")
		.forEach((input) =>
			input.addEventListener("change", () => toast(t("design.updated"))),
		);
	document
		.querySelectorAll<HTMLButtonElement>("[data-camera]")
		.forEach((button) =>
			button.addEventListener("click", () => {
				state.simCamera = button.dataset.camera!;
				document
					.querySelectorAll("[data-camera]")
					.forEach((b) => b.classList.toggle("active", b === button));
				drawSimulation();
			}),
		);
}

let lastFrame = performance.now();
function tick(now: number) {
	const dt = Math.min(0.05, (now - lastFrame) / 1000);
	lastFrame = now;
	if (state.page === "design" && state.playing && !dragStart) {
		state.theta -= dt * 1.4 * state.speed;
		drawPose(state.theta);
	}
	if (state.page === "sim" && state.simPlaying) {
		state.simTime += dt * state.simSpeed;
		if (state.simTime > 6) state.simTime = 0;
		drawSimulation();
	}
	requestAnimationFrame(tick);
}

document.addEventListener("keydown", (event) => {
	if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
		event.preventDefault();
		globalAction(event.shiftKey ? "redo" : "undo");
	}
	if (
		event.code === "Space" &&
		!(event.target as HTMLElement).matches("input,select,textarea,button")
	) {
		event.preventDefault();
		if (state.page === "design") state.playing = !state.playing;
		if (state.page === "sim") state.simPlaying = !state.simPlaying;
	}
});

document.documentElement.dataset.theme = state.theme;
setLocale(getLocale());
shell();
navigate("design");
requestAnimationFrame(tick);
