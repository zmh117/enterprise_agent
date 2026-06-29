FROM node:22-trixie-slim AS node-runtime

FROM python:3.12-slim

WORKDIR /app
COPY --from=node-runtime /usr/local/ /usr/local/
RUN node --version \
    && npm --version \
    && npm install -g @anthropic-ai/claude-code
COPY pyproject.toml /app/
COPY backend /app/backend
COPY .claude /app/.claude
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app/backend
