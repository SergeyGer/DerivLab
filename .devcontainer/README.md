# DerivLab Dev Container

This folder is the zero-setup development environment for VS Code and the
Microsoft **Dev Containers** extension.

## Open it

1. Install Docker Desktop (or Docker Engine + Compose) and the
   [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)
   extension.
2. Clone the repository and open the folder in VS Code.
3. Run **Dev Containers: Reopen in Container** from the Command Palette.
4. Wait for the post-create script to finish. Dependencies and the bundled
   seed data are already available.
5. Start the app:

   ```bash
   streamlit run app.py --server.port 8501
   ```

   VS Code forwards port **8501** and can open the preview automatically.

## Why this works for a distributed team

- The same pinned `requirements.txt` and Python 3.11 image are used on Windows,
  macOS Intel, Apple Silicon, and Linux.
- The workspace is bind-mounted through `${localWorkspaceFolder}` — there are no
  absolute host paths in the configuration.
- The seed data ships in the repository, so first boot works offline.
- The runtime cache lives in the developer's own `data/cache` directory. It is
  gitignored, so two laptops never share history accidentally.
- `shutdownAction: stopContainer` means the dev container stops when VS Code
  closes. The app is **not** started automatically and has no restart policy.
- Python tooling, the pytest configuration, VS Code tasks, and debugging are
  committed under `.vscode/` for a consistent workflow.

## Useful commands

```bash
make run          # start Streamlit
make test         # run pytest
make seed         # refresh five years of Yahoo Finance data
make lint         # ruff
```

## Troubleshooting

- **Port already in use**: stop the other Streamlit process or forward 8501 to a
  different local port in VS Code.
- **Permission denied in data/cache**: rebuild the container; the post-create
  script re-creates the directory with the developer user's ownership.
- **No internet**: the app still runs from `data/seed`. Use the Data Vault screen
  or `make seed` when the network returns.
- **Apple Silicon**: the base image and all wheels are multi-architecture. If a
  package is missing for arm64, rebuild with `--platform=linux/arm64`.
