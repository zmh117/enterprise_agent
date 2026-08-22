from __future__ import annotations

from pathlib import Path

import pytest

from backend.tests.suite_governance import (
    SuiteManifestError,
    load_validated_test_tiers,
)


TEST_ROOT = Path(__file__).parent
TEST_TIER_MANIFEST = TEST_ROOT / "test_suite_tiers.toml"


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    try:
        tiers_by_path = load_validated_test_tiers(TEST_ROOT, TEST_TIER_MANIFEST)
    except SuiteManifestError as exc:
        raise pytest.UsageError(f"invalid backend test tier manifest: {exc}") from exc

    resolved_root = TEST_ROOT.resolve()
    for item in items:
        try:
            relative_path = Path(item.path).resolve().relative_to(resolved_root).as_posix()
        except ValueError:
            continue
        tier = tiers_by_path.get(relative_path)
        if tier is None:
            raise pytest.UsageError(
                f"collected backend test has no tier assignment: {relative_path}"
            )
        item.add_marker(getattr(pytest.mark, tier))


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
