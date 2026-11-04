import "./styles.css";
import { mount } from "svelte";
import { t } from "./i18n/index.svelte";
import { initializeKernel } from "./kernel-loader";

const target = document.getElementById("app") as HTMLElement;
target.textContent = t("kernel.loading");
initializeKernel()
	.then(async (name) => {
		// App modules may compute initial geometry, so import them only after the engine is ready.
		const { default: App } = await import("./App.svelte");
		target.textContent = "";
		target.dataset.kernel = name;
		mount(App, { target });
	})
	.catch((error) => {
		target.setAttribute("role", "alert");
		target.textContent = t("kernel.failed", {
			message: error instanceof Error ? error.message : String(error),
		});
	});
