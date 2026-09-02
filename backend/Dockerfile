# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS python-deps
ARG BUILD_SOURCE_REVISION=local-dev
ARG BUILD_ID=local-dev
ARG TARGETPLATFORM=linux/unknown
ARG BUILD_IMAGE_DIGEST=
ENV BUILD_SOURCE_REVISION=${BUILD_SOURCE_REVISION}
ENV BUILD_ID=${BUILD_ID}
ENV BUILD_PLATFORM=${TARGETPLATFORM}
ENV BUILD_IMAGE_DIGEST=${BUILD_IMAGE_DIGEST}
WORKDIR /app
COPY backend/docker/normalize_secrets_entrypoint.sh /usr/local/bin/normalize-secrets-entrypoint
RUN chmod 0555 /usr/local/bin/normalize-secrets-entrypoint
COPY pyproject.toml /app/
RUN --mount=type=cache,target=/root/.cache/pip \
    python -c "import subprocess, sys, tomllib; deps = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'setuptools>=69', 'wheel', *deps])"
ENV PYTHONPATH=/app/backend
ENTRYPOINT ["/usr/local/bin/normalize-secrets-entrypoint"]

FROM python-deps AS claude-runtime
RUN --mount=type=cache,target=/root/.cache/pip \
    python -c "import subprocess, sys, tomllib; deps = tomllib.load(open('/app/pyproject.toml', 'rb'))['project']['optional-dependencies']['python-runtime']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', *deps])"

FROM python-deps AS database-deps
RUN --mount=type=cache,target=/root/.cache/pip \
    python -c "import subprocess, sys, tomllib; optional = tomllib.load(open('/app/pyproject.toml', 'rb'))['project']['optional-dependencies']['database']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', *optional])"

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
COPY backend/app/modules /app/backend/app/modules
COPY backend/maintenance /app/backend/maintenance
COPY backend/migrations /app/backend/migrations
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps --no-build-isolation .
CMD ["python", "-m", "app.cli.migrate"]

FROM database-deps AS api-server
COPY backend/app/__init__.py backend/app/bootstrap.py backend/app/main.py /app/backend/app/
COPY backend/app/acceptance /app/backend/app/acceptance
COPY backend/app/cli /app/backend/app/cli
COPY backend/app/shared /app/backend/app/shared
COPY backend/app/modules /app/backend/app/modules
COPY backend/migrations /app/backend/migrations
COPY backend/seeds /app/backend/seeds
COPY contracts/agent-runtime/v1.4 /app/contracts/agent-runtime/v1.4
COPY contracts/agent-runtime/v1.5 /app/contracts/agent-runtime/v1.5
COPY .claude/skills /app/.claude/skills
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
COPY backend/app/modules/document_processing /app/backend/app/modules/document_processing
COPY backend/app/modules/external_action /app/backend/app/modules/external_action
COPY backend/app/modules/dingding/__init__.py /app/backend/app/modules/dingding/
COPY backend/app/modules/dingding/application /app/backend/app/modules/dingding/application
COPY backend/app/modules/dingding/infrastructure /app/backend/app/modules/dingding/infrastructure
COPY backend/app/modules/file_workspace /app/backend/app/modules/file_workspace
COPY backend/app/modules/identity /app/backend/app/modules/identity
COPY backend/app/modules/identity_discovery /app/backend/app/modules/identity_discovery
COPY backend/app/modules/mcp_tool_runtime /app/backend/app/modules/mcp_tool_runtime
COPY backend/app/modules/job/__init__.py /app/backend/app/modules/job/
COPY backend/app/modules/job/application /app/backend/app/modules/job/application
COPY backend/app/modules/job/domain /app/backend/app/modules/job/domain
COPY backend/app/modules/job/infrastructure /app/backend/app/modules/job/infrastructure
COPY backend/app/modules/managed_channel /app/backend/app/modules/managed_channel
COPY backend/app/modules/message_bus /app/backend/app/modules/message_bus
COPY backend/app/modules/model_connection /app/backend/app/modules/model_connection
COPY backend/app/modules/permission /app/backend/app/modules/permission
COPY backend/app/modules/platform_config /app/backend/app/modules/platform_config
COPY backend/app/modules/workflow /app/backend/app/modules/workflow
COPY backend/app/modules/webhook /app/backend/app/modules/webhook
COPY backend/app/workers /app/backend/app/workers
COPY backend/migrations /app/backend/migrations
COPY backend/seeds /app/backend/seeds
COPY contracts/agent-runtime/v1.4 /app/contracts/agent-runtime/v1.4
COPY contracts/agent-runtime/v1.5 /app/contracts/agent-runtime/v1.5
COPY .claude/skills /app/.claude/skills
RUN python -c "import app.bootstrap; import app.workers.agent_job_worker; import app.workers.job_dispatch_worker; import app.workers.delivery_dispatch_worker; import app.workers.webhook_dispatch_worker; import app.workers.channel_dispatch_worker; import app.workers.file_worker; import app.workers.file_processing_worker"
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps --no-build-isolation .
CMD ["python", "-m", "app.workers.agent_job_worker"]

