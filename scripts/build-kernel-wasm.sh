#!/usr/bin/env bash
# Required: Rust with wasm32-unknown-unknown target and wasm-bindgen-cli 0.2.105.
# No downloads or environment mutation: CI/container setup installs these explicitly.
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v wasm-bindgen >/dev/null || [ "$(wasm-bindgen --version)" != "wasm-bindgen 0.2.105" ]; then
  echo "Install wasm-bindgen-cli 0.2.105 (matching Cargo.lock) before building the web kernel." >&2
  exit 1
fi
cargo build --locked --release --package beest-kernel --no-default-features --features wasm --target wasm32-unknown-unknown
wasm-bindgen --target web --out-dir crates/beest-kernel/generated --out-name beest_kernel "${CARGO_TARGET_DIR:-target}/wasm32-unknown-unknown/release/beest_kernel.wasm"
