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

## What this is not
No authentication, no multi-user separation, no remote storage: it is a single-machine lab. Putting it on a public host needs at least auth, quotas and rate limits first (see PLATFORM.md, section 4.3).
