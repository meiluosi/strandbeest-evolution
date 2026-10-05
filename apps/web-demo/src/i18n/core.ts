import { IntlMessageFormat } from "intl-messageformat";

export type Locale = "zh" | "en";
export type Catalog = Record<string, string>;
export type Params = Record<
	string,
	string | number | boolean | null | undefined
>;

export const LOCALES: readonly Locale[] = ["zh", "en"];
export const LOCALE_NAMES: Record<Locale, string> = {
	zh: "中文",
	en: "English",
};

/**
 * Pure translator: messages are ICU strings. Missing keys fall back to the fallback locale,
 * then to the key itself, so a missing translation is visible but never throws.
 */
export function createTranslator(
	catalogs: Record<Locale, Catalog>,
	locale: Locale,
	fallback: Locale = "zh",
) {
	const cache = new Map<string, IntlMessageFormat>();
	return function t(key: string, params?: Params): string {
		const message = catalogs[locale]?.[key] ?? catalogs[fallback]?.[key];
		if (message === undefined) return key;
		if (!params && !message.includes("{")) return message;
		const id = `${locale}\u0000${key}`;
		let fmt = cache.get(id);
		if (!fmt) {
			try {
				fmt = new IntlMessageFormat(message, locale === "zh" ? "zh-CN" : "en");
			} catch {
				return message;
			}
			cache.set(id, fmt);
		}
		return String(
			fmt.format((params ?? {}) as Record<string, string | number>),
		);
	};
}

/** Pick the first supported language from a navigator-style list, else the fallback. */
export function detectLocale(
	languages: readonly string[],
	fallback: Locale = "zh",
): Locale {
	for (const tag of languages) {
		const base = tag.toLowerCase().split("-")[0];
		if (base === "zh" || base === "en") return base;
	}
	return fallback;
}
