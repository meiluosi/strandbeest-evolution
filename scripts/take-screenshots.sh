#!/usr/bin/env bash
set -e

EDGE="/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
BASE="http://localhost:4173"
OUT="docs/assets/screens"

snap() {
  local file="$1"
  local url="$2"
  local size="$3"
  local budget="${4:-2500}"
  echo "Capturing $file ($size)..."
  "$EDGE" --headless=new \
    --screenshot="$OUT/$file" \
    --window-size="$size" \
    --virtual-time-budget="$budget" \
    "$url" 2>/dev/null || true
}

mkdir -p "$OUT"

# Design tab (zh & en)
snap "design-zh.png" "$BASE/?tab=design&lang=zh" "1600,1200" 2500
snap "design-en.png" "$BASE/?tab=design&lang=en" "1600,1200" 2500

# Sim tab - replay (zh & en)
snap "sim-replay-zh.png" "$BASE/?tab=sim&lang=zh" "1600,1111" 3500
snap "sim-replay-en.png" "$BASE/?tab=sim&lang=en" "1600,1111" 3500

# Sim tab - glassbox (zh & en)
snap "sim-glassbox-zh.png" "$BASE/?tab=sim&lang=zh&scroll=glassbox" "1600,1111" 3500
snap "sim-glassbox-en.png" "$BASE/?tab=sim&lang=en&scroll=glassbox" "1600,1111" 3500

# Fabricate tab (zh & en)
snap "fabricate-zh.png" "$BASE/?tab=fab&lang=zh" "1600,1400" 2500
snap "fabricate-en.png" "$BASE/?tab=fab&lang=en" "1600,1400" 2500

# Lab tab (zh & en)
snap "lab-zh.png" "$BASE/?tab=lab&lang=zh" "1600,1111" 2500
snap "lab-en.png" "$BASE/?tab=lab&lang=en" "1600,1111" 2500

echo "All screenshots captured successfully!"
