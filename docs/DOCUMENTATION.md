# Documentation Infrastructure

DerivLab deliberately separates the front door from the manual.

| Surface | Audience | Content |
|---|---|---|
| [`README.md`](../README.md) | Visitor, educator, decision maker | Story, 80-second narrated demo film, screenshots, one-command start |
| [GitHub Wiki](https://github.com/SergeyGer/DerivLab/wiki) | Developer, operator | Setup, architecture, AI, models, tests, deployment, security |
| [`docs/adr/`](adr/README.md) | Maintainer | Durable architecture decisions |
| [`docs/VERSIONING.md`](VERSIONING.md) | Maintainer, integrator | SemVer, release artifacts, checklist |
| This page | Maintainer | How the documentation system is checked and maintained |

---

## One-click delivery

### GHCR

```bash
docker run --rm -p 8501:8501 ghcr.io/sergeyger/derivlab:latest
```

The image is built by `.github/workflows/publish-image.yml` for
`linux/amd64` and `linux/arm64`, tagged `latest`, the release version, and a
`sha-<short>` tag. It contains no API key and runs the deterministic local models
by default. After the first publish, verify the package is public before treating
the one-command path as a supported entry point.

### Streamlit Community Cloud

Live demo: <https://derivlab-pavyratzrx7won9iv4zmcg.streamlit.app/>

[One-click deploy](https://share.streamlit.io/deploy?repository=https://github.com/SergeyGer/DerivLab&branch=main&mainModule=app.py)
creates a hosted widget from `app.py`. The app works without secrets because the
AI Arena falls back to local models. After deploy, replace the badge link in the
README with the app's public URL.

Choose **Python 3.11** (recommended), or 3.10/3.12/3.13, in **Advanced
settings**. Community Cloud pins Python at deployment time and cannot change it
in place. The requirements include wheels for Python 3.10–3.13, so a correctly
deployed app installs cleanly and does not need a redeploy just for NumPy/SciPy.
The Docker image and CI use Python 3.11 as the supported production baseline.

---

## Link checking

Local validation:

```bash
python scripts/validate_docs.py
```

The Docs workflow runs the same script and then
[lychee](https://github.com/lycheeverse/lychee-action) against `README.md` and
`docs/`. External hosts are allowed to return `403`/`429` to tolerate rate limits.

The Wiki is a separate Git repository. Its links are checked by the same
practical rule: every page must be reachable from `_Sidebar.md`, and every
repository link uses the public GitHub URL.

---

## ADRs

Architecture decisions live in [`docs/adr/`](adr/README.md). The validator checks:

- every ADR contains Status, Context, Decision, Consequences;
- the index links every ADR file;
- ADR filenames follow the zero-padded sequence.

---

## Coverage

```bash
pytest -q --cov=derivlab --cov-report=term --cov-report=xml
coverage json -o coverage.json
python scripts/update_coverage_badge.py
python scripts/update_coverage_badge.py --check
```

The CI threshold is **80%**. The badge is generated from the measured total
(currently **85%**) and committed at `docs/badges/coverage.svg`.

---

## Social preview

GitHub's repository social preview is a **Settings → Social preview** upload and
does not expose a public REST/GraphQL mutation. The prepared asset is:

- [`docs/social-preview.png`](social-preview.png) — 1280×640, dark terminal
  aesthetic, AI Arena + model stack.

Upload it at:
<https://github.com/SergeyGer/DerivLab/settings/social-preview>

Until it is uploaded, GitHub uses its generated OpenGraph card. Keep the source
image in the repository so the social card is reviewable and reproducible.

> A GitHub token can manage the repository but cannot authenticate the web
> settings form. This one step intentionally remains a human UI action.

---

## Versioned and testable docs

- **Compatibility matrix:** [`docs/COMPATIBILITY.md`](COMPATIBILITY.md).
- **Release snapshots:** [`docs/versions/`](versions/README.md); the current
  `APP_VERSION` snapshot is mandatory.
- **Owners:** [`docs/OWNERS.md`](OWNERS.md) and `.github/CODEOWNERS`.
- **Feedback:** [documentation issue form](https://github.com/SergeyGer/DerivLab/issues/new?template=docs-feedback.yml).
- **LLM quality:** [`docs/LLM-QUALITY.md`](LLM-QUALITY.md) documents the
  acceptance pipeline, clamps, fallbacks, provenance, tests, and residual risks.
- **Quality gates:** the validator now checks local links, heading anchors, image
  alt text, Python snippet syntax, ADR structure, version snapshots, and
  governance files. Lychee checks external links.
- GitHub Wiki has no page-level analytics; the issue form is the explicit
  feedback channel, with repository traffic insights as the aggregate signal.

## Versioning

See [`docs/VERSIONING.md`](VERSIONING.md). The current release is **1.2.0**.
`CHANGELOG.md` is the source of truth for user-visible changes; the Wiki Release
Notes mirror the highlights.

---

## Adding documentation

1. Put visitor-facing copy in README, implementation details in the Wiki.
2. Add a decision to `docs/adr/` when the change is architectural.
3. Update `docs/VERSIONING.md` only when the release policy changes.
4. Run `python scripts/validate_docs.py` and the Docs workflow.
5. Update the Wiki sidebar if a new page is added.
