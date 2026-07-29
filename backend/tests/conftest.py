from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def local_webhook_test_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve local seed references explicitly without storing plaintext in SQL."""
    monkeypatch.setenv(
        "GRAFANA_WEBHOOK_TOKEN",
        "test-grafana-token-0123456789abcdefABCDEF",
    )
    monkeypatch.setenv("DINGTALK_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("DINGTALK_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv(
        "DINGTALK_WEBHOOK_ROBOT_URL",
        "https://oapi.dingtalk.com/robot/send?access_token=test-token",
    )
    monkeypatch.setenv("DINGTALK_WEBHOOK_ROBOT_SECRET", "test-robot-secret")
