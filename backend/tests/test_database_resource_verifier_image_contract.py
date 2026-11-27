from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "backend/Dockerfile"


def test_api_declares_its_pydantic_major_version() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert "pydantic>=2.9,<3" in project["dependencies"]


def test_api_server_image_includes_resource_verification_clients() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "FROM database-deps AS api-server" in dockerfile
