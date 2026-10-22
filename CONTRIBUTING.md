# Contributing to DerivLab

Thanks for helping improve the simulator. The project is designed so that
developers on Windows, macOS (Intel or Apple Silicon), and Linux can work from
the same checkout.

## The 60-second setup

1. Install Docker and the VS Code **Dev Containers** extension.
2. Clone the repository and open it in VS Code.
3. Run **Dev Containers: Reopen in Container**.
4. Start the app with `make run` (or `streamlit run app.py --server.port 8501`).
5. Run the checks with `make test` and `make lint`.

The dev container pins Python 3.10 and all dependencies. It mounts the checkout
through `${localWorkspaceFolder}`, so no machine-specific paths are committed.
The bundled `data/seed` folder makes the first launch work offline.

## Working with data

- `data/seed/` is the committed, point-in-time demo snapshot.
- `data/cache/` is the per-developer runtime cache and is gitignored.
- Refresh your cache from the **Data Vault** screen or with `make seed`.
- Never commit downloaded history, cookies, logs, or `.env` files.

## Code expectations

- Keep all UI copy, comments, and documentation in English.
- Preserve the fallback chain: runtime cache → bundled seed → clearly labelled
  synthetic data. A network failure must never crash the app.
- Every new strategy or parameter combination needs a test that exercises it.
- Keep `restart: "no"` in `docker-compose.yml`. Automatic restart on server
  reboot is intentionally disabled.
- Run `make lint` and `make test` before opening a pull request.

## Branch and PR workflow

- Use a short descriptive branch, for example `feature/iron-condor-scoring`.
- Describe the user-facing change and the tests you ran.
- Screenshots are welcome for UI changes; store them in `docs/screenshots/`.
- Do not include generated caches or large raw data files.

## Reporting a problem

Include the page, instrument, strategy, selected parameters, and the exact
message shown in the UI. The Data Vault "Last refresh report" is useful for
download issues. Do not include secrets or private portfolio data.
