# syntax=docker/dockerfile:1.7
# Developer image: same Python/runtime pins as production, plus dev tooling.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:${PATH}" \
    DERIVLAB_DATA_DIR=/workspaces/DerivLab/data/cache \
    DERIVLAB_SEED_DIR=/workspaces/DerivLab/data/seed

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
        procps \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
RUN printf 'export PATH="/opt/venv/bin:$PATH"\nexport DERIVLAB_DATA_DIR=/workspaces/DerivLab/data/cache\nexport DERIVLAB_SEED_DIR=/workspaces/DerivLab/data/seed\n' \
    > /etc/profile.d/derivlab.sh \
    && chmod 0644 /etc/profile.d/derivlab.sh
COPY requirements.txt requirements-dev.txt /tmp/
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/requirements-dev.txt

RUN useradd --uid 1000 --create-home --shell /bin/bash developer \
    && mkdir -p /workspaces/DerivLab/data/cache \
    && chown -R developer:developer /workspaces/DerivLab /opt/venv

USER developer
WORKDIR /workspaces/DerivLab

EXPOSE 8501
