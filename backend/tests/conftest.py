from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def local_webhook_test_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve the local seed's secret reference without storing a secret in SQL."""
    monkeypatch.setenv("GRAFANA_WEBHOOK_TOKEN", "test-grafana-token")
