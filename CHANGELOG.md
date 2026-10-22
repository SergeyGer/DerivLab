# Changelog

All notable changes to DerivLab are documented here.

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
