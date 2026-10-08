import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { IntlMessageFormat } from "intl-messageformat";
import { describe, expect, it } from "vitest";
import { createTranslator, detectLocale } from "./core";
import en from "./en.json";
import zh from "./zh.json";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");
const placeholders = (m: string) =>
	[...m.matchAll(/\{(\w+)[,}]/g)].map((x) => x[1]).sort();

describe("catalogs", () => {
	it("zh and en define exactly the same keys", () => {
		expect(Object.keys(en).sort()).toEqual(Object.keys(zh).sort());
	});

	it("every message is valid ICU and uses the same placeholders in both languages", () => {
		for (const key of Object.keys(zh)) {
			const z = (zh as Record<string, string>)[key] as string;
			const e = (en as Record<string, string>)[key] as string;
			expect(() => new IntlMessageFormat(z, "zh-CN"), key).not.toThrow();
			expect(() => new IntlMessageFormat(e, "en"), key).not.toThrow();
			expect(placeholders(e), `placeholders of ${key}`).toEqual(
				placeholders(z),
			);
		}
	});

	it("the English catalog contains no CJK characters", () => {
		for (const [key, msg] of Object.entries(en)) {
			expect(/[　-〿一-鿿＀-￯]/.test(msg), key).toBe(false);
		}
	});

	it("every key used in the sources exists, and every catalog key is used", () => {
		const files = [SRC, join(SRC, "i18n")].flatMap((dir) =>
			readdirSync(dir)
				.filter((f) => /\.(svelte|ts)$/.test(f) && !f.endsWith(".test.ts"))
				.map((f) => join(dir, f)),
		);
		const text = files.map((f) => readFileSync(f, "utf8")).join("\n");
		const used = new Set<string>();
		for (const m of text.matchAll(
			/"((?:[a-z][A-Za-z0-9]*)(?:\.[A-Za-z0-9_]+)+)"/g,
		))
			used.add(m[1] as string);
		const called = [...text.matchAll(/\bt\("([\w.]+)"/g)].map(
			(m) => m[1] as string,
		);
		for (const key of called)
			expect(zh, `missing key ${key}`).toHaveProperty([key]);
		const unused = Object.keys(zh).filter((k) => !used.has(k));
		expect(unused).toEqual([]);
	});
});

describe("translator", () => {
	const catalogs = {
		zh: { a: "你好 {name}", only: "仅中文" },
		en: { a: "Hello {name}" },
	};
	it("formats parameters", () => {
		expect(createTranslator(catalogs, "en")("a", { name: "Ada" })).toBe(
			"Hello Ada",
		);
		expect(createTranslator(catalogs, "zh")("a", { name: "Ada" })).toBe(
			"你好 Ada",
		);
	});
	it("falls back to the fallback locale, then to the key", () => {
		expect(createTranslator(catalogs, "en")("only")).toBe("仅中文");
		expect(createTranslator(catalogs, "en")("nope")).toBe("nope");
	});
	it("supports ICU plural", () => {
		const c = { zh: {}, en: { n: "{n, plural, one {# row} other {# rows}}" } };
		const t = createTranslator(c, "en");
		expect(t("n", { n: 1 })).toBe("1 row");
		expect(t("n", { n: 3 })).toBe("3 rows");
	});
	it("detects the first supported browser language", () => {
		expect(detectLocale(["fr-FR", "en-GB"])).toBe("en");
		expect(detectLocale(["zh-TW"])).toBe("zh");
		expect(detectLocale(["fr"])).toBe("zh");
	});
});
