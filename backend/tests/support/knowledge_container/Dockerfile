# Tests stay outside production images. Build the production ONES target first.
FROM enterprise-agent-knowledge-acceptance-ones:local
USER root
RUN pip install --no-cache-dir "pytest>=8,<10"
COPY backend/tests /app/backend/tests
COPY backend/app/python_runtime /app/backend/app/python_runtime
ENV PYTHONPATH=/app/backend:/app
