"""主 Compose 知识服务部署合同；只解析合成配置，不读取实际部署配置。"""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_SERVICES = {
    "knowledge-embedding",
    "knowledge-embedding-online",
    "knowledge-reranker",
    "knowledge-qdrant",
    "knowledge-mcp",
    "knowledge-sync",
    "knowledge-ops-controller",
}
PREPARE_SERVICES = {"knowledge-model-prepare", "knowledge-reranker-prepare"}


@pytest.fixture(scope="module")
def compose_cli():
    executable = shutil.which("docker")
    if not executable:
        pytest.skip("Docker Compose CLI unavailable")
    result = subprocess.run([executable, "compose", "version"], capture_output=True, timeout=15)
    if result.returncode:
        pytest.skip("Docker Compose CLI unavailable")
    return executable


def render(compose_cli, *, profiles=(), **variables):
    env = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
    env.update({"KNOWLEDGE_DEPLOY_ROOT": str(ROOT), **variables})
    command = [
        compose_cli,
        "compose",
        "--env-file",
        os.devnull,
        "-p",
        "knowledge-compose-contract",
        "-f",
        str(ROOT / "docker-compose.yml"),
    ]
    for profile in profiles:
        command.extend(["--profile", profile])
    command.extend(["config", "--format", "json"])
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, "synthetic Compose rendering failed (details withheld)"
    return json.loads(result.stdout)


def test_default_main_file_starts_all_resident_services_and_prepares_models(compose_cli):
    config = render(compose_cli)
    assert KNOWLEDGE_SERVICES | PREPARE_SERVICES <= config["services"].keys()
    assert not {"knowledge-ops", "knowledge-check"} & config["services"].keys()
    assert all(
        not config["services"][name].get("profiles")
        for name in KNOWLEDGE_SERVICES | PREPARE_SERVICES
    )
    for name in ("knowledge-embedding", "knowledge-embedding-online"):
        assert (
            config["services"][name]["depends_on"]["knowledge-model-prepare"]["condition"]
            == "service_completed_successfully"
        )
    assert (
        config["services"]["knowledge-reranker"]["depends_on"]["knowledge-reranker-prepare"][
            "condition"
        ]
        == "service_completed_successfully"
    )
    for name in ("api-server", "postgres", "ones-mcp"):
        assert "knowledge-managed" in config["services"][name]["networks"]
    assert config["networks"]["knowledge-managed"]["internal"]
    assert not any(
        (ROOT / "knowledge" / name).exists()
        for name in (
            "compose.yml",
            "mcp.compose.yml",
            "sync.compose.yml",
            "ops.compose.yml",
            "deployment.compose.yml",
        )
    )


def test_fixed_volume_names_are_external_and_overrideable(compose_cli):
    config = render(
        compose_cli,
        KNOWLEDGE_MODEL_VOLUME="existing-model",
        KNOWLEDGE_QDRANT_VOLUME="existing-qdrant",
        KNOWLEDGE_STATE_VOLUME="existing-state",
        KNOWLEDGE_RERANKER_VOLUME="existing-reranker",
    )
    for key, name in {
        "knowledge-models": "existing-model",
        "knowledge-qdrant": "existing-qdrant",
        "knowledge-operation-state": "existing-state",
        "knowledge-reranker-models": "existing-reranker",
    }.items():
        assert config["volumes"][key] == {"name": name, "external": True}
    default = render(compose_cli)
    assert (
        default["volumes"]["knowledge-qdrant"]["name"]
        == "knowledge-compose-contract_knowledge-qdrant"
    )
    assert (
        default["volumes"]["knowledge-operation-state"]["name"]
        == "knowledge-compose-contract_knowledge_ops_state"
    )


