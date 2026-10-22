## Status
Accepted · 2026-10-22

**Deciders:** DerivLab maintainers

## Context

The AI Arena needs an institutional critic and a news wire. A live LLM makes the
experience more compelling, but API availability, cost, latency, and output
quality cannot be guaranteed. A failed model call must never break a simulation.

## Decision

Treat the LLM as an optional orchestration layer:

- three deterministic local models are the default;
- every LLM call returns a structured result and never raises into the UI;
- reports are validated against three exact headings;
- news is validated as JSON;
- decisions are clamped field by field and fall back per agent;
- the active model, provider, source, latency, and fallback reason are visible in
  the UI.

## Consequences

**Easier**

- The arena is fully usable offline and in CI.
- A bad model response becomes a local result, not a crash.
- Users can see exactly which model produced a verdict.

**Harder / accepted**

- Local prose is less varied than a frontier model.
- Strict validation can reject an otherwise interesting model output.
- Model availability varies by organization; GPT-5 may require verification.

## Alternatives considered

- **LLM-only** — unacceptable availability and cost risk.
- **Silent fallback** — hides failure and damages trust; rejected.
- **Let the LLM choose unconstrained fields** — unsafe and unreproducible.