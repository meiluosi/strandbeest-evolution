import {
	createWasmKinematicsKernel,
	installKinematicsKernel,
	kinematicsKernel,
} from "strandbeest-core";
import init, * as bindings from "../../../crates/beest-kernel/generated/beest_kernel.js";
import wasmUrl from "../../../crates/beest-kernel/generated/beest_kernel_bg.wasm?url";

let initialization: Promise<string> | undefined;

/** Every JS realm (UI/worker) must initialize before numerical work; rejection is never a TS fallback. */
export function initializeKernel(): Promise<string> {
	initialization ??= (async () => {
		await init({ module_or_path: wasmUrl });
		installKinematicsKernel(createWasmKinematicsKernel(bindings));
		return kinematicsKernel().name;
	})();
	return initialization;
}
