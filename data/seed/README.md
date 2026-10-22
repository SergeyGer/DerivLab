# Bundled demo seed

This folder contains the offline seed used by DerivLab demos:

- **14 instruments** from the SRS universe.
- **Five years** of adjusted daily OHLCV (start `2021-10-22`).
- **Parquet** format with a `DatetimeIndex` and `Open, High, Low, Close, Volume`.
- Generated with `python -m derivlab.data_preprocessor --all --years 5 --output both`.
- See `manifest.json` for row counts and the exact end date of each series.

Source: Yahoo Finance via `yfinance`. The data is provided for educational and
demonstration purposes only and remains subject to Yahoo Finance's terms.

The app prefers `data/cache` when it contains fresher files. Refresh it from the
**Data Vault** screen or with the preprocessor CLI. If both the cache and this
seed are missing and the network is unavailable, the simulator falls back to
deterministic synthetic prices and labels them clearly in the UI.