@pytest.mark.parametrize(
    "root", ["/home/deploy/项目 with spaces", "C:/Users/deploy/enterprise agent"]
)
def test_controller_mount_targets_do_not_inherit_host_path_syntax(compose_cli, root):
    config = render(compose_cli, KNOWLEDGE_DEPLOY_ROOT=root)
    controller = config["services"]["knowledge-ops-controller"]
    assert controller["environment"]["KNOWLEDGE_DEPLOY_ROOT"] == "/deployment"
    mounts = {row["target"]: row for row in controller["volumes"]}
    for target in (
        "/deployment",
        "/deployment-secrets/app-config-master-key",
        "/deployment-secrets/principal-jwks.json",
        "/deployment-secrets/knowledge-bootstrap-token",
    ):
        assert mounts[target]["type"] == "bind"
        assert mounts[target]["read_only"] is True
        assert not mounts[target].get("bind", {}).get("create_host_path", False)
    assert all(not target.startswith("C:") for target in mounts)


def test_build_database_secret_and_maintenance_boundaries(compose_cli):
    config = render(compose_cli, profiles=("maintenance",))
    raw = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = config["services"]
    assert {"knowledge-ops", "knowledge-check"} <= services.keys()
    for name in KNOWLEDGE_SERVICES | PREPARE_SERVICES | {"knowledge-ops", "knowledge-check"}:
        service = services[name]
        assert not service.get("container_name")
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        if "build" in service:
            assert Path(service["build"]["context"]) == ROOT
            assert (ROOT / service["build"]["dockerfile"]).is_file()
        if name != "knowledge-qdrant":
            assert service["read_only"] and not service.get("ports")
    for name in (
        "knowledge-mcp",
        "knowledge-sync",
        "knowledge-ops-controller",
        "knowledge-ops",
        "knowledge-check",
    ):
        assert (
            services[name]["environment"]["DATABASE_DSN"]
            == services["api-server"]["environment"]["DATABASE_DSN"]
        )
        assert raw["services"][name]["build"]["args"] == raw["x-release-build-args"]
    for name in PREPARE_SERVICES | {
        "knowledge-embedding",
        "knowledge-embedding-online",
        "knowledge-reranker",
        "knowledge-qdrant",
        "knowledge-ops",
    }:
        assert not services[name].get("secrets")
    assert services["knowledge-ops"]["environment"]["APP_CONFIG_MASTER_KEY_FILE"] == ""
    assert "HF_ENDPOINT" not in services["knowledge-embedding"]["environment"]
    assert services["knowledge-embedding"]["volumes"][0]["read_only"]


def test_qdrant_is_pinned_and_only_publishes_loopback_http_by_default(compose_cli):
    config = render(compose_cli)
    service = config["services"]["knowledge-qdrant"]
    assert (
        service["image"]
        == "qdrant/qdrant:v1.19.1@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10"
    )
    assert not service.get("build")
    assert service["ports"] == [
        {
            "mode": "ingress",
            "host_ip": "127.0.0.1",
            "target": 6333,
            "published": "6333",
            "protocol": "tcp",
        }
    ]
    assert set(service["networks"]) == {"knowledge-managed", "provider-egress"}
    assert service["environment"]["QDRANT__TELEMETRY_DISABLED"] == "true"
    assert (
        render(compose_cli, KNOWLEDGE_QDRANT_BIND="0.0.0.0")["services"]["knowledge-qdrant"][
            "ports"
        ][0]["host_ip"]
        == "0.0.0.0"
    )


def test_model_endpoint_only_reaches_prepare_jobs(compose_cli):
    default = render(compose_cli)
    mirror = render(compose_cli, HF_ENDPOINT="https://hf-mirror.com")
    for name in PREPARE_SERVICES:
        assert default["services"][name]["environment"]["HF_ENDPOINT"] == "https://huggingface.co"
        assert mirror["services"][name]["environment"]["HF_ENDPOINT"] == "https://hf-mirror.com"
        assert set(mirror["services"][name]["networks"]) == {"provider-egress"}
    for name in ("knowledge-embedding", "knowledge-embedding-online", "knowledge-reranker"):
        service = mirror["services"][name]
        assert "HF_ENDPOINT" not in service["environment"]
        assert service["environment"]["HF_HUB_OFFLINE"] == "1"
        assert set(service["networks"]) == {"knowledge-managed"}
