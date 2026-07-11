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

FROM python-deps AS mock-internal-api-platform
COPY backend/app/__init__.py backend/app/mock_internal_api_platform.py /app/backend/app/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps --no-build-isolation .
CMD ["python", "-m", "uvicorn", "app.mock_internal_api_platform:create_app", "--factory", "--host", "0.0.0.0", "--port", "9000"]

FROM python-deps AS internal-api-platform
# Multi-dialect read-only gateway. DB drivers live only in this image.
# Oracle Instant Client (thick) is bundled when vendor/oracle provides the client;
# otherwise the image still builds and runs oracledb thin for local/dev.
#
# apt 只在真正需要 Instant Client 时执行，避免日常构建卡在 deb.debian.org。
# 需要 apt 时默认用阿里云 Debian 源，可用 build-arg 覆盖：
#   --build-arg DEBIAN_MIRROR=https://mirrors.aliyun.com/debian
#   --build-arg DEBIAN_SECURITY_MIRROR=https://mirrors.aliyun.com/debian-security
USER root
ARG DEBIAN_MIRROR=https://mirrors.aliyun.com/debian
ARG DEBIAN_SECURITY_MIRROR=https://mirrors.aliyun.com/debian-security
ENV DEBIAN_MIRROR=${DEBIAN_MIRROR}
ENV DEBIAN_SECURITY_MIRROR=${DEBIAN_SECURITY_MIRROR}
ENV ORACLE_CLIENT_LIB_DIR=/opt/oracle/instantclient
COPY backend/vendor/oracle/ /tmp/oracle-vendor/
COPY backend/docker/setup_oracle_client.sh /tmp/setup_oracle_client.sh
RUN chmod +x /tmp/setup_oracle_client.sh \
    && ORACLE_VENDOR_DIR=/tmp/oracle-vendor /tmp/setup_oracle_client.sh \
    && rm -f /tmp/setup_oracle_client.sh
ENV LD_LIBRARY_PATH=/opt/oracle/instantclient
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "pymysql>=1.1" "pymssql>=2.3" "oracledb>=2.2" "redis>=5.0"
COPY backend/app/__init__.py backend/app/internal_api_platform.py /app/backend/app/
COPY backend/app/agent_test_data /app/backend/app/agent_test_data
COPY backend/app/shared /app/backend/app/shared
COPY backend/app/modules/__init__.py /app/backend/app/modules/
COPY backend/app/modules/internal_api_platform /app/backend/app/modules/internal_api_platform
COPY backend/app/modules/platform_config /app/backend/app/modules/platform_config
COPY backend/app/modules/local_internal_api_platform /app/backend/app/modules/local_internal_api_platform
COPY backend/config /app/backend/config
COPY backend/migrations /app/backend/migrations
RUN python -c "import app.internal_api_platform; import app.modules.internal_api_platform.app"
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps --no-build-isolation .
CMD ["python", "-m", "uvicorn", "app.internal_api_platform:create_app", "--factory", "--host", "0.0.0.0", "--port", "9000"]

FROM python-deps AS agent-test-data-seeder
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "pymysql>=1.1" "pymssql>=2.3" "redis>=5.0"
COPY backend/app/__init__.py /app/backend/app/
COPY backend/app/agent_test_data /app/backend/app/agent_test_data
RUN python -c "import app.agent_test_data.seeder"
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps --no-build-isolation .
CMD ["python", "-m", "app.agent_test_data.seeder", "seed"]

FROM python-deps AS api-server
COPY backend/app/__init__.py backend/app/bootstrap.py backend/app/main.py /app/backend/app/
COPY backend/app/shared /app/backend/app/shared
COPY backend/app/modules /app/backend/app/modules
COPY backend/config /app/backend/config
COPY backend/migrations /app/backend/migrations
COPY backend/seeds /app/backend/seeds
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

FROM claude-runtime AS agent-worker
COPY backend/app/__init__.py backend/app/bootstrap.py /app/backend/app/
COPY backend/app/shared /app/backend/app/shared
COPY backend/app/modules/__init__.py /app/backend/app/modules/
COPY backend/app/modules/agent /app/backend/app/modules/agent
COPY backend/app/modules/audit /app/backend/app/modules/audit
COPY backend/app/modules/channel /app/backend/app/modules/channel
COPY backend/app/modules/delivery /app/backend/app/modules/delivery
COPY backend/app/modules/dingding/__init__.py /app/backend/app/modules/dingding/
COPY backend/app/modules/dingding/application /app/backend/app/modules/dingding/application
COPY backend/app/modules/dingding/infrastructure /app/backend/app/modules/dingding/infrastructure
COPY backend/app/modules/internal_tools /app/backend/app/modules/internal_tools
COPY backend/app/modules/internal_api_platform/__init__.py /app/backend/app/modules/internal_api_platform/
COPY backend/app/modules/internal_api_platform/domain /app/backend/app/modules/internal_api_platform/domain
COPY backend/app/modules/internal_api_platform/infrastructure/__init__.py backend/app/modules/internal_api_platform/infrastructure/secrets.py /app/backend/app/modules/internal_api_platform/infrastructure/
COPY backend/app/modules/job/__init__.py /app/backend/app/modules/job/
COPY backend/app/modules/job/application /app/backend/app/modules/job/application
COPY backend/app/modules/job/domain /app/backend/app/modules/job/domain
COPY backend/app/modules/job/infrastructure /app/backend/app/modules/job/infrastructure
COPY backend/app/modules/message_bus /app/backend/app/modules/message_bus
COPY backend/app/modules/permission /app/backend/app/modules/permission
COPY backend/app/modules/platform_config /app/backend/app/modules/platform_config
COPY backend/app/modules/workflow /app/backend/app/modules/workflow
COPY backend/app/workers /app/backend/app/workers
COPY backend/migrations /app/backend/migrations
COPY backend/seeds /app/backend/seeds
COPY .claude /app/.claude
RUN python -c "import app.bootstrap; import app.workers.agent_job_worker"
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
