import {
	createTranslator,
	detectLocale,
	LOCALES,
	type Locale,
	type Params,
} from "./core";
import en from "./en.json";
import zh from "./zh.json";

const STORAGE_KEY = "strandbeest-locale";
const catalogs = { zh, en };
const translators = {
	zh: createTranslator(catalogs, "zh"),
	en: createTranslator(catalogs, "en"),
};

function initialLocale(): Locale {
	try {
		const saved = localStorage.getItem(STORAGE_KEY);
		if (saved && (LOCALES as readonly string[]).includes(saved))
			return saved as Locale;
	} catch {
		// storage can be unavailable; fall through to detection
	}
	return detectLocale(
		typeof navigator === "undefined" ? [] : navigator.languages,
	);
}

/** Reactive language state; reading `i18n.locale` inside a template or $derived subscribes to changes. */
export const i18n = $state({ locale: initialLocale() });

function applyDocument(locale: Locale) {
	if (typeof document === "undefined") return;
	document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
	document.title = translators[locale]("app.docTitle");
}

export function setLocale(locale: Locale) {
	i18n.locale = locale;
	try {
		localStorage.setItem(STORAGE_KEY, locale);
	} catch {
		// remembering the choice is a convenience only
	}
	applyDocument(locale);
}

applyDocument(i18n.locale);

/** Translate. Because it reads `i18n.locale`, calls made while rendering re-run when the language changes. */
export function t(key: string, params?: Params): string {
	return translators[i18n.locale](key, params);
}
