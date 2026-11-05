export type Theme = "light" | "dark";

const STORAGE_KEY = "strandbeest-theme";

function initialTheme(): Theme {
	try {
		const saved = localStorage.getItem(STORAGE_KEY);
		if (saved === "light" || saved === "dark") return saved;
	} catch {
		// Storage is optional; the system preference remains available.
	}
	return typeof matchMedia !== "undefined" &&
		matchMedia("(prefers-color-scheme: dark)").matches
		? "dark"
		: "light";
}

export const theme = $state({ mode: initialTheme() });

export function isDarkTheme(): boolean {
	return theme.mode === "dark";
}

function applyDocument() {
	if (typeof document === "undefined") return;
	document.documentElement.dataset.theme = theme.mode;
}

export function toggleTheme() {
	theme.mode = theme.mode === "dark" ? "light" : "dark";
	try {
		localStorage.setItem(STORAGE_KEY, theme.mode);
	} catch {
		// The in-memory preference still applies when storage is unavailable.
	}
	applyDocument();
	window.dispatchEvent(new Event("beest-theme-change"));
}

applyDocument();
