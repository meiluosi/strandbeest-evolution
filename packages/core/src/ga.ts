import { type Fitness } from "./fitness";
import { createRng, gaussian, type Rng } from "./rng";

export interface GAOptions {
	seed: number;
	population?: number;
	generations?: number;
	/** per-gene mutation probability */
	mutationRate?: number;
	/** mutation std-dev as a fraction of the gene's value */
	mutationScale?: number;
	elites?: number;
	tournament?: number;
	/** genes are clamped to [lo*seed, hi*seed] around the starting genome */
	bounds?: [number, number];
}

export interface GAState {
	generation: number;
	best: number[];
	bestFitness: number;
	meanFitness: number;
}

export interface GAResult {
	best: number[];
	bestFitness: number;
	history: GAState[];
}

/** Generator-style GA so UIs can step it. Randomness comes only from the seeded RNG. */
export function* evolve(
	start: number[],
	fitness: Fitness,
	opts: GAOptions,
): Generator<GAState, GAResult> {
	const rng: Rng = createRng(opts.seed);
	const popSize = opts.population ?? 60;
	const gens = opts.generations ?? 60;
	const mutRate = opts.mutationRate ?? 0.25;
	const mutScale = opts.mutationScale ?? 0.06;
	const elites = opts.elites ?? 2;
	const tSize = opts.tournament ?? 3;
	const [loF, hiF] = opts.bounds ?? [0.5, 1.5];
	const lo = start.map((v) => v * loF);
	const hi = start.map((v) => v * hiF);
	const clamp = (g: number[]) =>
		g.map((v, i) => Math.min(hi[i] as number, Math.max(lo[i] as number, v)));
	const mutate = (g: number[]) =>
		clamp(
			g.map((v) => (rng() < mutRate ? v * (1 + mutScale * gaussian(rng)) : v)),
		);

	let pop = Array.from({ length: popSize }, (_, k) =>
		k === 0
			? start.slice()
			: mutate(start.map((v) => v * (1 + 0.1 * gaussian(rng)))),
	);
	const history: GAState[] = [];
	let best = start;
	let bestFitness = Number.NEGATIVE_INFINITY;

	for (let gen = 0; gen <= gens; gen++) {
		const scores = pop.map(fitness);
		const order = scores
			.map((_, i) => i)
			.sort((a, b) => (scores[b] as number) - (scores[a] as number));
		const top = order[0] as number;
		if ((scores[top] as number) > bestFitness) {
			bestFitness = scores[top] as number;
			best = (pop[top] as number[]).slice();
		}
		const finite = scores.filter(Number.isFinite);
		const state: GAState = {
			generation: gen,
			best,
			bestFitness,
			meanFitness: finite.length
				? finite.reduce((s, v) => s + v, 0) / finite.length
				: Number.NEGATIVE_INFINITY,
		};
		history.push(state);
		yield state;
		if (gen === gens) break;

		const pick = () => {
			let w = Math.floor(rng() * popSize);
			for (let i = 1; i < tSize; i++) {
				const c = Math.floor(rng() * popSize);
				if ((scores[c] as number) > (scores[w] as number)) w = c;
			}
			return pop[w] as number[];
		};
		const next = order
			.slice(0, elites)
			.map((i) => (pop[i] as number[]).slice());
		while (next.length < popSize) {
			const p1 = pick();
			const p2 = pick();
			const child = p1.map((v, i) => {
				const t = rng();
				return v * t + (p2[i] as number) * (1 - t);
			});
			next.push(mutate(child));
		}
		pop = next;
	}
	return { best, bestFitness, history };
}

/** Run to completion. */
export function runGA(
	start: number[],
	fitness: Fitness,
	opts: GAOptions,
): GAResult {
	const it = evolve(start, fitness, opts);
	for (;;) {
		const r = it.next();
		if (r.done) return r.value;
	}
}
