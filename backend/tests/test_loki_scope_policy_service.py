from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.modules.platform_config.application.governed_resources import (
    ResourceVerificationOutcome,
)
from app.modules.platform_config.application.loki_scope_policies import (
    normalize_loki_scope_policy_draft,
)
from app.modules.platform_config.application.loki_scope_policy_verifier import (
    LokiScopePolicyVerificationOutcome,
)
from app.modules.platform_config.infrastructure.loki_scope_policy_repository import (
    LokiScopePolicyRepository,
)
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_application_builtin_tool_resource_mapping import (
    _publish_builtin_tool,
)
from backend.tests.test_business_application_control_plane import (
    control_plane_settings,
    draft_payload,
)
from backend.tests.test_unified_identity_rbac import csrf_headers, login


def _loki_payload(*, code: str, scope_type: str, environment_code: str = "") -> dict[str, object]:
    return {
        "code": code,
        "name": code,
        "resource_kind": "loki",
        "scope_type": scope_type,
        "environment_code": environment_code,
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
    }


class _PostgresStrictApplicationUsageDatabase:
    def execute(
        self,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del parameters
        normalized = " ".join(statement.split())
        assert "select distinct" in normalized
        assert (
            "order by application_code, application_publication_revision, "
            "policy_revision, resource_slot, target_key, deployment_environment"
            in normalized
        )
        return []


def test_loki_application_usage_projection_orders_by_selected_aliases_for_postgres() -> None:
    repository = LokiScopePolicyRepository(  # type: ignore[arg-type]
        _PostgresStrictApplicationUsageDatabase()
    )

    assert repository.list_application_usages("loki-policy-1") == []


def test_loki_resource_accepts_only_global_or_exact_environment_scope() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    platform = runtime.platform_config_service
    environment = platform.upsert_environment(
        {"code": "loki-scope-env"},
        actor_id="user_local_admin",
    )
    platform.upsert_base(
        {
            "environment_code": "loki-scope-env",
            "code": "guanlan",
            "engine": "mysql",
        },
        actor_id="user_local_admin",
    )
    resources = platform.governed_resources

    global_resource = resources.create_resource(
        _loki_payload(code="loki-global", scope_type="global"),
        actor_id="user_local_admin",
    )
    environment_resource = resources.create_resource(
        _loki_payload(
            code="loki-environment",
            scope_type="environment",
            environment_code="loki-scope-env",
        ),
        actor_id="user_local_admin",
    )
    assert global_resource["resource"]["environment_id"] is None
    assert global_resource["resource"]["scope_type"] == "global"
    assert environment_resource["resource"]["environment_id"] == environment["id"]
    assert {item["code"] for item in resources.list_resources()} == {
        "loki-global",
        "loki-environment",
    }

    invalid_base = _loki_payload(
        code="loki-base-invalid",
        scope_type="base",
        environment_code="loki-scope-env",
    )
    invalid_base["base_code"] = "guanlan"
    with pytest.raises(NonRetryableExecutionError) as base_rejected:
        resources.create_resource(invalid_base, actor_id="user_local_admin")
    assert base_rejected.value.error_code == "resource_scope_invalid"

    invalid_placement = _loki_payload(
        code="loki-placement-invalid",
        scope_type="environment",
        environment_code="loki-scope-env",
    )
    invalid_placement["placement"] = "edge"
    with pytest.raises(NonRetryableExecutionError) as placement_rejected:
        resources.create_resource(invalid_placement, actor_id="user_local_admin")
    assert placement_rejected.value.error_code == "builtin_tool_placement_invalid"
    runtime.database.close()


def test_loki_draft_test_session_cascades_exact_discovery_and_expires_on_change() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    platform = runtime.platform_config_service
    resources = platform.governed_resources
    created = resources.create_resource(
        _loki_payload(code="loki-discovery", scope_type="global"),
        actor_id="user_local_admin",
    )

    class Gateway:
        calls: list[dict[str, object]] = []

        def test_and_labels(self, **kwargs: object) -> list[str]:
            self.calls.append({"operation": "test", **kwargs})
            return ["workshop", "customer", "customer", "logtype"]

        def label_values(self, **kwargs: object) -> list[str]:
            self.calls.append({"operation": "values", **kwargs})
            return ["guanlan", "guanlan", "tianjin"]

    gateway = Gateway()
    discovery = platform.loki_draft_discovery
    discovery.gateway = gateway
    tested = discovery.test_draft(
        "loki-discovery",
        actor_id="user_local_admin",
        minutes=10,
        limit=2,
    )
    assert tested["labels"] == ["customer", "logtype"]
    assert tested["truncated"] is True

    values = discovery.label_values(
        "loki-discovery",
        test_session_id=str(tested["test_session_id"]),
        label="workshop",
        selected_conditions={"customer": "sanjiu-test1"},
        actor_id="user_local_admin",
        minutes=10,
        limit=10,
    )
    assert values == {
        "label": "workshop",
        "values": ["guanlan", "tianjin"],
        "value_count": 2,
        "truncated": False,
    }
    assert gateway.calls[-1]["conditions"] == {"customer": "sanjiu-test1"}

    for invalid_conditions in (
        {"customer": "sanjiu.*"},
        {"customer": 'sanjiu"} |= "x"'},
        {"customer": "sanjiu", "customer=~": ".*"},
    ):
        with pytest.raises(NonRetryableExecutionError) as rejected:
            discovery.label_values(
                "loki-discovery",
                test_session_id=str(tested["test_session_id"]),
                label="workshop",
                selected_conditions=invalid_conditions,
                actor_id="user_local_admin",
            )
        assert rejected.value.error_code == "loki_draft_discovery_invalid"

    with pytest.raises(NonRetryableExecutionError):
        discovery.test_draft(
            "loki-discovery",
            actor_id="user_local_admin",
            minutes=61,
        )

    resources.save_draft(
        "loki-discovery",
        {
            "provider_type": "loki",
            "config": {
                **created["draft"]["config"],
                "timeout_seconds": 6,
            },
            "secret_refs": {},
        },
        expected_revision=1,
        actor_id="user_local_admin",
    )
    with pytest.raises(NonRetryableExecutionError) as stale:
        discovery.label_values(
            "loki-discovery",
            test_session_id=str(tested["test_session_id"]),
            label="workshop",
            selected_conditions={"customer": "sanjiu-test1"},
            actor_id="user_local_admin",
        )
    assert stale.value.error_code == "loki_draft_test_session_stale"
    assert runtime.database.execute_one(
        """
        select count(*) as count
          from loki_resource_draft_test_session
         where id = ?
        """,
        (tested["test_session_id"],),
    ) == {"count": 1}
    runtime.database.close()


def test_loki_draft_discovery_api_requires_test_session_before_values() -> None:
    settings = control_plane_settings()
    runtime = build_test_container(settings, migrate=True, seed=True)
    runtime.platform_config_service.governed_resources.create_resource(
        _loki_payload(code="loki-discovery-api", scope_type="global"),
        actor_id="user_local_admin",
    )

    class Gateway:
        def test_and_labels(self, **_kwargs: object) -> list[str]:
            return ["customer", "workshop"]

        def label_values(self, **_kwargs: object) -> list[str]:
            return ["guanlan"]

    runtime.platform_config_service.loki_draft_discovery.gateway = Gateway()
    app = create_app(settings, container_factory=lambda _settings: runtime)
    with TestClient(app) as client:
        headers = csrf_headers(login(client))
        missing_session = client.post(
            "/api/platform/resources/loki-discovery-api/loki/label-values",
            json={"label": "workshop", "selected_conditions": {}},
            headers=headers,
        )
        tested = client.post(
            "/api/platform/resources/loki-discovery-api/loki/test",
            json={"minutes": 15, "limit": 64},
            headers=headers,
        )
        values = client.post(
            "/api/platform/resources/loki-discovery-api/loki/label-values",
            json={
                "test_session_id": tested.json()["test_session_id"],
                "label": "workshop",
                "selected_conditions": {"customer": "sanjiu-test1"},
            },
            headers=headers,
        )

    assert missing_session.status_code == 400
    assert tested.status_code == 200
    assert tested.json()["labels"] == ["customer", "workshop"]
    assert values.status_code == 200
    assert values.json()["values"] == ["guanlan"]
    runtime.database.close()


def test_loki_scope_policy_normalizes_exact_and_conditions() -> None:
    normalized = normalize_loki_scope_policy_draft(
        {
            "resource_revision_id": "loki-revision-1",
            "conditions": [
                {"key": "workshop", "value": "guanlan"},
                {"key": "customer", "value": "sanjiu-test1"},
            ],
        }
    )
    assert normalized["conditions"] == [
        {"key": "customer", "value": "sanjiu-test1"},
        {"key": "workshop", "value": "guanlan"},
    ]


@pytest.mark.parametrize(
    "conditions",
    [
        [],
        {"customer": "sanjiu-test1"},
        [
            {"key": "customer", "value": "sanjiu-test1"},
            {"key": "customer", "value": "other"},
        ],
        [{"key": "customer", "value": "sanjiu.*"}],
        [{"key": "customer", "value": "sanjiu|other"}],
        [{"key": "customer=~", "value": ".*"}],
        [{"key": "customer", "value": ""}],
        [{"key": "customer", "value": "sanjiu", "operator": "="}],
    ],
)
def test_loki_scope_policy_rejects_duplicate_fuzzy_or_logql_conditions(
    conditions: object,
) -> None:
    with pytest.raises(NonRetryableExecutionError) as rejected:
        normalize_loki_scope_policy_draft(
            {
                "resource_revision_id": "loki-revision-1",
                "conditions": conditions,
            }
        )
    assert rejected.value.error_code == "loki_scope_policy_invalid"


def test_loki_scope_policy_zero_match_publishes_immutable_revision() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    platform = runtime.platform_config_service
    platform.upsert_environment(
        {"code": "loki-policy-env"},
        actor_id="user_local_admin",
    )
    platform.upsert_base(
        {
            "environment_code": "loki-policy-env",
            "code": "guanlan",
            "engine": "mysql",
        },
        actor_id="user_local_admin",
    )
    resources = platform.governed_resources
    resources.create_resource(
        _loki_payload(code="loki-policy-global", scope_type="global"),
        actor_id="user_local_admin",
    )

    class PassingLokiResourceVerifier:
        def verify(self, **_kwargs: object) -> ResourceVerificationOutcome:
            return ResourceVerificationOutcome(
                status="PASSED",
                provider_contract_version="loki_v1",
                checks={"connection": True, "build_info": True},
            )

    resources.verify_draft(
        "loki-policy-global",
        actor_id="user_local_admin",
        verifier=PassingLokiResourceVerifier(),
    )
    resource_revision = resources.publish_draft(
        "loki-policy-global",
        actor_id="user_local_admin",
    )

    class ZeroMatchVerifier:
        def verify(self, **_kwargs: object) -> LokiScopePolicyVerificationOutcome:
            return LokiScopePolicyVerificationOutcome(
                status="PASSED",
                verifier_version="loki-scope-series.v1",
                match_count=0,
                zero_match_warning=True,
                result_summary={"match_hash": "0" * 64, "duration_ms": 3},
                safe_error_summary="Loki selector 当前未匹配到日志流",
            )

    policies = platform.loki_scope_policies
    policies.verifier = ZeroMatchVerifier()  # type: ignore[assignment]
    created = policies.create(
        {
            "code": "loki-policy-guanlan",
            "environment_code": "loki-policy-env",
            "base_code": "guanlan",
            "resource_revision_id": resource_revision["id"],
            "conditions": [
                {"key": "customer", "value": "loki-policy-env"},
                {"key": "workshop", "value": "guanlan"},
            ],
        },
        actor_id="user_local_admin",
    )
    evidence = policies.verify(
        "loki-policy-guanlan",
        expected_draft_revision=1,
        actor_id="user_local_admin",
    )
    assert evidence["status"] == "PASSED"
    assert evidence["zero_match_warning"] is True
    assert evidence["result_summary"] == {"match_hash": "0" * 64, "duration_ms": 3}
    assert "conditions" not in evidence["result_summary"]
    published = policies.publish(
        "loki-policy-guanlan",
        verification_id=str(evidence["id"]),
        expected_policy_revision=1,
        actor_id="user_local_admin",
    )
    repeated = policies.publish(
        "loki-policy-guanlan",
        verification_id=str(evidence["id"]),
        expected_policy_revision=1,
        actor_id="user_local_admin",
    )
    assert repeated["id"] == published["id"]
    assert published["health_status"] == "EMPTY"
    assert published["conditions"] == created["draft"]["conditions"]
    assert policies.detail("loki-policy-guanlan")["draft"] is None

    release = _publish_builtin_tool(runtime, "query_loki")
    application = runtime.business_application_service.create(
        actor_id="user_local_admin",
        code="loki-policy-usage",
        name="Loki Policy Usage",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    application_payload = draft_payload()
    application_payload["target_paths"] = [
        {
            "target_scope_type": "base",
            "environment_code": "loki-policy-env",
            "base_code": "guanlan",
            "workshop_code": "",
        }
    ]
    application_payload["builtin_tools"] = [
        {
            "tool_release_id": release["id"],
            "resources": [
                {
                    "resource_slot": "loki",
                    "target_scope_type": "base",
                    "environment_code": "loki-policy-env",
                    "base_code": "guanlan",
                    "workshop_code": "",
                    "placement": "",
                    "resource_revision_id": resource_revision["id"],
                    "workshop_partition_policy_revision_id": "",
                    "loki_scope_policy_revision_id": published["id"],
                }
            ],
        }
    ]
    application_revision = runtime.business_application_service.save_draft(
        actor_id="user_local_admin",
        code="loki-policy-usage",
        expected_revision=int(application["revision"]),
        payload=application_payload,
    )
    application_publication = runtime.business_application_service.publish(
        actor_id="user_local_admin",
        code="loki-policy-usage",
        revision_id=str(application_revision["id"]),
    )
    usages = policies.detail("loki-policy-guanlan")["application_usages"]
    assert len(usages) == 1
    assert usages[0]["application_code"] == "loki-policy-usage"
    assert usages[0]["application_publication_id"] == application_publication["id"]
    assert usages[0]["policy_revision_id"] == published["id"]
    assert usages[0]["active"] is False

    class UnavailableVerifier:
        def verify(self, **_kwargs: object) -> LokiScopePolicyVerificationOutcome:
            return LokiScopePolicyVerificationOutcome(
                status="FAILED",
                verifier_version="loki-scope-series.v1",
                result_summary={"match_hash": "0" * 64, "duration_ms": 4},
                safe_error_summary="Loki 上游当前不可用",
            )

    policies.verifier = UnavailableVerifier()  # type: ignore[assignment]
    observation = policies.refresh_health(
        "loki-policy-guanlan",
        policy_revision_id=str(published["id"]),
        actor_id="user_local_admin",
    )
    assert observation["health_status"] == "DEGRADED"
    after_health = policies.repository.get_revision(str(published["id"]))
    assert after_health["status"] == "PUBLISHED"
    assert after_health["health_status"] == "DEGRADED"
    assert observation["safe_error_summary"] == "Loki 上游当前不可用"

    resource_draft = resources.create_draft_from_revision(
        "loki-policy-global",
        str(resource_revision["id"]),
        actor_id="user_local_admin",
    )
    resources.save_draft(
        "loki-policy-global",
        {
            "provider_type": "loki",
            "config": {
                **resource_draft["config"],
                "timeout_seconds": 6,
            },
            "secret_refs": resource_draft["secret_refs"],
        },
        expected_revision=int(resource_draft["draft_revision"]),
        actor_id="user_local_admin",
    )
    resources.verify_draft(
        "loki-policy-global",
        actor_id="user_local_admin",
        verifier=PassingLokiResourceVerifier(),
    )
    current_resource_revision = resources.publish_draft(
        "loki-policy-global",
        actor_id="user_local_admin",
    )

    listed = next(
        item
        for item in policies.list()
        if item["code"] == "loki-policy-guanlan"
    )
    assert listed["resource_ids"] == [resource_revision["resource_id"]]
    assert listed["draft_resource_revision_id"] == ""
    assert listed["published_resource_revision_id"] == resource_revision["id"]
    assert listed["published_policy_revision"] == 1
    detail = policies.detail("loki-policy-guanlan")
    assert len(detail["application_usages"]) == 1
    assert detail["application_usages"][0]["policy_revision_id"] == published["id"]
    assert detail["revisions"][0]["resource_id"] == resource_revision["resource_id"]
    assert detail["revisions"][0]["resource_code"] == "loki-policy-global"
    assert detail["revisions"][0]["resource_revision"] == 1

    copied = policies.copy_revision_to_draft(
        "loki-policy-guanlan",
        source_revision_id=str(published["id"]),
        target_resource_revision_id=str(current_resource_revision["id"]),
        expected_policy_revision=1,
        actor_id="user_local_admin",
    )
    assert copied["resource_revision_id"] == current_resource_revision["id"]
    assert copied["resource_id"] == current_resource_revision["resource_id"]
    assert copied["resource_code"] == "loki-policy-global"
    assert copied["resource_revision"] == 2
    policies.verifier = ZeroMatchVerifier()  # type: ignore[assignment]
    repeated_evidence = policies.verify(
        "loki-policy-guanlan",
        expected_draft_revision=int(copied["draft_revision"]),
        actor_id="user_local_admin",
    )
    assert repeated_evidence["id"] != evidence["id"]
    assert repeated_evidence["status"] == "PASSED"
    assert repeated_evidence["draft_revision"] == copied["draft_revision"]
    assert policies.detail("loki-policy-guanlan")["draft"]["status"] == "VERIFIED"
    changed = policies.save_draft(
        "loki-policy-guanlan",
        expected_draft_revision=int(copied["draft_revision"]),
        payload={
            "resource_revision_id": current_resource_revision["id"],
            "conditions": [
                {"key": "customer", "value": "loki-policy-env"},
                {"key": "workshop", "value": "guanlan-next"},
            ],
        },
        actor_id="user_local_admin",
    )
    assert changed["status"] == "DRAFT"
    assert policies.repository.get_revision(str(published["id"]))["conditions"] == [
        {"key": "customer", "value": "loki-policy-env"},
        {"key": "workshop", "value": "guanlan"},
    ]
    runtime.database.close()
