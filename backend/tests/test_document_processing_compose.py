from __future__ import annotations

from pathlib import Path

import yaml

from app.modules.document_processing.profile import DOCLING_LAYOUT_OCR_V2


ROOT = Path(__file__).resolve().parents[2]
DIGEST = "sha256:0244089785d5ccb7570dfaa593cdc81ec64a1aadc63ffa9dce065064b0a6a807"
PROCESSOR_VERSION = "v1.30.0+wps-null-zero-drawing.v1"
PROCESSOR_BUILD_DIGEST = "sha256:ea15a6fc35b991249180d9265e1a3406448855fe8134c61fc7d26dd046b93429"
MODEL_DIGEST = "sha256:9e53a21c25853b53fa0b46df02bb8ebad1d5087dee342d7ef412efecaad0912c"


def _compose() -> dict[str, object]:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_docling_image_is_digest_pinned_offline_nonroot_and_internal_only() -> None:
    compose = _compose()
    service = compose["services"]["docling-serve"]
    environment = service["environment"]

    assert service["image"] == "enterprise-agent/docling-serve:v1.30.0-layout-ocr-v2"
    assert service["build"] == {
        "context": ".",
        "dockerfile": "backend/docker/docling-serve/Dockerfile",
    }
    dockerfile = (ROOT / service["build"]["dockerfile"]).read_text(encoding="utf-8")
    assert f"FROM quay.io/docling-project/docling-serve:v1.30.0@{DIGEST}" in dockerfile
    assert "verify_model_bundle.py" in dockerfile
    assert service["user"] == "1001:0"
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["pids_limit"] == 256
    assert service["networks"] == ["document-processing"]
    assert "ports" not in service
    assert service["expose"] == ["5001"]
    assert service["secrets"] == ["docling_api_key"]
    assert ":latest" not in service["image"]
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
    assert environment["DOCLING_SERVE_ENG_LOC_NUM_WORKERS"] == "2"
    assert environment["DOCLING_SERVE_ENABLE_REMOTE_SERVICES"] == "false"
    assert environment["DOCLING_SERVE_ALLOW_EXTERNAL_PLUGINS"] == "false"
    assert environment["DOCLING_SERVE_ALLOW_CUSTOM_VLM_CONFIG"] == "false"
    assert environment["DOCLING_SERVE_ALLOWED_SOURCE_TYPES"] == "[]"
    assert environment["DOCLING_SERVE_ALLOWED_TARGET_TYPES"] == '["inbody","zip"]'
    assert environment["DOCLING_SERVE_ALLOWED_IMAGE_EXPORT_MODES"] == (
        '["placeholder","referenced"]'
    )
    assert environment["DOCLING_SERVE_MAX_FILE_SIZE"] == "26214400"
    assert environment["DOCLING_SERVE_MAX_NUM_PAGES"] == "300"
    assert environment["DOCLING_SERVE_MAX_DOCUMENT_TIMEOUT"] == "600"
    assert environment["HF_HUB_OFFLINE"] == "1"
    assert environment["TRANSFORMERS_OFFLINE"] == "1"
    assert environment["DOCLING_MODEL_ARTIFACT_DIGEST"] == MODEL_DIGEST
    assert environment["DOCLING_MODEL_ARTIFACT_DIGEST"] == str(
        DOCLING_LAYOUT_OCR_V2.layout_ocr_options["model_artifact"]["digest"]
    )
    assert environment["DOCLING_SERVE_LOAD_MODELS_AT_BOOT"] == "true"
    assert "DOCLING_SERVE_API_KEY" not in environment
    assert "/run/secrets/docling_api_key" in service["command"][0]
    assert "verify_model_bundle.py" in service["command"][0]


def test_file_service_freezes_docling_and_docx_compatibility_build_identity() -> None:
    file_service = _compose()["services"]["file-service"]

    assert file_service["environment"]["DOCUMENT_PROCESSOR_VERSION"] == PROCESSOR_VERSION
    assert file_service["environment"]["DOCUMENT_PROCESSOR_BUILD_DIGEST"] == PROCESSOR_BUILD_DIGEST


def test_profile_identity_is_code_published_not_an_environment_parameter() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "DOCUMENT_LAYOUT_OCR_PROFILE_HASH=" not in env_example

    for service in _compose()["services"].values():
        environment = service.get("environment", {})
        assert "DOCUMENT_LAYOUT_OCR_PROFILE_HASH" not in environment


def test_processing_worker_has_only_queue_file_service_identity_and_docling_boundaries() -> None:
    services = _compose()["services"]
    worker = services["file-processing-worker"]
    second_worker = services["file-processing-worker-2"]
    environment = worker["environment"]

    assert second_worker == worker
    assert worker["image"] == ("enterprise-agent/file-processing-worker:docling-concurrency-2")

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
    assert environment["DOCLING_SERVE_MAX_RESPONSE_BYTES"] == "134217728"
    assert environment["DOCUMENT_LAYOUT_OCR_ENABLED"] == "true"
    assert "DOCUMENT_LAYOUT_OCR_PROFILE_HASH" not in environment
    assert "DOCLING_MODEL_ARTIFACT_DIGEST" not in environment
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
    assert worker["deploy"]["resources"]["limits"] == {
        "cpus": "1.0",
        "memory": "2G",
        "pids": 128,
    }


def test_processing_topology_adds_no_redis_rq_ray_file_mcp_or_host_docling_port() -> None:
    compose = _compose()
    services = compose["services"]
    assert "redis" not in services
    assert "file-mcp" not in services
    assert "docling-server" not in services
    assert sorted(name for name in services if name.startswith("file-processing-worker")) == [
        "file-processing-worker",
        "file-processing-worker-2",
    ]
    assert [name for name in services if name.startswith("docling-serve")] == ["docling-serve"]
    worker = services["file-processing-worker"]
    docling = services["docling-serve"]
    combined = str({"worker": worker, "docling": docling}).lower()
    assert "eng_kind': 'rq" not in combined
    assert "eng_kind': 'ray" not in combined
    assert "redis_url" not in combined
    assert "ports" not in docling
    migration = (
        ROOT / "backend/migrations/121_expand_docling_processing_concurrency.sql"
    ).read_text(encoding="utf-8")
    assert "VALUES (1, CURRENT_TIMESTAMP), (2, CURRENT_TIMESTAMP)" in migration
    assert DOCLING_LAYOUT_OCR_V2.layout_ocr_options["limits"]["max_global_docling_concurrency"] == 2


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
