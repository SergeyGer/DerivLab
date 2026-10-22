## Status
Accepted · 2026-10-22

**Deciders:** DerivLab maintainers

## Context

Cloning and building is a reasonable developer workflow but a poor first-run
experience. The project also needs durable signals that a change is safe:
tests, container health, static analysis, and documentation checks.

## Decision

- Publish a multi-arch image to **GHCR** (`ghcr.io/sergeyger/derivlab:latest`)
  so the demo can start with `docker run`.
- Offer a **Streamlit Community Cloud** one-click deploy path for a zero-install
  widget; the local models make it work without secrets.
- Require four protected-branch checks: Python tests, Docker health, CodeQL, and the Docs link/ADR check.
- Add a **Docs** check for local link/ADR/version validation and external link
  checking.
- Keep `restart: "no"` for Compose services.
- Use `latest` plus immutable version/SHA tags for images.

## Consequences

**Easier**

- A visitor can try the product without cloning or building.
- A broken link or missing ADR fails a PR rather than being discovered later.
- The public demo and the local demo share the same image.

**Harder / accepted**

- Multi-arch builds take longer.
- The Streamlit public app still requires the owner to authorize the deployment.
- A public GHCR package must have public visibility; package settings are part of
  the release checklist.

## Alternatives considered

- **Docker Hub** — additional account and pull-rate limits.
- **Source-only install** — the problem this ADR exists to solve.
- **No docs checks** — link rot and decision drift.