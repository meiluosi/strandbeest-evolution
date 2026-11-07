import en from "./i18n/en.json";
import zh from "./i18n/zh.json";

export type Locale = "zh" | "en";
const catalogs = { zh, en } as const;
let locale: Locale = "zh";

export function t(
	key: keyof typeof zh,
	params: Record<string, string | number> = {},
): string {
	let message: string = catalogs[locale][key] ?? zh[key] ?? key;
	Object.entries(params).forEach(([name, value]) => {
		message = message.replaceAll(`{${name}}`, String(value));
	});
	return message;
}

export function getLocale(): Locale {
	return locale;
}

export function setLocale(next: Locale): void {
	locale = next;
	document.documentElement.lang = next === "zh" ? "zh-CN" : "en";
}
