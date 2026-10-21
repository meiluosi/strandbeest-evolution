/** Python's `random.Random(seed)`: Mersenne Twister (MT19937), `random()` and `uniform()`. The bumps terrain draws its layout from
 *  it, so the browser must draw the same numbers for the same seed. Integer seeds below 2**32 (what scenes use) are supported. */
export class PyRandom {
	private mt = new Uint32Array(624);
	private idx = 624;

	constructor(seed: number) {
		if (!Number.isInteger(seed) || seed < 0 || seed >= 2 ** 32)
			throw new Error("PyRandom: seed must be an integer in [0, 2^32)");
		this.initByArray([seed >>> 0]);
	}

	private initGenrand(s: number) {
		const mt = this.mt;
		mt[0] = s >>> 0;
		for (let i = 1; i < 624; i++) {
			const prev = (mt[i - 1] as number) ^ ((mt[i - 1] as number) >>> 30);
			mt[i] = (Math.imul(1812433253, prev) + i) >>> 0;
		}
		this.idx = 624;
	}

	private initByArray(key: number[]) {
		const mt = this.mt;
		this.initGenrand(19650218);
		let i = 1;
		let j = 0;
		for (let k = Math.max(624, key.length); k > 0; k--) {
			const prev = (mt[i - 1] as number) ^ ((mt[i - 1] as number) >>> 30);
			mt[i] =
				(((mt[i] as number) ^ Math.imul(prev, 1664525)) +
					(key[j] as number) +
					j) >>>
				0;
			i++;
			j++;
			if (i >= 624) {
				mt[0] = mt[623] as number;
				i = 1;
			}
			if (j >= key.length) j = 0;
		}
		for (let k = 623; k > 0; k--) {
			const prev = (mt[i - 1] as number) ^ ((mt[i - 1] as number) >>> 30);
			mt[i] = (((mt[i] as number) ^ Math.imul(prev, 1566083941)) - i) >>> 0;
			i++;
			if (i >= 624) {
				mt[0] = mt[623] as number;
				i = 1;
			}
		}
		mt[0] = 0x80000000;
		this.idx = 624;
	}

	private next32(): number {
		const mt = this.mt;
		if (this.idx >= 624) {
			for (let k = 0; k < 624; k++) {
				const y =
					((mt[k] as number) & 0x80000000) |
					((mt[(k + 1) % 624] as number) & 0x7fffffff);
				let v = (mt[(k + 397) % 624] as number) ^ (y >>> 1);
				if (y & 1) v ^= 0x9908b0df;
				mt[k] = v >>> 0;
			}
			this.idx = 0;
		}
		let y = mt[this.idx++] as number;
		y ^= y >>> 11;
		y ^= (y << 7) & 0x9d2c5680;
		y ^= (y << 15) & 0xefc60000;
		y ^= y >>> 18;
		return y >>> 0;
	}

	private gaussNext: number | null = null;

	/** float in [0, 1) with 53 random bits, like `random.random()` */
	random(): number {
		const a = this.next32() >>> 5;
		const b = this.next32() >>> 6;
		return (a * 67108864 + b) / 9007199254740992;
	}

	/** `random.uniform(a, b)` */
	uniform(a: number, b: number): number {
		return a + (b - a) * this.random();
	}

	/** `random.gauss(mu, sigma)` using Python's exact Box-Muller generator */
	gauss(mu = 0.0, sigma = 1.0): number {
		let z = this.gaussNext;
		this.gaussNext = null;
		if (z === null) {
			const x2pi = this.random() * (2.0 * Math.PI);
			const g2rad = Math.sqrt(-2.0 * Math.log(1.0 - this.random()));
			z = Math.cos(x2pi) * g2rad;
			this.gaussNext = Math.sin(x2pi) * g2rad;
		}
		return mu + z * sigma;
	}
}
