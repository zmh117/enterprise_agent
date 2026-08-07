from __future__ import annotations

import os

import pytest

from app.bootstrap import build_test_container
from app.modules.internal_api_platform.domain.errors import PolicyViolation
from app.modules.internal_api_platform.domain.loki_policy import build_effective_selector
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_business_application_control_plane import (
    control_plane_settings,
)


def _live_loki_payload(
    *,
    code: str,
    scope_type: str,
    base_url: str,
    tenant_id: str,
    environment_code: str = "",
) -> dict[str, object]:
    return {
        "code": code,
        "name": code,
        "resource_kind": "loki",
        "scope_type": scope_type,
        "environment_code": environment_code,
        "provider_type": "loki",
        "config": {
            "base_url": base_url,
            "tenant_id": tenant_id,
            "timeout_seconds": 5,
            "max_minutes": 60,
            "max_lines": 200,
            "max_response_bytes": 65536,
        },
        "secret_refs": {},
    }


def test_live_loki_supports_global_and_environment_scope_configs() -> None:
    """Opt-in live acceptance; never reads or persists log line contents."""

    base_url = os.environ.get("LOKI_LIVE_ACCEPTANCE_URL", "").strip()
    if not base_url:
        pytest.skip("set LOKI_LIVE_ACCEPTANCE_URL to run live Loki acceptance")
    tenant_id = os.environ.get("LOKI_LIVE_ACCEPTANCE_TENANT", "tenant1").strip()
    cluster = os.environ.get("LOKI_LIVE_ACCEPTANCE_CLUSTER", "mes-cluster").strip()
    region = os.environ.get("LOKI_LIVE_ACCEPTANCE_REGION", "datacenter-01").strip()

    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    try:
        platform = runtime.platform_config_service
        for environment_code, bases in (
            ("loki-live-global-env", ()),
            ("loki-live-environment-env", ("loki-live-base",)),
        ):
            platform.upsert_environment(
                {"code": environment_code},
                actor_id="user_local_admin",
            )
            for base_code in bases:
                platform.upsert_base(
                    {
                        "environment_code": environment_code,
                        "code": base_code,
                        "engine": "mysql",
                    },
                    actor_id="user_local_admin",
                )

        resources = platform.governed_resources
        resources.create_resource(
            _live_loki_payload(
                code="loki-live-global",
                scope_type="global",
                base_url=base_url,
                tenant_id=tenant_id,
            ),
            actor_id="user_local_admin",
        )
        resources.create_resource(
            _live_loki_payload(
                code="loki-live-environment",
                scope_type="environment",
                environment_code="loki-live-environment-env",
                base_url=base_url,
                tenant_id=tenant_id,
            ),
            actor_id="user_local_admin",
        )

        discovery = platform.loki_draft_discovery
        sessions: dict[str, dict[str, object]] = {}
        for resource_code in ("loki-live-global", "loki-live-environment"):
            session = discovery.test_draft(
                resource_code,
                actor_id="user_local_admin",
                minutes=15,
            )
            assert {"cluster", "region"}.issubset(set(session["labels"]))
            clusters = discovery.label_values(
                resource_code,
                test_session_id=str(session["test_session_id"]),
                label="cluster",
                selected_conditions={},
                actor_id="user_local_admin",
                minutes=15,
            )
            assert cluster in clusters["values"]
            regions = discovery.label_values(
                resource_code,
                test_session_id=str(session["test_session_id"]),
                label="region",
                selected_conditions={"cluster": cluster},
                actor_id="user_local_admin",
                minutes=15,
            )
            assert region in regions["values"]
            sessions[resource_code] = session
        assert sessions["loki-live-global"]["label_count"] > 0
        assert sessions["loki-live-environment"]["label_count"] > 0

        resource_revisions: dict[str, dict[str, object]] = {}
        for resource_code in ("loki-live-global", "loki-live-environment"):
            verification = resources.verify_draft(
                resource_code,
                actor_id="user_local_admin",
            )
            assert verification["status"] == "PASSED"
            resource_revisions[resource_code] = resources.publish_draft(
                resource_code,
                actor_id="user_local_admin",
            )

        policies = platform.loki_scope_policies
        with pytest.raises(NonRetryableExecutionError) as cross_environment:
            policies.create(
                {
                    "code": "loki-live-cross-environment",
                    "environment_code": "loki-live-global-env",
                    "resource_revision_id": resource_revisions[
                        "loki-live-environment"
                    ]["id"],
                    "conditions": [{"key": "cluster", "value": cluster}],
                },
                actor_id="user_local_admin",
            )
        assert (
            cross_environment.value.error_code
            == "loki_scope_policy_resource_invalid"
        )

        policy_payloads = {
            "loki-live-global-environment": {
                "environment_code": "loki-live-global-env",
                "resource_revision_id": resource_revisions["loki-live-global"]["id"],
                "conditions": [{"key": "cluster", "value": cluster}],
            },
            "loki-live-environment-base": {
                "environment_code": "loki-live-environment-env",
                "base_code": "loki-live-base",
                "resource_revision_id": resource_revisions[
                    "loki-live-environment"
                ]["id"],
                "conditions": [
                    {"key": "cluster", "value": cluster},
                    {"key": "region", "value": region},
                ],
            },
            "loki-live-empty": {
                "environment_code": "loki-live-environment-env",
                "resource_revision_id": resource_revisions[
                    "loki-live-environment"
                ]["id"],
                "conditions": [
                    {"key": "cluster", "value": cluster},
                    {"key": "region", "value": "codex-missing-live-region"},
                ],
            },
        }
        published: dict[str, dict[str, object]] = {}
        evidence: dict[str, dict[str, object]] = {}
        for code, payload in policy_payloads.items():
            policies.create(
                {"code": code, **payload},
                actor_id="user_local_admin",
            )
            verification = policies.verify(
                code,
                expected_draft_revision=1,
                actor_id="user_local_admin",
            )
            assert verification["status"] == "PASSED"
            evidence[code] = verification
            published[code] = policies.publish(
                code,
                verification_id=str(verification["id"]),
                expected_policy_revision=1,
                actor_id="user_local_admin",
            )

        assert evidence["loki-live-global-environment"]["match_count"] > 0
        assert evidence["loki-live-environment-base"]["match_count"] > 0
        assert evidence["loki-live-empty"]["match_count"] == 0
        assert evidence["loki-live-empty"]["zero_match_warning"] is True
        assert published["loki-live-environment-base"]["conditions"] == [
            {"key": "cluster", "value": cluster},
            {"key": "region", "value": region},
        ]
        assert published["loki-live-empty"]["health_status"] == "EMPTY"

        effective = build_effective_selector(
            {"service_name": "flog"},
            mandatory_conditions=(("cluster", cluster), ("region", region)),
            require_mandatory=True,
        )
        assert effective == {
            "cluster": cluster,
            "region": region,
            "service_name": "flog",
        }
        with pytest.raises(PolicyViolation):
            build_effective_selector(
                {"region": "another-region"},
                mandatory_conditions=(("cluster", cluster), ("region", region)),
                require_mandatory=True,
            )
    finally:
        runtime.database.close()
