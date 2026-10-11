/** Python's number formatting, so MJCF text built here is byte-identical to what packages/sim writes.
 *  The builder uses two spellings: `f"{v:.9g}"` (fmtG9) and a bare `f"{v}"`, which is `repr` (pyFloat / pyInt). */

/** `f"{v:.9g}"` */
export function fmtG9(v: number): string {
	return fmtG(v, 9);
}

/** `format(v, ".{P}g")` (and `f"{v:g}"` for P = 6) */
export function fmtG(v: number, P: number): string {
	if (Number.isNaN(v)) return "nan";
	if (!Number.isFinite(v)) return v < 0 ? "-inf" : "inf";
	if (v === 0) return Object.is(v, -0) ? "-0" : "0";
	const [mant, ex] = v.toExponential(P - 1).split("e") as [string, string];
	const e = Number(ex);
	if (e < -4 || e >= P) {
		const m = mant.includes(".")
			? mant.replace(/0+$/, "").replace(/\.$/, "")
			: mant;
		return `${m}e${e < 0 ? "-" : "+"}${String(Math.abs(e)).padStart(2, "0")}`;
	}
	const fixed = v.toFixed(Math.max(0, P - 1 - e));
	return fixed.includes(".")
		? fixed.replace(/0+$/, "").replace(/\.$/, "")
		: fixed;
}

/** `repr(float)`: shortest digits that round-trip; fixed notation for 1e-4 <= |x| < 1e16, else scientific. */
export function pyFloat(v: number): string {
	if (Number.isNaN(v)) return "nan";
	if (!Number.isFinite(v)) return v < 0 ? "-inf" : "inf";
	if (v === 0) return Object.is(v, -0) ? "-0.0" : "0.0";
	const neg = v < 0;
	const [mant, ex] = Math.abs(v).toExponential().split("e") as [string, string];
	const digits = mant.replace(".", "");
	const decpt = Number(ex) + 1; // position of the decimal point relative to the first digit
	let s: string;
	if (decpt > -4 && decpt <= 16) {
		if (decpt <= 0) s = `0.${"0".repeat(-decpt)}${digits}`;
		else if (decpt >= digits.length)
			s = `${digits}${"0".repeat(decpt - digits.length)}.0`;
		else s = `${digits.slice(0, decpt)}.${digits.slice(decpt)}`;
	} else {
		const e = decpt - 1;
		s = `${digits[0]}${digits.length > 1 ? `.${digits.slice(1)}` : ""}e${e < 0 ? "-" : "+"}${String(Math.abs(e)).padStart(2, "0")}`;
	}
	return neg ? `-${s}` : s;
}

/** `str(int)` */
export function pyInt(v: number): string {
	return String(Math.trunc(v));
}

/** `f"{v:.{d}f}"`: like toFixed, but exact ties round half to even as Python does (toFixed picks the larger). */
export function pyFixed(v: number, d: number): string {
	if (!Number.isFinite(v)) return fmtG(v, 6);
	const k = 10 ** d;
	const scaled = Math.abs(v) * k;
	if (Math.abs(scaled - Math.floor(scaled) - 0.5) === 0) {
		const f = Math.floor(scaled);
		const n = f % 2 === 0 ? f : f + 1;
		return `${v < 0 ? "-" : ""}${(n / k).toFixed(d)}`;
	}
	return v.toFixed(d);
}

/** `f"{v:.0%}"` */
export function pyPercent0(v: number): string {
	return `${pyFixed(v * 100, 0)}%`;
}
