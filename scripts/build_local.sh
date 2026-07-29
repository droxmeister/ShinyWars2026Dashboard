#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m src.build_dashboard \
  --local-input-dir local_input \
  --output web/data/strategy.json
python scripts/validate_site_data.py web/data/strategy.json
printf 'Open web/index.html through a local HTTP server, for example:\n'
printf '  python -m http.server 8000 --directory web\n'
