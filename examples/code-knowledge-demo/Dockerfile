FROM python:3.12-slim AS web
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY web.py ui.html /app/
CMD ["python", "web.py"]

FROM python:3.12-slim AS worker
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends subversion \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY analyzer.py worker.py test_demo.py /app/
COPY fixtures /app/fixtures
CMD ["python", "worker.py"]
