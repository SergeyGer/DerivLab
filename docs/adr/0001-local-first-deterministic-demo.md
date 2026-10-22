## Status
Accepted · 2026-10-22

**Deciders:** DerivLab maintainers

## Context

DerivLab is used in classrooms, workshops, and demos where the network may be
unavailable and where repeating a result matters. A simulator that fails because
Yahoo Finance rate-limits, or that changes its lesson on every run, is not a
usable teaching tool.

## Decision

Run the complete experience from local data by default:

- ship a committed historical seed;
- cache refreshed data in a per-machine Parquet store;
- fall back to deterministic synthetic prices only as a clearly labelled last
  resort;
- use deterministic local models for every AI role when no key is configured;
- never make an external API call required for the core loop.

## Consequences

**Easier**

- Offline demos and reproducible classroom exercises.
- No account, broker, or market-data subscription.
- Fast first run from the bundled seed.

**Harder / accepted**

- The seed can become stale until refreshed.
- Synthetic fallback is not a market forecast.
- Live AI prose is an optional enhancement rather than a dependency.

## Alternatives considered

- **Cloud-only data** — brittle in classrooms and blocked networks.
- **Require an OpenAI key** — excludes most first-time users and breaks the
  no-key demo promise.
- **Randomized synthetic data** — visually alive but not reproducible.