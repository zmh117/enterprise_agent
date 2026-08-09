# syntax=docker/dockerfile:1.7
FROM python:3.12-slim
WORKDIR /app
COPY services/ones-mcp-server/requirements.lock /tmp/requirements.lock
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps --require-hashes -r /tmp/requirements.lock
COPY services/__init__.py /app/services/__init__.py
COPY services/mcp_common /app/services/mcp_common
COPY services/ones_mcp_server /app/services/ones_mcp_server
ENV PYTHONPATH=/app
USER 65532:65532
CMD ["python", "-m", "services.ones_mcp_server"]
