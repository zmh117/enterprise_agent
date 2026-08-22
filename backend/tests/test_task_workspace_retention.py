from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.modules.business_application.domain.policies import (
    publication_workspace_retention,
    snapshot_hash,
    validate_task_workspace_retention_period,
    verify_publication_snapshot,
)
from app.modules.file_workspace.domain import RetentionPeriod
from app.modules.file_workspace.lifecycle import task_workspace_expires_at
from app.modules.business_application.domain.runtime import RuntimeReadinessEvaluator
from app.modules.document_processing.profile import document_processing_profile_snapshot
from app.shared.exceptions import NonRetryableExecutionError


SHANGHAI = ZoneInfo("Asia/Shanghai")


@pytest.mark.parametrize(
    ("created_at", "period", "expected"),
    [
        ("2026-08-14T23:59:59+08:00", RetentionPeriod.DAY, "2026-08-15T00:00:00+08:00"),
        ("2026-08-12T09:00:00+08:00", RetentionPeriod.WEEK, "2026-08-17T00:00:00+08:00"),
        ("2026-08-31T23:59:59+08:00", RetentionPeriod.MONTH, "2026-09-01T00:00:00+08:00"),
        ("2026-12-31T12:00:00+08:00", RetentionPeriod.MONTH, "2027-01-01T00:00:00+08:00"),
    ],
)
def test_workspace_expiry_uses_fixed_asia_shanghai_natural_boundary(
    created_at: str,
    period: RetentionPeriod,
    expected: str,
) -> None:
    created = datetime.fromisoformat(created_at)
    expiry = task_workspace_expires_at(created, period)
    assert expiry.tzinfo == SHANGHAI
    assert expiry.isoformat() == expected
    # Later activity is deliberately not an input and cannot roll the boundary.
    assert task_workspace_expires_at(created, period) == expiry


def test_retention_policy_defaults_are_fixed_to_publication_snapshot() -> None:
    assert validate_task_workspace_retention_period(None) == "WEEK"
    assert publication_workspace_retention({"schema_version": 1}) == (
        "WEEK",
        "publication_snapshot",
    )
    assert publication_workspace_retention(
        {"schema_version": 2, "task_workspace_retention_period": "MONTH"}
    ) == ("MONTH", "publication_snapshot")

    with pytest.raises(NonRetryableExecutionError) as error:
        validate_task_workspace_retention_period("ROLLING_24_HOURS")
    assert error.value.field_errors == [
        {
            "field": "task_workspace_retention_period",
            "message": "只允许 DAY、WEEK 或 MONTH",
        }
    ]


def test_workspace_expiry_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        task_workspace_expires_at(datetime(2026, 8, 14), RetentionPeriod.DAY)


def test_current_publication_requires_complete_schema_v6_snapshot() -> None:
    invalid_v2 = {"schema_version": 6, "application": {"id": "invalid"}}
    assert not verify_publication_snapshot(
        invalid_v2, schema_version=6, expected_hash=snapshot_hash(invalid_v2)
    )
    valid_v2 = {
        **invalid_v2,
        "task_workspace_retention_period": "DAY",
        "task_file_features": {
            "workspace_enabled": False,
            "file_mcp_enabled": False,
            "runtime_file_edit_enabled": False,
            "default_file_delivery_enabled": False,
        },
        "document_processing_profile": document_processing_profile_snapshot("NONE"),
    }
    assert verify_publication_snapshot(
        valid_v2, schema_version=6, expected_hash=snapshot_hash(valid_v2)
    )


def test_file_dependencies_block_publication_preflight_with_stable_safe_reasons() -> None:
    evaluator = RuntimeReadinessEvaluator(
        data_plane_enabled=True,
        runtime_environment="local",
        file_service_ready=False,
        file_worker_ready=False,
    )
    errors = evaluator.activation_errors(
        {
            "task_workspace_retention_period": "WEEK",
            "agent": {"id": "agent-publication", "config_hash": "a" * 64},
            "triggers": [],
            "deliveries": [],
        }
    )
    file_errors = {
        str(item["reason_code"]): str(item["field"])
        for item in errors
        if str(item["reason_code"]).startswith("file_")
    }
    assert file_errors == {
        "file_service_unavailable": "task_workspace_retention_period",
        "file_worker_unavailable": "task_workspace_retention_period",
    }
    readiness = evaluator.evaluate(
        snapshot={
            "agent": {"id": "agent-publication", "config_hash": "a" * 64},
            "triggers": [],
            "deliveries": [],
        },
        deployment={"active": True, "environment": "local"},
    )
    assert readiness.reason_code == "file_service_unavailable"
    assert "endpoint" not in readiness.message.lower()
    assert "secret" not in readiness.message.lower()
