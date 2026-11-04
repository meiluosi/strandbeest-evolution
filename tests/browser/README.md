# Browser regressions / 浏览器回归

`pnpm test:browser` builds both live and static apps, starts a real API with a
temporary asset directory, and runs Chromium in a fixed Linux amd64 container.
Install the project Python environment and build the Rust WASM kernel first:

```sh
pnpm install --frozen-lockfile
./scripts/setup-python.sh
./scripts/build-kernel-wasm.sh
pnpm test:browser
```

The kernel build requires the repository's Rust toolchain, the
`wasm32-unknown-unknown` target and `wasm-bindgen-cli` 0.2.105. Docker must be
running. No production assets are used. Local API port 8787 is reserved for this
runner; the two built sites use ports 4173/4174 inside the browser container.

Four projects exercise live/static × Chinese/English. Successful evolution,
design persistence, simulation and Arrow replay use the real API and physics
kernel. Only explicit failure tests inject HTTP 503. Static tests assert no API
requests. Every test checks for unexpected page exceptions and the Rust WASM
mount marker. The full H5 card also requires measurement/calibration and
fabrication paths; this suite does not claim those unfinished paths are covered.

`tests/browser/Dockerfile` pins the Node base digest, Playwright 1.64.1, Chromium
156.0.8078.4 (revision 1248), Noto CJK and Liberation font versions. The image
records every installed Debian package in `/opt/beest-browser-packages.txt`.
Snapshots use the same viewport, locale, timezone and software WebGL renderer on
developer machines and CI. Do not replace these baselines with native macOS or
Windows screenshots.
Atlas captures pause the designer and close the asset browser through its actual
disclosure control, so existing records do not change the capture position.

The local Linux/amd64 run under Rosetta still exposed a strict visual failure:
the English invalid-import atlas alternated by fewer than 100 RGB pixels along
one SVG edge, despite a stable layout. Zero-difference visual acceptance remains
unverified; these failures are retained, not retried away or accepted as new
baselines. See the H5 experiment record for the complete validation status.

```sh
# Review the changed images before accepting a new baseline.
pnpm test:browser --update-snapshots

# Repeat without rebuilding the app (only after a successful current build).
BEEST_E2E_SKIP_BUILD=1 pnpm test:browser

# Reuse the already verified local browser image too (no downloads/rebuild).
BEEST_E2E_SKIP_BUILD=1 BEEST_E2E_SKIP_IMAGE_BUILD=1 pnpm test:browser

# Negative control: expected failure, with an actual magenta visual regression.
BEEST_E2E_VISUAL_PROBE=1 BEEST_E2E_SKIP_BUILD=1 pnpm test:browser --project=static-en --grep 'atlas slices'
```

Baselines live in `tests/browser/baselines/`. Failures retain expected/actual/diff
PNGs, a browser trace and the page accessibility snapshot under
`test-results/browser/`; the HTML report is `playwright-report/index.html`.
`test-results/browser.xml` is a JUnit result. CI should upload both result
directories even on failure. Retries and pixel-difference tolerances are disabled.
`test-results/browser-packages.txt` records the image's installed package versions;
`baselines/environment.json` records the reviewed baseline's rendering environment.

To use an existing isolated API, set `BEEST_E2E_API_URL` to an address reachable
**from the container**. If the API is another container, also set
`BEEST_E2E_NETWORK` to its Docker network. Its CORS origins must include
`http://127.0.0.1:4173` and `http://127.0.0.1:4174`.

For a quick native functional diagnosis using an already installed browser, run
Playwright directly with `BEEST_E2E_EXECUTABLE_PATH` and `--ignore-snapshots`.
That run is not screenshot evidence. Never combine the visual negative control
with `--update-snapshots`.
