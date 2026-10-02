<script lang="ts">
import { JANSEN_LENGTHS, type JansenParams } from "strandbeest-core";
import Evolver from "./Evolver.svelte";
import LinkageViewer from "./LinkageViewer.svelte";
import WindPanel from "./WindPanel.svelte";

let params = $state<JansenParams>({ ...JANSEN_LENGTHS });
</script>

<main>
	<h1>Jansen 连杆实验室</h1>
	<p>拖动滑块改变连杆长度，观察脚的轨迹（橙色）。默认是 Theo Jansen 的 13 个数字。</p>
	<LinkageViewer bind:params />
	<button onclick={() => (params = { ...JANSEN_LENGTHS })}>恢复 Jansen 原始参数</button>
	<h2>风能带得动吗？</h2>
	<WindPanel {params} />
	<h2>让它自己演化</h2>
	<p>遗传算法在浏览器里运行（Web Worker），从当前参数出发搜索。</p>
	<Evolver {params} onapply={(p) => (params = p)} />
</main>

<style>
	:global(body) { font-family: system-ui, sans-serif; margin: 0; background: Canvas; color: CanvasText; color-scheme: light dark; }
	main { max-width: 860px; margin: 0 auto; padding: 16px; }
</style>
