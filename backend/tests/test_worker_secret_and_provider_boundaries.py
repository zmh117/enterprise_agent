from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.bootstrap import _ensure_trusted_ones_for_service
from app.shared.config import Settings
from app.shared.runtime_config_loader import _service_requires_master_key


@pytest.mark.parametrize(
    "service_name",
    (
        "agent-worker",
        "job-dispatch-worker",
        "webhook-worker",
        "channel-dispatch-worker",
    ),
)
def test_non_decrypting_workers_do_not_require_platform_master_key(
    service_name: str,
) -> None:
    assert _service_requires_master_key(service_name) is False


@pytest.mark.parametrize(
    "service_name",
    ("api-server", "delivery-dispatch-worker", "attachment-worker"),
)
def test_decrypting_services_require_platform_master_key(service_name: str) -> None:
    assert _service_requires_master_key(service_name) is True


def test_worker_startup_never_mutates_trusted_provider_instance() -> None:
    repository = Mock()

    _ensure_trusted_ones_for_service(
        repository,
        settings=Settings(),
        service_name="agent-worker",
    )

    repository.ensure_trusted_ones.assert_not_called()


def test_api_startup_owns_trusted_provider_reconciliation() -> None:
    repository = Mock()

    _ensure_trusted_ones_for_service(
        repository,
        settings=Settings(),
        service_name="api-server",
    )

    repository.ensure_trusted_ones.assert_called_once()
