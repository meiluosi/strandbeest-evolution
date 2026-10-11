# Running the platform locally

## Without Docker
```bash
./scripts/setup-python.sh && source .venv/bin/activate
strandbeest-api                       # http://127.0.0.1:8000
pnpm install && pnpm --filter @strandbeest/web-demo dev   # http://localhost:5173
```

## With Docker
```bash
docker compose up --build             # web http://localhost:8080, API http://localhost:8000
```
Data (designs, runs, exports, measurements, the job database) lives in the named volume `strandbeest-data`, mounted at `/data` in the API container. `docker compose down -v` deletes it.

## Configuration (environment variables of the API)
| variable | default | meaning |
|---|---|---|
| `STRANDBEEST_DATA` | `data` (`/data` in Docker) | where everything is stored |
| `STRANDBEEST_WORKERS` | `2` | parallel jobs; MuJoCo releases the GIL, so threads give real parallelism |
| `STRANDBEEST_CORS` | localhost dev and compose origins | comma-separated allowed browser origins |
| `STRANDBEEST_HOST`, `STRANDBEEST_PORT` | `127.0.0.1`, `8000` | bind address (the container uses `0.0.0.0`) |

The web build reads `VITE_API_URL` (build argument in Docker) as the default backend address; the address can also be changed in the page header and is remembered in the browser.

## Jobs
Runs, sweeps and calibrations are jobs in `strandbeest.db` (SQLite).
- Jobs survive restarts. Jobs that were *running* when the process stopped are marked `failed: interrupted by a restart`; they are not silently re-run, because a run can take minutes.
- `POST /jobs/{id}/cancel`: queued jobs are cancelled immediately; a running sweep stops after the points in flight; a single run or a calibration cannot be interrupted once started.
- Every simulation, including each sweep point, is stored as a run (`run.json` + `arrays.npz`) and indexed in the database; the index is rebuilt from the files on startup.

## Static demo (GitHub Pages)
`VITE_STATIC=1 pnpm --filter @strandbeest/web-demo build` builds a backend-free version: the design tab (editing, evolver, share links, card export) and the simulation tab with **pre-recorded** replays of the default design, one per scene. Fabrication and calibration tabs are hidden.
- Replays live in `apps/web-demo/public/gallery/<scene>.json` and are produced by `tsx scripts/bake-gallery.ts [scene ...]` against a running `strandbeest-api` (about 100 s per scene, 1.6-2 MB each, about 0.3 MB gzipped on the wire). Re-bake whenever the simulator or a scene in `contracts/scenes.json` changes; the replays are an output of the simulator, not a source.
- CI builds it and `scripts/check-static-build.mjs` fails when a scene has no baked replay.
- `.github/workflows/pages.yml` deploys it by hand (`workflow_dispatch`); enabling Pages (Source: GitHub Actions) is the repository owner's step.
- Share links carry the whole design in the URL fragment (`#d=`, deflate + base64url); nothing is sent to a server.

## What this is not
No authentication, no multi-user separation, no remote storage: it is a single-machine lab. Putting it on a public host needs at least auth, quotas and rate limits first (see PLATFORM.md, section 4.3).
