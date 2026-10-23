# Compatibility & Version Matrix

**Last verified:** 2026-10-23
**Current release:** 1.2.0

| Release | Status | Python | Streamlit | PyArrow | NumPy / SciPy | Plotly | GHCR |
|---|---|---:|---:|---:|---:|---:|---|
| **1.2.0** | **Current** | 3.10–3.13¹ | 1.54.0 | 23.0.1 | 2.2.6 / 1.15.3 | 5.24.1 | `latest`, `1.2.0` |
| 1.1.0 | Superseded (security) | 3.10–3.12 | 1.40.2 | 16.1.0 | 1.26.4 / 1.13.1 | 5.24.1 | `1.1.0` |
| 1.0.1 | Legacy | 3.10–3.12 | 1.40.2 | 16.1.0 | 1.26.4 / 1.13.1 | 5.24.1 | not published |

¹ The application supports Python 3.10–3.13. Docker, CI, and the Dev Container
use **Python 3.11** as the recommended production baseline.

## Verified runtimes

| Environment | Status | Notes |
|---|---|---|
| Docker / Compose | ✅ | `derivlab:1.2.0`, Python 3.11 |
| GHCR | ✅ | multi-arch `linux/amd64` + `linux/arm64` |
| Streamlit Community Cloud | ✅ | live demo; Python 3.10–3.13 compatible |
| Local Python 3.12 | ✅ | 248 tests |
| CI Python 3.11 | ✅ | lint, 248 tests, Docker health, Docs |
| CodeQL | ✅ | 0 open alerts |

## AI models

| Role | Verified model | Fallback |
|---|---|---|
| AlphaVanguard critic | OpenAI `gpt-4.1` | deterministic local critic |
| NewsWire | OpenAI `gpt-4.1-mini` | deterministic local newswire |
| Agent decisions | deterministic local policies | optional LLM mandate call |

`gpt-5` / `gpt-5-mini` require organization verification on the tested account.
The model stack in the app always shows the actual active model.

## Documentation versions

Version snapshots and release-specific notes are indexed in
[`docs/versions/`](versions/README.md). The live Wiki documents `main`; the
compatibility table above is the authoritative support matrix.

## Code check

```python
from derivlab.config import APP_VERSION

assert APP_VERSION
```
