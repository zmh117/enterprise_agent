# syntax=docker/dockerfile:1.7

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r /app/requirements.txt

COPY mock_ones_api.py /app/mock_ones_api.py
COPY mock.yaml /app/mock.yaml

ENV ONES_MOCK_CONFIG=/app/mock.yaml
RUN groupadd --system --gid 10004 ones-mock \
    && useradd --system --uid 10004 --gid 10004 --no-create-home ones-mock \
    && python -c "import mock_ones_api"
USER 10004:10004
EXPOSE 19121

CMD ["python", "-m", "uvicorn", "mock_ones_api:create_app", "--factory", "--host", "0.0.0.0", "--port", "19121"]
