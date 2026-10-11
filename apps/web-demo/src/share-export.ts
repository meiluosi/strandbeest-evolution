/** Things people post: a design card (PNG) and a recording of the 3D replay (WebM/MP4). Browser-only, no dependencies. */

export interface CardData {
	title: string;
	subtitle: string;
	/** foot path in model coordinates, y up */
	foot: { x: number; y: number }[];
	stats: { value: string; label: string }[];
	footer: string;
}

function css(name: string, fallback: string): string {
	const v = getComputedStyle(document.documentElement)
		.getPropertyValue(name)
		.trim();
	return v || fallback;
}

export async function designCardPng(d: CardData): Promise<Blob> {
	const W = 1200;
	const H = 630;
	const c = document.createElement("canvas");
	c.width = W;
	c.height = H;
	const g = c.getContext("2d") as CanvasRenderingContext2D;
	const bg = css("--bg", "#f7f6f3");
	const ink = css("--ink", "#1f2430");
	const accent = css("--accent", "#d9622b");
	const muted = css("--muted", "#6b7280");
	g.fillStyle = bg;
	g.fillRect(0, 0, W, H);
	g.fillStyle = accent;
	g.fillRect(0, 0, 14, H);

	g.fillStyle = ink;
	g.font = "700 54px system-ui, sans-serif";
	g.fillText(d.title, 60, 100, W - 120);
	g.fillStyle = muted;
	g.font = "28px system-ui, sans-serif";
	g.fillText(d.subtitle, 60, 148, W - 120);

	// the foot path, scaled into a box
	if (d.foot.length > 1) {
		const bx = 60;
		const by = 190;
		const bw = 700;
		const bh = 330;
		const xs = d.foot.map((p) => p.x);
		const ys = d.foot.map((p) => p.y);
		const x0 = Math.min(...xs);
		const y0 = Math.min(...ys);
		const k =
			Math.min(
				bw / (Math.max(...xs) - x0 || 1),
				bh / (Math.max(...ys) - y0 || 1),
			) * 0.9;
		const ox = bx + (bw - (Math.max(...xs) - x0) * k) / 2;
		const oy = by + (bh - (Math.max(...ys) - y0) * k) / 2;
		g.beginPath();
		d.foot.forEach((p, i) => {
			const x = ox + (p.x - x0) * k;
			const y = oy + (Math.max(...ys) - p.y) * k;
			if (i) g.lineTo(x, y);
			else g.moveTo(x, y);
		});
		g.closePath();
		g.fillStyle = `${accent}33`;
		g.fill();
		g.lineWidth = 6;
		g.lineJoin = "round";
		g.strokeStyle = accent;
		g.stroke();
	}

	d.stats.slice(0, 3).forEach((s, i) => {
		const y = 230 + i * 120;
		g.fillStyle = ink;
		g.font = "700 64px system-ui, sans-serif";
		g.fillText(s.value, 820, y);
		g.fillStyle = muted;
		g.font = "26px system-ui, sans-serif";
		g.fillText(s.label, 820, y + 38, 340);
	});

	g.fillStyle = muted;
	g.font = "24px system-ui, sans-serif";
	g.fillText(d.footer, 60, H - 40, W - 120);
	return new Promise((res, rej) =>
		c.toBlob((b) => (b ? res(b) : rej(new Error("png"))), "image/png"),
	);
}

const VIDEO_TYPES = ["video/webm;codecs=vp9", "video/webm", "video/mp4"];
export const videoType = (): string | null =>
	typeof MediaRecorder === "undefined"
		? null
		: (VIDEO_TYPES.find((t) => MediaRecorder.isTypeSupported(t)) ?? null);

/** Start recording a canvas; call the returned function to stop and get the file. */
export function recordCanvas(
	canvas: HTMLCanvasElement,
	fps = 30,
): () => Promise<{ blob: Blob; ext: string }> {
	const type = videoType();
	if (!type) throw new Error("MediaRecorder is not available");
	const rec = new MediaRecorder(canvas.captureStream(fps), {
		mimeType: type,
		videoBitsPerSecond: 4_000_000,
	});
	const chunks: Blob[] = [];
	rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
	rec.start();
	return () =>
		new Promise((res) => {
			rec.onstop = () =>
				res({
					blob: new Blob(chunks, { type }),
					ext: type.startsWith("video/mp4") ? "mp4" : "webm",
				});
			rec.stop();
		});
}

export function saveBlob(name: string, blob: Blob) {
	const a = document.createElement("a");
	a.href = URL.createObjectURL(blob);
	a.download = name;
	a.click();
	setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
