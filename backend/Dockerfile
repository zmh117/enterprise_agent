# syntax=docker/dockerfile:1.7

FROM node:22-trixie-slim AS node-runtime

FROM python:3.12-slim AS python-deps
WORKDIR /app
COPY pyproject.toml /app/
RUN --mount=type=cache,target=/root/.cache/pip \
    python -c "import subprocess, sys, tomllib; deps = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'setuptools>=69', 'wheel', *deps])"
ENV PYTHONPATH=/app/backend

FROM python-deps AS claude-runtime
COPY --from=node-runtime /usr/local/ /usr/local/
RUN --mount=type=cache,target=/root/.npm \
    node --version \
    && npm --version \
    && npm install -g @anthropic-ai/claude-code

FROM python-deps AS agent-test-data-seeder
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "pymysql>=1.1" "pymssql>=2.3" "redis>=5.0"
COPY backend/app/__init__.py /app/backend/app/
COPY backend/app/agent_test_data /app/backend/app/agent_test_data
RUN python -c "import app.agent_test_data.seeder"
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps --no-build-isolation .
CMD ["python", "-m", "app.agent_test_data.seeder", "seed"]

FROM python-deps AS migrator
COPY backend/app/__init__.py /app/backend/app/
COPY backend/app/cli /app/backend/app/cli
COPY backend/app/shared /app/backend/app/shared
COPY backend/migrations /app/backend/migrations
COPY backend/maintenance /app/backend/maintenance
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps --no-build-isolation .
CMD ["python", "-m", "app.cli.migrate"]

FROM python-deps AS api-server
COPY backend/app/__init__.py backend/app/bootstrap.py backend/app/main.py /app/backend/app/
COPY backend/app/acceptance /app/backend/app/acceptance
COPY backend/app/cli /app/backend/app/cli
COPY backend/app/shared /app/backend/app/shared
COPY backend/app/modules /app/backend/app/modules
COPY backend/config /app/backend/config
COPY backend/migrations /app/backend/migrations
COPY backend/maintenance /app/backend/maintenance
COPY backend/seeds /app/backend/seeds
COPY services/__init__.py /app/services/
COPY services/mcp_common /app/services/mcp_common
COPY services/data_mcp_server/__init__.py services/data_mcp_server/contracts.py /app/services/data_mcp_server/
COPY services/ones_mcp_server/__init__.py services/ones_mcp_server/contracts.py /app/services/ones_mcp_server/
COPY config /app/config
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps --no-build-isolation .
CMD ["python", "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

FROM python-deps AS dingtalk-stream-ingress
COPY backend/app/__init__.py backend/app/bootstrap.py /app/backend/app/
COPY backend/app/shared /app/backend/app/shared
COPY backend/app/modules /app/backend/app/modules
COPY backend/app/workers /app/backend/app/workers
COPY backend/migrations /app/backend/migrations
COPY backend/seeds /app/backend/seeds
RUN python -c "import app.bootstrap; import app.workers.dingtalk_stream_ingress_worker"
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps --no-build-isolation .
CMD ["python", "-m", "app.workers.dingtalk_stream_ingress_worker"]

FROM python-deps AS agent-worker
COPY backend/app/__init__.py backend/app/bootstrap.py /app/backend/app/
COPY backend/app/cli /app/backend/app/cli
COPY backend/app/shared /app/backend/app/shared
COPY backend/app/modules/__init__.py /app/backend/app/modules/
COPY backend/app/modules/admin /app/backend/app/modules/admin
COPY backend/app/modules/agent /app/backend/app/modules/agent
COPY backend/app/modules/agent_config /app/backend/app/modules/agent_config
COPY backend/app/modules/attachments /app/backend/app/modules/attachments
COPY backend/app/modules/audit /app/backend/app/modules/audit
COPY backend/app/modules/authorization_center /app/backend/app/modules/authorization_center
COPY backend/app/modules/business_application /app/backend/app/modules/business_application
COPY backend/app/modules/channel /app/backend/app/modules/channel
COPY backend/app/modules/delivery /app/backend/app/modules/delivery
COPY backend/app/modules/dingding/__init__.py /app/backend/app/modules/dingding/
COPY backend/app/modules/dingding/application /app/backend/app/modules/dingding/application
COPY backend/app/modules/dingding/infrastructure /app/backend/app/modules/dingding/infrastructure
COPY backend/app/modules/identity /app/backend/app/modules/identity
COPY backend/app/modules/identity_discovery /app/backend/app/modules/identity_discovery
COPY backend/app/modules/job/__init__.py /app/backend/app/modules/job/
COPY backend/app/modules/job/application /app/backend/app/modules/job/application
COPY backend/app/modules/job/domain /app/backend/app/modules/job/domain
COPY backend/app/modules/job/infrastructure /app/backend/app/modules/job/infrastructure
COPY backend/app/modules/managed_channel /app/backend/app/modules/managed_channel
COPY backend/app/modules/mcp_resources /app/backend/app/modules/mcp_resources
COPY backend/app/modules/mcp_runtime /app/backend/app/modules/mcp_runtime
COPY backend/app/modules/mcp_tool_publications /app/backend/app/modules/mcp_tool_publications
COPY backend/app/modules/message_bus /app/backend/app/modules/message_bus
COPY backend/app/modules/model_connection /app/backend/app/modules/model_connection
COPY backend/app/modules/permission /app/backend/app/modules/permission
COPY backend/app/modules/platform_config /app/backend/app/modules/platform_config
COPY backend/app/modules/cutover /app/backend/app/modules/cutover
COPY backend/app/modules/workflow /app/backend/app/modules/workflow
COPY backend/app/modules/webhook /app/backend/app/modules/webhook
COPY services/__init__.py /app/services/
COPY services/mcp_common /app/services/mcp_common
COPY backend/app/workers /app/backend/app/workers
COPY backend/migrations /app/backend/migrations
COPY backend/seeds /app/backend/seeds
RUN python -c "import app.bootstrap; import app.workers.agent_job_worker; import app.workers.job_dispatch_worker; import app.workers.delivery_dispatch_worker; import app.workers.webhook_dispatch_worker; import app.workers.channel_dispatch_worker"
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps --no-build-isolation .
CMD ["python", "-m", "app.workers.agent_job_worker"]

FROM claude-runtime AS backend-runtime
COPY backend/app /app/backend/app
COPY backend/migrations /app/backend/migrations
COPY backend/seeds /app/backend/seeds
COPY .claude /app/.claude
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps --no-build-isolation .
