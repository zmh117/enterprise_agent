from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DIGEST = "sha256:0244089785d5ccb7570dfaa593cdc81ec64a1aadc63ffa9dce065064b0a6a807"


def _compose() -> dict[str, object]:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_docling_image_is_digest_pinned_offline_nonroot_and_internal_only() -> None:
    compose = _compose()
    service = compose["services"]["docling-serve"]
    environment = service["environment"]

    assert service["image"] == ("quay.io/docling-project/docling-serve:v1.30.0@" + DIGEST)
    assert service["user"] == "1001:0"
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["pids_limit"] == 256
    assert service["networks"] == ["document-processing"]
    assert "ports" not in service
    assert service["expose"] == ["5001"]
    assert service["secrets"] == ["docling_api_key"]
    assert "@sha256:" in service["image"] and ":latest" not in service["image"]
    assert compose["networks"]["document-processing"]["internal"] is True
    assert service["deploy"]["resources"]["limits"] == {
        "cpus": "4.0",
        "memory": "8G",
        "pids": 256,
    }
    assert service["tmpfs"]
    assert service["healthcheck"]["test"][-1].find("/ready") >= 0

    assert environment["DOCLING_DEVICE"] == "cpu"
    assert environment["DOCLING_SERVE_ENG_KIND"] == "local"
    assert environment["DOCLING_SERVE_ENG_LOC_NUM_WORKERS"] == "1"
    assert environment["DOCLING_SERVE_ENABLE_REMOTE_SERVICES"] == "false"
    assert environment["DOCLING_SERVE_ALLOW_EXTERNAL_PLUGINS"] == "false"
    assert environment["DOCLING_SERVE_ALLOW_CUSTOM_VLM_CONFIG"] == "false"
    assert environment["DOCLING_SERVE_ALLOWED_SOURCE_TYPES"] == "[]"
    assert environment["DOCLING_SERVE_ALLOWED_TARGET_TYPES"] == '["inbody"]'
    assert environment["DOCLING_SERVE_MAX_FILE_SIZE"] == "26214400"
    assert environment["DOCLING_SERVE_MAX_NUM_PAGES"] == "300"
    assert environment["DOCLING_SERVE_MAX_DOCUMENT_TIMEOUT"] == "600"
    assert environment["HF_HUB_OFFLINE"] == "1"
    assert environment["TRANSFORMERS_OFFLINE"] == "1"
    assert "DOCLING_SERVE_API_KEY" not in environment
    assert "/run/secrets/docling_api_key" in service["command"][0]


def test_processing_worker_has_only_queue_file_service_identity_and_docling_boundaries() -> None:
    services = _compose()["services"]
    worker = services["file-processing-worker"]
    environment = worker["environment"]

    assert worker["build"]["target"] == "file-processing-worker"
    assert worker["user"] == "10006:10006"
    assert worker["read_only"] is True
    assert worker["cap_drop"] == ["ALL"]
    assert worker["security_opt"] == ["no-new-privileges:true"]
    assert worker["pids_limit"] == 128
    assert set(worker["networks"]) == {"default", "document-processing"}
    assert set(worker["secrets"]) == {
        "file_processing_worker_bootstrap_token",
        "docling_api_key",
    }
    assert environment["FILE_PROCESSING_WORKER_CONCURRENCY"] == "1"
    assert environment["FILE_PROCESSING_WORKER_READINESS_HOST"] == "0.0.0.0"
    assert environment["FILE_PROCESSING_WORKER_READINESS_PORT"] == "9106"
    assert worker["expose"] == ["9106"]
    assert "ports" not in worker
    assert environment["FILE_PROCESSING_MAX_ATTEMPTS"] == "3"
    assert environment["DOCLING_SERVE_TOTAL_TIMEOUT_SECONDS"] == "600"
    assert environment["FILE_PROCESSING_WORKER_BOOTSTRAP_TOKEN_FILE"] == (
        "/run/secrets/file_processing_worker_bootstrap_token"
    )
    assert environment["DOCLING_SERVE_API_KEY_FILE"] == "/run/secrets/docling_api_key"
    for forbidden in (
        "DATABASE_DSN",
        "APP_CONFIG_MASTER_KEY_FILE",
        "FILE_STORAGE_ENDPOINT_URL",
        "FILE_STORAGE_ACCESS_KEY_REF",
        "FILE_STORAGE_SECRET_KEY_REF",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "PRINCIPAL_JWT_PRIVATE_KEY_FILE",
    ):
        assert forbidden not in environment
    assert "postgres" not in worker["depends_on"]
    assert "minio" not in worker["depends_on"]
    assert worker["depends_on"]["docling-serve"]["condition"] == "service_healthy"
    assert worker["depends_on"]["file-service"]["condition"] == "service_healthy"
    assert worker["depends_on"]["rabbitmq"]["condition"] == "service_healthy"
    assert worker["healthcheck"]["test"][-1].find("/ready") >= 0


def test_processing_topology_adds_no_redis_rq_ray_file_mcp_or_host_docling_port() -> None:
    compose = _compose()
    services = compose["services"]
    assert "redis" not in services
    assert "file-mcp" not in services
    assert "docling-server" not in services
    worker = services["file-processing-worker"]
    docling = services["docling-serve"]
    combined = str({"worker": worker, "docling": docling}).lower()
    assert "eng_kind': 'rq" not in combined
    assert "eng_kind': 'ray" not in combined
    assert "redis_url" not in combined
    assert "ports" not in docling


def test_processing_secrets_are_generated_as_files_and_never_have_example_values() -> None:
    compose = _compose()
    secrets = compose["secrets"]
    assert set(secrets) >= {
        "file_processing_worker_bootstrap_token",
        "docling_api_key",
    }
    assert "file" in secrets["file_processing_worker_bootstrap_token"]
    assert "file" in secrets["docling_api_key"]
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "FILE_PROCESSING_WORKER_BOOTSTRAP_TOKEN_FILE=" in env_example
    assert "DOCLING_SERVE_API_KEY_FILE=" in env_example
    assert "DOCLING_SERVE_API_KEY=replace" not in env_example
    script = (ROOT / "scripts/bootstrap_agent_runtime_secrets.sh").read_text(encoding="utf-8")
    assert "file-processing-worker-bootstrap-token" in script
    assert "docling-api-key" in script
