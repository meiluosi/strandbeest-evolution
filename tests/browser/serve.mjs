import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, resolve, sep } from "node:path";

const root = resolve(process.argv[2]);
const types = {
	".html": "text/html; charset=utf-8",
	".js": "text/javascript; charset=utf-8",
	".css": "text/css; charset=utf-8",
	".json": "application/json",
	".wasm": "application/wasm",
	".svg": "image/svg+xml",
	".png": "image/png",
};
createServer(async (request, response) => {
	try {
		const pathname = decodeURIComponent(
			new URL(request.url, "http://local").pathname,
		);
		const path = resolve(
			root,
			`.${pathname === "/" ? "/index.html" : pathname}`,
		);
		if (!path.startsWith(root + sep) || !(await stat(path)).isFile()) {
			response.writeHead(404).end();
			return;
		}
		response.writeHead(200, {
			"content-type": types[extname(path)] ?? "application/octet-stream",
			"cache-control": "no-store",
		});
		createReadStream(path).pipe(response);
	} catch {
		response.writeHead(404).end();
	}
}).listen(Number(process.argv[3]), "0.0.0.0");
