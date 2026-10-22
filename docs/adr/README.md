# Architecture Decision Records

This directory is the durable decision log for DerivLab. Each ADR records a
choice, the context that forced it, and the consequences we accept.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-local-first-deterministic-demo.md) | Local-first, deterministic demo | Accepted |
| [0002](0002-backtrader-synthetic-options.md) | Backtrader + synthetic option chain | Accepted |
| [0003](0003-optional-llm-local-fallback.md) | Optional LLM with deterministic fallback | Accepted |
| [0004](0004-documentation-architecture.md) | README story, Wiki manual, ADR log | Accepted |
| [0005](0005-delivery-and-quality-gates.md) | GHCR delivery and quality gates | Accepted |

## Format

Each record uses:

- **Status** — proposed, accepted, superseded, or deprecated
- **Context** — the forces and constraints
- **Decision** — what we chose
- **Consequences** — what becomes easier, harder, or impossible
- **Alternatives considered** — the paths we did not take

## Adding a record

1. Copy the structure of an existing ADR.
2. Use the next four-digit number.
3. Add it to the index above.
4. Link it from the relevant Wiki page and pull request.
5. Run `python scripts/validate_docs.py`.

ADRs are never edited to hide a change of mind. Supersede an accepted record with
a new one and update its status.
