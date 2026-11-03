FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
ARG TARGETARCH
WORKDIR /app
ENV PYTHONPATH=/app/backend:/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1 TOKENIZERS_PARALLELISM=false \
    TORCH_FORCE_WEIGHTS_ONLY_LOAD=1
COPY backend/app/modules/knowledge/embedding_runtime.lock backend/app/modules/knowledge/embedding_runtime_amd64.lock /tmp/
RUN --mount=type=cache,target=/root/.cache/pip \
    case "$TARGETARCH" in \
      arm64) lock=/tmp/embedding_runtime.lock ;; \
      amd64) lock=/tmp/embedding_runtime_amd64.lock ;; \
      *) echo "Unsupported reranker architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && pip install --require-hashes --no-deps -r "$lock" \
    && python -c "import platform, torch; assert platform.machine() in {'aarch64', 'x86_64'}; assert torch.version.cuda is None"
COPY backend/app/__init__.py /app/backend/app/
COPY backend/app/modules/__init__.py /app/backend/app/modules/
COPY backend/app/modules/knowledge/__init__.py /app/backend/app/modules/knowledge/
COPY backend/app/modules/knowledge/embedding_model.json backend/app/modules/knowledge/reranker_model.json backend/app/modules/knowledge/embedding_runtime.lock backend/app/modules/knowledge/embedding_runtime_amd64.lock /app/backend/app/modules/knowledge/
COPY backend/app/modules/knowledge/domain/__init__.py backend/app/modules/knowledge/domain/vector_contract.py backend/app/modules/knowledge/domain/rerank_contract.py /app/backend/app/modules/knowledge/domain/
COPY backend/app/modules/knowledge/infrastructure/__init__.py backend/app/modules/knowledge/infrastructure/embedding_profile.py backend/app/modules/knowledge/infrastructure/reranker_profile.py /app/backend/app/modules/knowledge/infrastructure/
COPY services/__init__.py /app/services/
COPY services/knowledge_embedding/__init__.py services/knowledge_embedding/model_files.py services/knowledge_embedding/online_queue.py /app/services/knowledge_embedding/
COPY services/knowledge_reranker /app/services/knowledge_reranker
RUN groupadd --gid 10009 reranker && useradd --uid 10009 --gid 10009 --no-create-home reranker \
    && mkdir /models && chown 10009:10009 /models
USER 10009:10009
CMD ["uvicorn", "services.knowledge_reranker.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8097", "--no-access-log", "--log-level", "critical"]
