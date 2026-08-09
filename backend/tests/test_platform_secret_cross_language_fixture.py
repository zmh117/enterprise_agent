from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.mcp_common.auth import McpAuthenticationError
from services.mcp_common.secret_crypto import PlatformSecretDecryptor


FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "agent-runtime"
    / "contracts"
    / "v1"
    / "golden"
    / "platform-secret-python.json"
)


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_python_and_node_share_the_platform_secret_fixture() -> None:
    fixture = _fixture()
    material = str(fixture["master_key"]).removeprefix("EA_MASTER_KEY_V1:")
    decryptor = PlatformSecretDecryptor(material)

    assert decryptor.decrypt(
        secret_id=str(fixture["secret_id"]),
        version=int(fixture["version"]),
        ciphertext=str(fixture["ciphertext"]),
        nonce=str(fixture["nonce"]),
        algorithm=str(fixture["algorithm"]),
    ) == str(fixture["plaintext"])


def test_python_fixture_fails_closed_after_tag_tampering() -> None:
    fixture = _fixture()
    material = str(fixture["master_key"]).removeprefix("EA_MASTER_KEY_V1:")

    with pytest.raises(McpAuthenticationError):
        PlatformSecretDecryptor(material).decrypt(
            secret_id=str(fixture["secret_id"]),
            version=int(fixture["version"]),
            ciphertext=str(fixture["ciphertext"])[:-1] + "A",
            nonce=str(fixture["nonce"]),
            algorithm=str(fixture["algorithm"]),
        )
