from __future__ import annotations

from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.modules.platform_config.application.governed_resources import (
    ResourceVerificationOutcome,
)
from app.modules.platform_config.application.loki_scope_policy_verifier import (
    LokiScopePolicyVerificationOutcome,
)
from backend.tests.test_business_application_control_plane import (
    control_plane_settings,
)
from backend.tests.test_unified_identity_rbac import csrf_headers, login


class _PassingResourceVerifier:
    def verify(self, **_kwargs: object) -> ResourceVerificationOutcome:
        return ResourceVerificationOutcome(
            status="PASSED",
            provider_contract_version="loki_v1",
            checks={"connection": True},
        )


class _EmptyLokiPolicyVerifier:
    def verify(self, **_kwargs: object) -> LokiScopePolicyVerificationOutcome:
        return LokiScopePolicyVerificationOutcome(
            status="PASSED",
            verifier_version="loki-scope-series.v1",
            match_count=0,
            zero_match_warning=True,
            result_summary={"match_hash": "0" * 64, "duration_ms": 2},
            safe_error_summary="Loki selector 当前未匹配到日志流",
        )


def test_policy_management_api_publishes_immutable_workshop_and_loki_revisions() -> None:
    settings = control_plane_settings()
    runtime = build_test_container(settings, migrate=True, seed=True)
    platform = runtime.platform_config_service
    platform.upsert_environment(
        {"code": "policy-api-env"},
        actor_id="user_local_admin",
    )
    platform.upsert_base(
        {
            "environment_code": "policy-api-env",
            "code": "guanlan",
            "engine": "mysql",
        },
        actor_id="user_local_admin",
    )
    platform.upsert_workshop(
        {
            "environment_code": "policy-api-env",
            "base_code": "guanlan",
            "code": "GL001",
        },
        actor_id="user_local_admin",
    )
    resources = platform.governed_resources
    resources.create_resource(
        {
            "code": "loki-policy-api",
            "name": "Loki Policy API",
            "resource_kind": "loki",
            "scope_type": "environment",
            "environment_code": "policy-api-env",
            "provider_type": "loki",
            "config": {
                "base_url": "http://loki.internal:3100",
                "tenant_id": "tenant-a",
                "timeout_seconds": 5,
                "max_minutes": 60,
                "max_lines": 200,
                "max_response_bytes": 65536,
            },
            "secret_refs": {},
        },
        actor_id="user_local_admin",
    )
    resources.verify_draft(
        "loki-policy-api",
        actor_id="user_local_admin",
        verifier=_PassingResourceVerifier(),
    )
    resource_revision = resources.publish_draft(
        "loki-policy-api",
        actor_id="user_local_admin",
    )
    platform.loki_scope_policies.verifier = _EmptyLokiPolicyVerifier()  # type: ignore[assignment]

    app = create_app(settings, container_factory=lambda _settings: runtime)
    with TestClient(app) as client:
        headers = csrf_headers(login(client))
        workshop_created = client.post(
            "/api/platform/workshop-partition-policies",
            headers=headers,
            json={
                "code": "partition-api-gl001",
                "environment_code": "policy-api-env",
                "base_code": "guanlan",
                "workshop_code": "GL001",
                "database_rule_enabled": True,
                "database_table_prefix": "GL001_",
                "redis_rule_enabled": False,
                "redis_prefixes": [],
            },
        )
        assert workshop_created.status_code == 200, workshop_created.text
        workshop_verified = client.post(
            "/api/platform/workshop-partition-policies/partition-api-gl001/verify",
            headers=headers,
            json={"expected_draft_revision": 1},
        )
        assert workshop_verified.status_code == 200, workshop_verified.text
        workshop_published = client.post(
            "/api/platform/workshop-partition-policies/partition-api-gl001/publish",
            headers=headers,
            json={
                "verification_id": workshop_verified.json()["verification"]["id"],
                "expected_policy_revision": 1,
            },
        )
        workshop_detail = client.get(
            "/api/platform/workshop-partition-policies/partition-api-gl001",
            headers=headers,
        )

        loki_created = client.post(
            "/api/platform/loki-scope-policies",
            headers=headers,
            json={
                "code": "loki-policy-api-guanlan",
                "environment_code": "policy-api-env",
                "base_code": "guanlan",
                "resource_revision_id": resource_revision["id"],
                "conditions": [
                    {"key": "customer", "value": "policy-api-env"},
                    {"key": "base", "value": "guanlan"},
                ],
            },
        )
        assert loki_created.status_code == 200, loki_created.text
        loki_verified = client.post(
            "/api/platform/loki-scope-policies/loki-policy-api-guanlan/verify",
            headers=headers,
            json={"expected_draft_revision": 1},
        )
        assert loki_verified.status_code == 200, loki_verified.text
        loki_published = client.post(
            "/api/platform/loki-scope-policies/loki-policy-api-guanlan/publish",
            headers=headers,
            json={
                "verification_id": loki_verified.json()["verification"]["id"],
                "expected_policy_revision": 1,
            },
        )
        loki_detail = client.get(
            "/api/platform/loki-scope-policies/loki-policy-api-guanlan",
            headers=headers,
        )

    assert workshop_published.status_code == 200
    assert workshop_published.json()["revision"]["database_table_prefix"] == "GL001_"
    assert workshop_detail.json()["policy"]["draft"] is None
    assert workshop_detail.json()["policy"]["revisions"][0]["id"] == (
        workshop_published.json()["revision"]["id"]
    )
    assert loki_published.status_code == 200
    assert loki_published.json()["revision"]["health_status"] == "EMPTY"
    assert loki_detail.json()["policy"]["draft"] is None
    assert loki_detail.json()["policy"]["revisions"][0]["conditions"] == [
        {"key": "base", "value": "guanlan"},
        {"key": "customer", "value": "policy-api-env"},
    ]
    combined = workshop_detail.text + loki_detail.text
    assert "secret_refs" not in combined
    assert "base_url" not in combined
    runtime.database.close()
