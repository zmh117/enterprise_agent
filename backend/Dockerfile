FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml /app/
COPY backend /app/backend
COPY .claude /app/.claude
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app/backend
