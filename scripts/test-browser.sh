#!/usr/bin/env bash
# Fixed Linux browser + fonts + software WebGL: the same baseline locally and in CI.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${BEEST_E2E_VISUAL_PROBE:-0}" != 0 && -n "${BEEST_E2E_VISUAL_PROBE:-}" && "$*" == *--update-snapshots* ]]; then
  echo "The negative visual control must never update baselines." >&2
  exit 1
fi

if [[ "${BEEST_E2E_SKIP_BUILD:-0}" != 1 ]]; then
  pnpm --filter @strandbeest/web-demo exec vite build --outDir ../../.browser-build/live --emptyOutDir
  VITE_STATIC=1 pnpm --filter @strandbeest/web-demo exec vite build --outDir ../../.browser-build/static --emptyOutDir
fi
if [[ "${BEEST_E2E_SKIP_IMAGE_BUILD:-0}" != 1 ]]; then
  docker build --platform linux/amd64 -f tests/browser/Dockerfile -t beest-browser:1.64.1 .
fi
mkdir -p test-results
docker run --rm --platform linux/amd64 --entrypoint cat beest-browser:1.64.1 \
  /opt/beest-browser-packages.txt >test-results/browser-packages.txt

api_pid=""
cleanup() {
  if [[ -n "$api_pid" ]]; then kill "$api_pid" 2>/dev/null || true; wait "$api_pid" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM
if [[ -z "${BEEST_E2E_API_URL:-}" ]]; then
  if curl --silent --fail http://127.0.0.1:8787/health >/dev/null; then
    echo "Port 8787 already serves an API; stop it or explicitly set BEEST_E2E_API_URL." >&2
    exit 1
  fi
  mkdir -p test-results
  .venv/bin/python tests/browser/serve_api.py >test-results/browser-api.log 2>&1 &
  api_pid=$!
  for attempt in {1..60}; do
    if curl --silent --fail http://127.0.0.1:8787/health >/dev/null; then break; fi
    if ! kill -0 "$api_pid" 2>/dev/null; then cat test-results/browser-api.log; exit 1; fi
    sleep 1
  done
  curl --silent --fail http://127.0.0.1:8787/health >/dev/null
  export BEEST_E2E_API_URL=http://host.docker.internal:8787
fi

docker_args=(--rm --init --ipc=host --platform linux/amd64 --add-host=host.docker.internal:host-gateway)
if [[ -n "${BEEST_E2E_NETWORK:-}" ]]; then docker_args+=(--network "$BEEST_E2E_NETWORK"); fi
docker run "${docker_args[@]}" \
  --mount "type=bind,src=$PWD,dst=/work" \
  --mount type=volume,dst=/work/node_modules \
  -e BEEST_E2E_API_URL -e CI -e BEEST_E2E_VISUAL_PROBE \
  beest-browser:1.64.1 test -c playwright.config.ts "$@"

# Inspect the browser's actual downloaded artifacts with the backend's mesh tools.
.venv/bin/python tests/browser/validate_manufacturing.py test-results/browser
