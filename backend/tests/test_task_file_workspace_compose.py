from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _compose() -> dict[str, object]:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_compose_has_one_file_service_and_one_attachment_queue_consumer() -> None:
    compose = _compose()
    services = compose["services"]

    assert "file-service" in services
    assert services["file-service"]["build"]["target"] == "file-service"
    assert "file-worker" in services
    assert services["file-worker"]["command"] == [
        "python",
        "-m",
        "app.workers.file_worker",
    ]
    assert "attachment-worker" not in services
    assert "file-mcp" not in services
    assert "docling-server" not in services
    assert "docling-serve" not in services

    attachment_consumers = [
        name
        for name, service in services.items()
        if service.get("command")
        in (
            ["python", "-m", "app.workers.file_worker"],
            ["python", "-m", "app.workers.attachment_worker"],
        )
    ]
    assert attachment_consumers == ["file-worker"]


def test_minio_credentials_and_connections_stop_at_file_service_boundary() -> None:
    compose = _compose()
    services = compose["services"]
    direct_credential_services: set[str] = set()
    for name, service in services.items():
        environment = service.get("environment", {})
        if {"S3_ACCESS_KEY", "S3_SECRET_KEY"}.intersection(environment):
            direct_credential_services.add(name)
    assert direct_credential_services <= {"minio", "minio-init"}

    migrator = services["migrator"]
    assert {
        "app_config_master_key",
        "file_storage_bootstrap_access_key",
        "file_storage_bootstrap_secret_key",
    } <= set(migrator["secrets"])
    assert "bootstrap_file_storage_secrets" in migrator["command"][-1]

    file_environment = services["file-service"]["environment"]
    assert file_environment["FILE_STORAGE_ACCESS_KEY_REF"].startswith(
        "${FILE_STORAGE_ACCESS_KEY_REF:-secret://platform/"
    )
    assert file_environment["FILE_STORAGE_SECRET_KEY_REF"].startswith(
        "${FILE_STORAGE_SECRET_KEY_REF:-secret://platform/"
    )
    assert file_environment["FILE_STORAGE_BUCKET"] == (
        "${FILE_STORAGE_BUCKET:-agent-files}"
    )
    assert file_environment["FILE_STORAGE_LEGACY_ATTACHMENT_BUCKET"] == (
        "${S3_BUCKET:-agent-attachments}"
    )
    assert "S3_ACCESS_KEY" not in file_environment
    assert "S3_SECRET_KEY" not in file_environment

    for name in (
        "agent-worker",
        "typescript-agent-runtime",
        "python-agent-runtime",
        "file-worker",
        "delivery-dispatch-worker",
        "admin-web",
    ):
        service = services[name]
        environment = service.get("environment", {})
        assert not any(key.startswith("S3_") for key in environment), name
        assert "FILE_STORAGE_LEGACY_ATTACHMENT_BUCKET" not in environment, name
        assert "minio" not in service.get("depends_on", {}), name


def test_worker_identity_bootstrap_is_role_separated_and_file_service_is_hardened() -> None:
    services = _compose()["services"]
    file_service = services["file-service"]
    file_worker = services["file-worker"]
    delivery_worker = services["delivery-dispatch-worker"]

    assert file_service["read_only"] is True
    assert file_service["cap_drop"] == ["ALL"]
    assert file_service["security_opt"] == ["no-new-privileges:true"]
    assert set(file_service["secrets"]) == {
        "app_config_master_key",
        "principal_jwks",
    }
    assert "file_worker_bootstrap_token" in file_worker["secrets"]
    assert "delivery_worker_bootstrap_token" not in file_worker["secrets"]
    assert "delivery_worker_bootstrap_token" in delivery_worker["secrets"]
    assert "file_worker_bootstrap_token" not in delivery_worker["secrets"]
    assert "principal_jwt_private_key" not in file_worker["secrets"]
    assert "principal_jwt_private_key" not in delivery_worker["secrets"]

    api = services["api-server"]
    assert {
        "principal_jwt_private_key",
        "file_worker_bootstrap_token",
        "delivery_worker_bootstrap_token",
    } <= set(api["secrets"])
    assert file_worker["depends_on"]["api-server"]["condition"] == "service_healthy"
    assert delivery_worker["depends_on"]["api-server"]["condition"] == "service_healthy"

    compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "FILE_WORKER_PRINCIPAL_TOKEN_FILE" not in compose_text
    assert "DELIVERY_WORKER_PRINCIPAL_TOKEN_FILE" not in compose_text
    assert "file-worker-principal.jwt" not in compose_text
    assert "delivery-worker-principal.jwt" not in compose_text
    assert "SERVICE_PRINCIPAL_PRIVATE_KEY_FILE" not in compose_text
    assert "SERVICE_PRINCIPAL_JWKS_FILE" not in compose_text
    assert "service_principal_private_key" not in compose_text
    assert "service_principal_jwks" not in compose_text
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "SERVICE_PRINCIPAL_PRIVATE_KEY_FILE" not in env_example
    assert "SERVICE_PRINCIPAL_JWKS_FILE" not in env_example


def test_runtime_tmpfs_and_per_job_limits_are_explicitly_configured() -> None:
    services = _compose()["services"]
    for name, prefix in (
        ("typescript-agent-runtime", "AGENT_RUNTIME"),
        ("python-agent-runtime", "PYTHON_AGENT_RUNTIME"),
    ):
        service = services[name]
        assert "${AGENT_RUNTIME_TMPFS_SIZE:-256m}" in service["tmpfs"][0]
        environment = service["environment"]
        assert environment[f"{prefix}_SANDBOX_CAPACITY_BYTES"] == (
            "${AGENT_RUNTIME_SANDBOX_CAPACITY_BYTES:-234881024}"
        )
        assert environment[f"{prefix}_SANDBOX_MAX_FILE_BYTES"] == (
            "${AGENT_RUNTIME_SANDBOX_MAX_FILE_BYTES:-15728640}"
        )


def test_backend_image_contains_file_service_and_file_worker_targets() -> None:
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM api-server AS file-service" in dockerfile
    assert "import app.workers.file_worker" in dockerfile
    assert "COPY backend/app/modules/file_workspace" in dockerfile
