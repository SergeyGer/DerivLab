# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# DerivLab - multi-stage, reproducible Streamlit image
# Base image intentionally matches the SRS: python:3.10-slim
# ---------------------------------------------------------------------------
ARG PYTHON_VERSION=3.10
ARG APP_VERSION=1.1.0

FROM python:${PYTHON_VERSION}-slim AS builder
ARG APP_VERSION
LABEL org.opencontainers.image.title="DerivLab" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.description="Options & futures strategy emulator with synthetic Black-Scholes chains" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/SergeyGer/DerivLab" \
      org.opencontainers.image.documentation="https://github.com/SergeyGer/DerivLab/wiki"

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# Native compilers are isolated in the builder so the runtime image stays lean.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc g++ \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/requirements.txt

# ---------------------------------------------------------------------------
# Runtime stage
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime
ARG APP_VERSION
LABEL org.opencontainers.image.title="DerivLab" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.description="Options & futures strategy emulator with synthetic Black-Scholes chains" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/SergeyGer/DerivLab" \
      org.opencontainers.image.documentation="https://github.com/SergeyGer/DerivLab/wiki"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:${PATH}" \
    HOME=/home/app \
    DERIVLAB_DATA_DIR=/app/data/cache \
    DERIVLAB_SEED_DIR=/app/data/seed \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home --shell /bin/bash app

WORKDIR /app
COPY --from=builder --chown=app:app /opt/venv /opt/venv
COPY --chown=app:app app.py ./
COPY --chown=app:app derivlab ./derivlab
COPY --chown=app:app .streamlit ./.streamlit
COPY --chown=app:app data/seed ./data/seed
RUN mkdir -p /app/data/cache /home/app/.streamlit \
    && chown -R app:app /app /home/app

USER app
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--server.fileWatcherType=none", \
     "--browser.gatherUsageStats=false"]
