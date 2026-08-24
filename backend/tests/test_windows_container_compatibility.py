from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "backend/docker/normalize_secrets_entrypoint.sh"
DOCKERFILE = ROOT / "backend/Dockerfile"
SECRET_FILE_VARIABLES = {
    "APP_CONFIG_MASTER_KEY_FILE",
    "DELIVERY_WORKER_BOOTSTRAP_TOKEN_FILE",
    "DINGTALK_RUNTIME_AUTH_TOKEN_FILE",
    "DOCLING_SERVE_API_KEY_FILE",
    "FILE_PROCESSING_WORKER_BOOTSTRAP_TOKEN_FILE",
    "FILE_STORAGE_BOOTSTRAP_ACCESS_KEY_FILE",
    "FILE_STORAGE_BOOTSTRAP_SECRET_KEY_FILE",
    "FILE_WORKER_BOOTSTRAP_TOKEN_FILE",
    "INITIAL_ADMIN_PASSWORD_FILE",
    "MODEL_PROBE_AUTH_TOKEN_FILE",
    "PRINCIPAL_JWKS_FILE",
    "PRINCIPAL_JWT_PRIVATE_KEY_FILE",
    "RUNTIME_GRANT_PRIVATE_KEY_FILE",
    "RUNTIME_GRANT_PUBLIC_KEY_FILE",
}


def test_shell_scripts_are_lf_normalized_by_repository_policy() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    scripts = sorted(
        path
        for root in (ROOT / "backend", ROOT / "frontend", ROOT / "scripts")
        for path in root.rglob("*.sh")
    )

    assert "*.sh text eol=lf" in attributes.splitlines()
    assert scripts
    for script in scripts:
        assert b"\r" not in script.read_bytes(), script.relative_to(ROOT)


def test_python_base_images_inherit_secret_normalization_entrypoint() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    base_section = dockerfile.split("FROM python:3.12-slim AS python-deps", 1)[1].split(
        "FROM python-deps AS claude-runtime",
        1,
    )[0]

    assert (
        "COPY backend/docker/normalize_secrets_entrypoint.sh "
        "/usr/local/bin/normalize-secrets-entrypoint" in base_section
    )
    assert 'ENTRYPOINT ["/usr/local/bin/normalize-secrets-entrypoint"]' in base_section


def test_compose_secret_file_variables_and_read_only_tmpfs_are_covered() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    configured_secret_variables: set[str] = set()
    for service_name, service in compose["services"].items():
        environment = service.get("environment", {})
        configured_secret_variables.update(
            name
            for name, value in environment.items()
            if name.endswith("_FILE") and "/run/secrets/" in str(value)
        )
        build = service.get("build", {})
        if not (
            service.get("read_only") is True
            and isinstance(build, dict)
            and build.get("dockerfile") == "backend/Dockerfile"
        ):
            continue
        runtime_tmpdir = str(environment.get("TMPDIR", "/tmp"))
        mount_targets = {str(item).split(":", 1)[0] for item in service.get("tmpfs", [])}
        assert runtime_tmpdir in mount_targets, service_name

    assert configured_secret_variables <= SECRET_FILE_VARIABLES


def test_entrypoint_normalizes_only_whitelisted_file_variables(
    tmp_path: Path,
) -> None:
    source = tmp_path / "windows-mounted-secret"
    source.write_text("sensitive-test-fixture\n", encoding="utf-8")
    source.chmod(0o777)
    ignored = tmp_path / "ignored-secret"
    ignored.write_text("ignored-test-fixture\n", encoding="utf-8")
    ignored.chmod(0o777)
    runtime_tmp = tmp_path / "runtime-tmp"
    runtime_tmp.mkdir(mode=0o700)
    environment = {
        **os.environ,
        "TMPDIR": str(runtime_tmp),
        "HOME": str(tmp_path / "must-not-be-used"),
        "APP_CONFIG_MASTER_KEY_FILE": str(source),
        "UNDECLARED_SECRET_FILE": str(ignored),
    }

    completed = subprocess.run(
        [
            str(ENTRYPOINT),
            sys.executable,
            "-c",
            "import os; print(os.environ['APP_CONFIG_MASTER_KEY_FILE'])",
        ],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    normalized = Path(completed.stdout.strip())
    assert normalized == runtime_tmp / "ea-secrets" / "APP_CONFIG_MASTER_KEY_FILE"
    assert normalized.read_bytes() == source.read_bytes()
    assert stat.S_IMODE(normalized.stat().st_mode) == 0o400
    assert stat.S_IMODE(normalized.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(source.stat().st_mode) == 0o777
    assert not (runtime_tmp / "ea-secrets" / "UNDECLARED_SECRET_FILE").exists()


def test_entrypoint_rejects_symlink_source_without_disclosing_content(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.write_text("must-not-appear-in-output", encoding="utf-8")
    link = tmp_path / "source-link"
    link.symlink_to(source)
    runtime_tmp = tmp_path / "runtime-tmp"
    runtime_tmp.mkdir()
    environment = {
        **os.environ,
        "TMPDIR": str(runtime_tmp),
        "APP_CONFIG_MASTER_KEY_FILE": str(link),
    }

    completed = subprocess.run(
        [str(ENTRYPOINT), sys.executable, "-c", "raise SystemExit(0)"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "APP_CONFIG_MASTER_KEY_FILE" in completed.stderr
    assert "must-not-appear-in-output" not in completed.stderr


def test_entrypoint_rejects_relative_tmpdir_instead_of_falling_back_to_home(
    tmp_path: Path,
) -> None:
    environment = {
        **os.environ,
        "TMPDIR": "relative-runtime-tmp",
        "HOME": str(tmp_path),
    }

    completed = subprocess.run(
        [str(ENTRYPOINT), sys.executable, "-c", "raise SystemExit(0)"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert str(tmp_path) not in completed.stderr


def test_entrypoint_contract_is_shell_valid_and_has_fixed_whitelist() -> None:
    content = ENTRYPOINT.read_text(encoding="utf-8")

    subprocess.run(
        ["sh", "-n", str(ENTRYPOINT)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert SECRET_FILE_VARIABLES == {
        line.strip()
        for line in content.split("secret_file_variables='", 1)[1].split("'", 1)[0].splitlines()
        if line.strip()
    }
    assert "/dev/shm" not in content
    assert "HOME" not in content
    assert 'exec "$@"' in content
