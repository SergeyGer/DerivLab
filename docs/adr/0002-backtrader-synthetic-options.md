## Status
Accepted · 2026-10-22

**Deciders:** DerivLab maintainers

## Context

The project needs an event-driven simulation with expiries, assignment, fees,
rolling, and a trade ledger, but no free historical option chain is available for
fourteen instruments over five years.

## Decision

Use Backtrader as the event loop and a private portfolio ledger, with a synthetic
option chain built from 30-day realized volatility and Black-Scholes pricing. The
same controller powers Backtest Lab, Hold the Position, and the AI Arena.

The ledger records option kind, strike, expiry, and cash flows so the UI and the
AI trigger layer can reason about breaches and assignments.

## Consequences

**Easier**

- Consistent accounting across all four desks and the game.
- Full control over expiries, assignment, fees, and rolling.
- Deterministic replay and testability.

**Harder / accepted**

- No bid-ask spread, open interest, volatility surface, or early exercise.
- Basis convergence is idealized.
- Results are educational, not executable.

## Alternatives considered

- **Real option data** — expensive, incomplete for the asset list, and fragile
  offline.
- **Vectorized backtest only** — simpler, but cannot model the daily
  hold/roll/assign loop that the game needs.
- **Custom event loop from scratch** — more control, but higher maintenance and
  less recognizable to contributors.