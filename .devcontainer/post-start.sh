#!/usr/bin/env bash
# Runs on every Dev Container start. Intentionally does NOT launch the app:
# services should only run when a developer asks for them.
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p data/cache
printf "DerivLab ready. Run: streamlit run app.py --server.port 8501\n"
