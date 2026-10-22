## Status
Accepted · 2026-10-22

**Deciders:** DerivLab maintainers

## Context

The repository serves two audiences: a non-technical visitor who needs to
understand the value in seconds, and an engineer who needs exact behavior,
configuration, and design rationale. Mixing both in one README makes the first
screen dense and the technical details hard to find.

## Decision

Split documentation by purpose:

- **README** — the story, the demo, the outcomes, and a three-command start.
- **GitHub Wiki** — the manual: setup, architecture, AI, tests, deployment,
  security, troubleshooting; with a sidebar.
- **`docs/adr/`** — durable architecture decisions.
- **`docs/VERSIONING.md`** — release and compatibility policy.
- **`docs/DOCUMENTATION.md`** — how the documentation system itself works.
- **`scripts/validate_docs.py`** + **Docs workflow** — local link/ADR/version
  validation and external link checking.

## Consequences

**Easier**

- A visitor can decide in under a minute whether the project is for them.
- Engineers have one canonical place for implementation details.
- Decisions and releases have a traceable home.

**Harder / accepted**

- Two surfaces to keep in sync (README and Wiki).
- Wiki changes are not part of the main repository PR.
- The link checker must tolerate public-host rate limits.

## Alternatives considered

- **One giant README** — rejected by the non-technical audience test.
- **Docs site generator** — more infrastructure than this project needs now.
- **Wiki-only** — weak front door for a visual project.