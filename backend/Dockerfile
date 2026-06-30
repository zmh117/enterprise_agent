# syntax=docker/dockerfile:1.7

FROM node:22-trixie-slim AS node-runtime

FROM python:3.12-slim

WORKDIR /app
COPY --from=node-runtime /usr/local/ /usr/local/
RUN --mount=type=cache,target=/root/.npm \
    node --version \
    && npm --version \
    && npm install -g @anthropic-ai/claude-code
COPY pyproject.toml /app/
RUN --mount=type=cache,target=/root/.cache/pip \
    python -c "import subprocess, sys, tomllib; deps = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'setuptools>=69', 'wheel', *deps])"
COPY backend /app/backend
COPY .claude /app/.claude
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps --no-build-isolation .
ENV PYTHONPATH=/app/backend
