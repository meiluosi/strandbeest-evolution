<script lang="ts">
import {
	cycleSummary,
	DEFAULT_SAIL,
	DEFAULT_WALKER,
	type JansenParams,
	jansenSpec,
	windWalk,
} from "strandbeest-core";

let { params }: { params: JansenParams } = $props();

let wind = $state(6);
let mass = $state(50);
let slopeDeg = $state(0);
let legs = $state(12);
let rolling = $state(5);

const summary = $derived(
	cycleSummary(
		jansenSpec(params),
		{ ...DEFAULT_WALKER, mass, legs },
		{ slope: (slopeDeg * Math.PI) / 180, drag: (rolling / 100) * mass * 9.81 },
		120,
	),
);
const result = $derived(summary ? windWalk(DEFAULT_SAIL, summary, wind) : null);
</script>

<div class="wind">
	<div class="grid">
		<label>风速 {wind} m/s <input type="range" min="0" max="15" step="0.5" bind:value={wind} /></label>
		<label>质量 {mass} kg <input type="range" min="10" max="200" step="5" bind:value={mass} /></label>
		<label>坡度 {slopeDeg}° <input type="range" min="0" max="25" step="1" bind:value={slopeDeg} /></label>
		<label>腿数 {legs} <input type="range" min="2" max="24" step="2" bind:value={legs} /></label>
		<label>阻力 {rolling}% 体重 <input type="range" min="0" max="20" step="1" bind:value={rolling} /></label>
	</div>
	{#if summary && result}
		<p>
			每圈前进 {summary.stride.toFixed(2)} m · 曲柄峰值扭矩 {summary.peakTorque.toFixed(1)} N·m · 平均 {summary.meanTorque.toFixed(1)} N·m
			· 稳定支撑 {(summary.stableFraction * 100).toFixed(0)}%
		</p>
		<p class="big">
			{#if result.runs}
				预计速度 <b>{result.speed.toFixed(2)} m/s</b>（起步需风速 ≥ {result.minStartWind.toFixed(1)} m/s）
			{:else}
				风太小，推不动（起步需风速 ≥ {result.minStartWind.toFixed(1)} m/s）
			{/if}
		</p>
		<small>准静态模型：不含惯性、滑移、松软地面；帆、传动比、阻力均为示意假设。用于比较不同连杆设计，不是实测预测。</small>
	{:else}
		<p>该参数下连杆无法闭合。</p>
	{/if}
</div>

<style>
	.wind { display: flex; flex-direction: column; gap: 6px; font-size: 14px; }
	.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 6px 14px; }
	.grid label { display: flex; flex-direction: column; }
	.big { font-size: 16px; }
	small { opacity: 0.7; }
</style>
