import type { LinkageSpec } from "strandbeest-core";

interface CorpusFile {
	name: string;
	spec: LinkageSpec;
}

// Every kinematics contract (contracts/kinematics/*.json) doubles as an example linkage the designer can load:
// add a file there and it shows up here. Jansen's leg comes first.
const files = import.meta.glob("../../../contracts/kinematics/*.json", {
	eager: true,
	import: "default",
}) as Record<string, CorpusFile>;

export const PRESETS: { id: string; spec: LinkageSpec }[] = Object.values(files)
	.map((f) => ({ id: f.name, spec: f.spec }))
	.sort((a, b) =>
		a.id === "jansen" ? -1 : b.id === "jansen" ? 1 : a.id.localeCompare(b.id),
	);
