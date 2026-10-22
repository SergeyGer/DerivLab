# Versioning & Releases

DerivLab follows **Semantic Versioning 2.0.0** for the application and the public
Python package surface.

```text
MAJOR.MINOR.PATCH
```

- **MAJOR** — incompatible behavior, a removed strategy, a breaking environment
  variable, or a changed report/news contract.
- **MINOR** — a new screen, strategy, model role, or backwards-compatible feature.
- **PATCH** — bug fixes, documentation, performance, or visual polish that does
  not change the public contract.

The current release is **1.2.0**.

---

## Release artifacts

A release is complete only when all of these exist:

| Artifact | Convention |
|---|---|
| Git tag | `vMAJOR.MINOR.PATCH` (for example `v1.2.0`) |
| GitHub Release | Title `DerivLab X.Y.Z — <theme>` with highlights and verification |
| GHCR image | `ghcr.io/sergeyger/derivlab:latest` and `:X.Y.Z` |
| CHANGELOG | A `## [X.Y.Z]` section with Added/Changed/Fixed |
| Wiki | Release Notes page updated |
| CI/CodeQL | Green on the release commit |
| Docs | Link/ADR/version checks green |

The image workflow also publishes a `sha-<short>` tag for traceability.

---

## Release checklist

1. Update `APP_VERSION` in `derivlab/config.py`.
2. Update the `Dockerfile` build arg and the Compose image tag.
3. Add the `CHANGELOG.md` section.
4. Update the Wiki Release Notes and any changed setup instructions.
5. Run:
   ```bash
   ruff check .
   pytest -q --cov=derivlab --cov-fail-under=80
   python scripts/update_coverage_badge.py --check
   python scripts/validate_docs.py
   ```
6. Open a pull request; all required checks must pass.
7. Merge to `main`, create the Git tag and GitHub Release.
8. Run **Publish image** with the version input, or push the tag.
9. Verify `docker run --rm -p 8501:8501 ghcr.io/sergeyger/derivlab:latest`
   becomes healthy.
10. Update the Wiki Release Notes with the release URL.

---

## Compatibility promises

- Environment variables are additive within a major version.
- Existing strategy keys and scenario IDs are stable within a major version.
- The report contract is stable within a major version; adding a section is a
  breaking change.
- The local model names are stable for reproducibility; changing their behavior
  is a minor release and must be called out.
- Deprecated configuration is documented for at least one minor release before
  removal.

---

## Documentation versioning

The Wiki reflects `main`. A release note page records the behavior at that tag.
ADRs are append-only: a changed decision gets a new ADR and supersedes the old
one rather than rewriting history.

---

## Hotfixes

A hotfix may ship as a PATCH from a short-lived branch. It still requires:

- a failing regression test;
- a green CI/CodeQL/Docs run;
- a changelog entry;
- the same tag and image conventions.