FROM agent-worker AS file-processing-worker
USER root
RUN groupadd --system --gid 10006 file-processing-worker \
    && useradd --system --uid 10006 --gid 10006 --no-create-home file-processing-worker \
    && python -c "import app.workers.file_processing_worker"
USER 10006:10006
CMD ["python", "-m", "app.workers.file_processing_worker"]

FROM claude-runtime AS python-agent-runtime
COPY backend/app/__init__.py /app/backend/app/
COPY backend/app/python_runtime /app/backend/app/python_runtime
COPY backend/app/shared /app/backend/app/shared
COPY backend/app/modules/__init__.py /app/backend/app/modules/
COPY backend/app/modules/agent/__init__.py /app/backend/app/modules/agent/
COPY backend/app/modules/agent/domain /app/backend/app/modules/agent/domain
COPY backend/app/modules/agent/infrastructure/__init__.py /app/backend/app/modules/agent/infrastructure/
COPY backend/app/modules/agent/infrastructure/generated_runtime_contracts*.py backend/app/modules/agent/infrastructure/runtime_protocol.py backend/app/modules/agent/infrastructure/tool_manifest.py /app/backend/app/modules/agent/infrastructure/
COPY backend/app/modules/mcp_tool_runtime/__init__.py backend/app/modules/mcp_tool_runtime/contracts.py backend/app/modules/mcp_tool_runtime/manifest.py /app/backend/app/modules/mcp_tool_runtime/
# Keep this as a narrow namespace-package whitelist. Its __init__.py imports the repository layer.
COPY backend/app/modules/file_workspace/contracts.py backend/app/modules/file_workspace/domain.py backend/app/modules/file_workspace/text_format_policy.py /app/backend/app/modules/file_workspace/
COPY backend/app/modules/model_connection/__init__.py /app/backend/app/modules/model_connection/
COPY backend/app/modules/model_connection/domain /app/backend/app/modules/model_connection/domain
COPY backend/app/modules/model_connection/infrastructure/__init__.py backend/app/modules/model_connection/infrastructure/repository.py /app/backend/app/modules/model_connection/infrastructure/
COPY backend/app/modules/platform_config/__init__.py /app/backend/app/modules/platform_config/
COPY backend/app/modules/platform_config/domain /app/backend/app/modules/platform_config/domain
COPY backend/app/modules/platform_config/application/__init__.py backend/app/modules/platform_config/application/secrets.py backend/app/modules/platform_config/application/validation.py /app/backend/app/modules/platform_config/application/
COPY backend/app/modules/platform_config/infrastructure/__init__.py backend/app/modules/platform_config/infrastructure/repository.py /app/backend/app/modules/platform_config/infrastructure/
COPY contracts/agent-runtime/v1.4 /app/contracts/agent-runtime/v1.4
COPY contracts/agent-runtime/v1.5 /app/contracts/agent-runtime/v1.5
RUN groupadd --system --gid 10002 python-runtime \
    && useradd --system --uid 10002 --gid 10002 --no-create-home python-runtime \
    && python -c "import app.python_runtime; import app.python_runtime.file_transfer_http; import app.modules.agent.infrastructure.runtime_protocol; from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST; from mcp import types; from app.python_runtime.claude_client import claude_cli_version, claude_sdk_version; from app.python_runtime.file_mcp_bridge import _mcp_list_tools_next_cursor, _mcp_tool_input_schema; assert MCP_TOOL_MANIFEST; assert claude_sdk_version() != 'unknown'; assert claude_cli_version() not in {'unknown', 'unavailable'}; assert _mcp_tool_input_schema(types.Tool(name='probe', inputSchema={})) == {}; assert _mcp_list_tools_next_cursor(types.ListToolsResult(tools=[])) == ''"
