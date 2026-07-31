from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "backend/Dockerfile"


def test_api_server_image_includes_resource_verification_clients() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "FROM database-deps AS api-server" in dockerfile
