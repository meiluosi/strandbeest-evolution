/** The GitHub Pages build has no backend: simulations are baked replays (scripts/bake-gallery.ts), designs travel in the URL. */
export const STATIC = import.meta.env.VITE_STATIC === "1";

export const REPO_URL = "https://github.com/meiluosi/strandbeest-evolution";

async function pipe(
	data: Uint8Array,
	stream: CompressionStream | DecompressionStream,
) {
	const out = new Blob([data as BlobPart]).stream().pipeThrough(stream);
	return new Uint8Array(await new Response(out).arrayBuffer());
}

/** Design -> URL-safe text (deflate + base64url), for `#d=` share links. */
export async function encodeShare(doc: unknown): Promise<string> {
	const bytes = await pipe(
		new TextEncoder().encode(JSON.stringify(doc)),
		new CompressionStream("deflate-raw"),
	);
	let bin = "";
	for (const b of bytes) bin += String.fromCharCode(b);
	return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export async function decodeShare(text: string): Promise<unknown> {
	const b64 = text.replace(/-/g, "+").replace(/_/g, "/");
	const bin = atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
	const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
	const raw = await pipe(bytes, new DecompressionStream("deflate-raw"));
	return JSON.parse(new TextDecoder().decode(raw));
}

/** The design in `location.hash` (`#d=...`), if any. */
export async function designFromHash(): Promise<unknown | null> {
	const m = /^#d=([A-Za-z0-9_-]+)$/.exec(location.hash);
	if (!m) return null;
	try {
		return await decodeShare(m[1] as string);
	} catch {
		return null;
	}
}