USER 10002:10002
CMD ["python", "-m", "uvicorn", "app.python_runtime.service:create_app", "--factory", "--host", "0.0.0.0", "--port", "8091"]

FROM api-server AS tool-mcp
USER root
ARG DEBIAN_MIRROR=https://mirrors.aliyun.com/debian
ARG DEBIAN_SECURITY_MIRROR=https://mirrors.aliyun.com/debian-security
ENV DEBIAN_MIRROR=${DEBIAN_MIRROR}
ENV DEBIAN_SECURITY_MIRROR=${DEBIAN_SECURITY_MIRROR}
ENV ORACLE_CLIENT_LIB_DIR=/opt/oracle/instantclient
COPY backend/vendor/oracle/ /tmp/oracle-vendor/
COPY backend/docker/setup_oracle_client.sh /tmp/setup_oracle_client.sh
COPY backend/docker/verify_oracle_client.py /tmp/verify_oracle_client.py
RUN --mount=type=cache,target=/root/.cache/pip \
    python -c "import subprocess, sys, tomllib; deps = tomllib.load(open('/app/pyproject.toml', 'rb'))['project']['optional-dependencies']['tool-mcp']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', *deps])" \
    && chmod +x /tmp/setup_oracle_client.sh /tmp/verify_oracle_client.py \
    && ORACLE_VENDOR_DIR=/tmp/oracle-vendor /tmp/setup_oracle_client.sh \
    && rm -f /tmp/setup_oracle_client.sh /tmp/verify_oracle_client.py \
    && groupadd --system --gid 10001 tool-mcp \
    && useradd --system --uid 10001 --gid 10001 --no-create-home tool-mcp
ENV LD_LIBRARY_PATH=/opt/oracle/instantclient
COPY backend/app/services /app/backend/app/services
RUN python -c "import app.services.tool_mcp"
USER 10001:10001
CMD ["python", "-m", "uvicorn", "app.services.tool_mcp:create_default_app", "--factory", "--host", "0.0.0.0", "--port", "9103"]

FROM api-server AS ones-mcp
USER root
COPY services /app/services
RUN --mount=type=cache,target=/root/.cache/pip \
    python -c "import subprocess, sys, tomllib; deps = tomllib.load(open('/app/pyproject.toml', 'rb'))['project']['optional-dependencies']['ones-mcp']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', *deps])" \
    && groupadd --system --gid 10003 ones-mcp \
    && useradd --system --uid 10003 --gid 10003 --no-create-home ones-mcp \
    && python -c "import services.ones_mcp_server.app"
USER 10003:10003
CMD ["python", "-m", "services.ones_mcp_server"]

FROM api-server AS dingtalk-mcp
USER root
COPY services /app/services
RUN --mount=type=cache,target=/root/.cache/pip \
    python -c "import subprocess, sys, tomllib; deps = tomllib.load(open('/app/pyproject.toml', 'rb'))['project']['optional-dependencies']['dingtalk-mcp']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', *deps])" \
    && groupadd --system --gid 10007 dingtalk-mcp \
    && useradd --system --uid 10007 --gid 10007 --no-create-home dingtalk-mcp \
    && python -c "import services.dingtalk_mcp_server.app; import services.dingtalk_mcp_server.worker; from services.ones_mcp_server.task_update_catalog import TaskUpdateFieldCatalog; TaskUpdateFieldCatalog.load()"
USER 10007:10007
CMD ["python", "-m", "services.dingtalk_mcp_server"]

FROM api-server AS file-service
USER root
COPY services /app/services
RUN --mount=type=cache,target=/root/.cache/pip \
    python -c "import subprocess, sys, tomllib; deps = tomllib.load(open('/app/pyproject.toml', 'rb'))['project']['optional-dependencies']['file-service']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', *deps])" \
    && groupadd --system --gid 10005 file-service \
    && useradd --system --uid 10005 --gid 10005 --no-create-home file-service \
    && python -c "import services.file_service.app"
USER 10005:10005
CMD ["python", "-m", "services.file_service"]
