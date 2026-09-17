FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
WORKDIR /app
ENV PYTHONPATH=/app/backend:/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1 TOKENIZERS_PARALLELISM=false \
    TORCH_FORCE_WEIGHTS_ONLY_LOAD=1
COPY backend/app/modules/knowledge/embedding_runtime.lock /tmp/requirements.lock
RUN --mount=type=cache,target=/root/.cache/pip pip install --require-hashes --no-deps -r /tmp/requirements.lock
COPY backend/app/__init__.py /app/backend/app/
COPY backend/app/modules/__init__.py /app/backend/app/modules/
COPY backend/app/modules/knowledge/__init__.py /app/backend/app/modules/knowledge/
COPY backend/app/modules/knowledge/vector_contract.py backend/app/modules/knowledge/embedding_model.json backend/app/modules/knowledge/embedding_runtime.lock /app/backend/app/modules/knowledge/
COPY services/__init__.py /app/services/
COPY services/knowledge_embedding /app/services/knowledge_embedding
RUN groupadd --gid 10007 embedding && useradd --uid 10007 --gid 10007 --no-create-home embedding \
    && mkdir /models && chown 10007:10007 /models
USER 10007:10007
CMD ["uvicorn", "services.knowledge_embedding.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8096", "--no-access-log", "--log-level", "critical"]
