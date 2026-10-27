<script lang="ts">
import {
	cycleSummary,
	DEFAULT_SAIL,
	DEFAULT_WALKER,
	type LinkageSpec,
	windWalk,
} from "strandbeest-core";
import DynamometerChart from "./DynamometerChart.svelte";
import { t } from "./i18n/index.svelte";

let {
	spec,
	theta = $bindable(0),
	windDrive = $bindable(false),
	windOmega = $bindable<number | null>(null),
	windSpeed = $bindable(6),
	stalledAt = $bindable<number | null>(null),
	ongust,
}: {
	spec: LinkageSpec;
	theta?: number;
	windDrive?: boolean;
	windOmega?: number | null;
	windSpeed?: number;
	stalledAt?: number | null;
	ongust?: () => void;
} = $props();

let wind = $state(6);
let mass = $state(50);
let slopeDeg = $state(0);
let legs = $state(12);
let rolling = $state(5);

const summary = $derived(
	cycleSummary(
		spec,
		{ ...DEFAULT_WALKER, mass, legs },
		{ slope: (slopeDeg * Math.PI) / 180, drag: (rolling / 100) * mass * 9.81 },
		120,
	),
);
const result = $derived(summary ? windWalk(DEFAULT_SAIL, summary, wind) : null);

$effect(() => {
	windSpeed = windDrive ? wind : 0;
	if (!windDrive || !summary || !result) {
		windOmega = null;
		stalledAt = null;
		return;
	}
	windOmega = result.runs ? result.omega : 0;
	if (!result.runs) {
		const peakIdx = summary.samples.findIndex(
			(s) => s.torque === summary.peakTorque,
		);
		stalledAt =
			peakIdx >= 0 ? (2 * Math.PI * peakIdx) / summary.samples.length : 0;
	} else {
		stalledAt = null;
	}
});
</script>

<div class="wind stack">
	<div class="row center wind-toolbar">
		<label class="inline">
			<input type="checkbox" bind:checked={windDrive} />
			<b>{t("wind.driveViewer")}</b>
		</label>
		<button
			class="btn small"
			onclick={() => {
				windDrive = true;
				ongust?.();
			}}
		>
			{t("wind.gustImpulse")}
		</button>
	</div>
	<div class="grid">
		<label>{t("wind.speed", { wind: wind })} <input type="range" min="0" max="15" step="0.5" bind:value={wind} /></label>
		<label>{t("wind.mass", { mass: mass })} <input type="range" min="10" max="200" step="5" bind:value={mass} /></label>
		<label>{t("wind.slope", { slopeDeg: slopeDeg })} <input type="range" min="0" max="25" step="1" bind:value={slopeDeg} /></label>
		<label>{t("wind.legs", { legs: legs })} <input type="range" min="2" max="24" step="2" bind:value={legs} /></label>
		<label>{t("wind.rolling", { rolling: rolling })} <input type="range" min="0" max="20" step="1" bind:value={rolling} /></label>
	</div>
	{#if summary && result}
		<p>
			{t("wind.summary", { stride: summary.stride.toFixed(2), peakTorque: summary.peakTorque.toFixed(1), meanTorque: summary.meanTorque.toFixed(1), stableFraction: (summary.stableFraction * 100).toFixed(0) })}
		</p>
		<p class="big">
			{#if result.runs}
				{t("wind.expectedSpeed")} <b>{result.speed.toFixed(2)} m/s</b>{t("wind.startNeeds", { minStartWind: result.minStartWind.toFixed(1) })}
			{:else}
				{t("wind.tooWeak", { minStartWind: result.minStartWind.toFixed(1) })}
			{/if}
		</p>
		<DynamometerChart
			{spec}
			{wind}
			{mass}
			{legs}
			{slopeDeg}
			{rolling}
			{theta}
			onseektheta={(th) => (theta = th)}
		/>
		<small>{t("wind.caveat")}</small>
	{:else}
		<p>{t("wind.cannotClose")}</p>
	{/if}
</div>


<style>
	.wind { display: flex; flex-direction: column; gap: 6px; font-size: 14px; }
	.wind-toolbar { margin: 2px 0 4px; justify-content: space-between; }
	.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 6px 14px; }
	.grid label { display: flex; flex-direction: column; }
	.big { font-size: 16px; }
	small { opacity: 0.7; }
</style>