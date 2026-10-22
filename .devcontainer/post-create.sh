#!/usr/bin/env bash
# Runs once when the Dev Container is created. It is safe to re-run.
set -euo pipefail

cd "$(dirname "$0")/.."

mkdir -p data/cache data/seed
python - <<'PY'
import importlib.util
required = ["streamlit", "pandas", "numpy", "scipy", "yfinance", "backtrader", "plotly", "pyarrow", "pytest"]
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    raise SystemExit("Missing packages: " + ", ".join(missing))
print("Python dependencies are ready.")
PY

if [ ! -d data/seed ] || [ -z "$(find data/seed -name '*.parquet' -print -quit 2>/dev/null)" ]; then
  echo "No bundled seed detected; downloading five years of data..."
  python -m derivlab.data_preprocessor --all --years 5 --output both --retries 3
fi

echo
echo "DerivLab Dev Container is ready."
echo "Start the app with: streamlit run app.py --server.port 8501"
echo "Run the test suite with: python -m pytest -q"
