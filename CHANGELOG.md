# Changelog

All notable changes to DerivLab are documented here.

## [1.1.0] - 2026-10-22

### Added

- **AI Arena.** A new screen where three autonomous rival desks trade the same
  historical scenario as the user. The desks choose their own strategies and
  parameters from a pre-simulation market context.
- **AlphaVanguard AI performance review.** A strict three-section Markdown report
  comparing the user portfolio, the AlphaVanguard rival portfolio, the whole
  leaderboard, and the critical trigger timeline.
- **Cyberpunk NewsWire.** A four-item market wire generated from the cycle's
  metrics, model names, and critical events.
- **Optional LLM orchestration.** OpenAI-compatible and Anthropic endpoints,
  role-specific decision/critic/news models, JSON validation, and automatic
  fallback to deterministic local models. Active model names are shown in the
  sidebar, arena cards, leaderboard, report header, and model-stack panel.
- **Async agent bridge.** Backtrader breach and assignment events are emitted to
  an `AIAgentBridge`; an optional asyncio loop dispatches them with
  `run_coroutine_threadsafe`, matching the SRS integration template.
- Model recommendation catalog for frontier, fast/cheap, and offline deployments.
- Regression tests for personas, policies, LLM HTTP clients, JSON parsing,
  report/news fallbacks, arena scoring, bridge events, and the AI Arena UI.
- **One-command delivery.** Multi-arch GHCR image, `docker run` Quick Start, and
  a Streamlit Community Cloud one-click deploy badge.
- **Coverage signal.** CI coverage gate (80%), generated badge (85%), and report
  artifacts.
- **Documentation infrastructure.** Docs workflow with local link/ADR/version
  checks, lychee external-link checking, ADR log, versioning policy, and a
  1280×640 social preview asset.

### Changed

- Backtest NAV now carries the spot price, and trade records carry option
  metadata (kind, strike, expiry) for trigger analysis.
- Version bumped to 1.1.0; Docker image tag and Compose service updated.

## [1.0.1] - 2026-10-22

### Fixed

- **Hold the Position frontend stability.** Eliminated the intermittent browser
  `NotFoundError: Failed to execute 'removeChild' on 'Node'` error by:
  - using stable Plotly component keys instead of recreating the chart every tick,
  - keeping the game fragment mounted with a constant one-second timer,
  - removing full-app `st.rerun()` calls from automatic alert and finish transitions,
  - keeping a constant number of Plotly traces while the tape advances.
- **Browser auto-translation guard.** The terminal now sets Google/Edge
  `notranslate` markers and `translate="no"` on the document so machine
  translation cannot mutate the React DOM during live updates.

### Changed

- Game decisions and playback controls update on the next one-second fragment
  tick instead of tearing down and rebuilding the page.
- README troubleshooting now documents the frontend/translation failure mode.

## [1.0.0] - 2026-10-22

### Added

- Initial DerivLab release: five strategies, 14 instruments, synthetic
  Black-Scholes option chains, Backtrader event loop, Streamlit terminal,
  Hold-the-Position game, Data Vault, Docker stack, Dev Containers, CI, tests,
  bundled five-year seed, and documentation.
