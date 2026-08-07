from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest

from app.bootstrap import build_test_container
from app.modules.internal_api_platform.domain.errors import PolicyViolation
from app.modules.internal_api_platform.domain.loki_policy import build_effective_selector
from app.modules.platform_config.application.governed_resources import (
    ResourceVerificationOutcome,
)
from app.modules.platform_config.application.loki_scope_policy_verifier import (
    LokiScopePolicyTechnicalVerifier,
)
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_business_application_control_plane import (
    control_plane_settings,
)


GLOBAL_LOKI_URL = "http://10.0.103.102:3100"
ENVIRONMENT_LOKI_URL = "http://loki.sanjiu-test2.internal:3100"
OBSERVED_LABEL_CHAIN = (
    "customer",
    "workshop",
    "role",
    "app",
    "replica",
    "logtype",
)


def _loki_payload(
    *,
    code: str,
    scope_type: str,
    base_url: str,
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
            "tenant_id": "tenant1",
            "timeout_seconds": 5,
            "max_minutes": 60,
            "max_lines": 200,
            "max_response_bytes": 65536,
        },
        "secret_refs": {},
    }


class _PassingLokiResourceVerifier:
    def verify(self, **_kwargs: object) -> ResourceVerificationOutcome:
        return ResourceVerificationOutcome(
            status="PASSED",
            provider_contract_version="loki_v1",
            checks={"connection": True, "build_info": True},
        )


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self._raw


def test_global_and_environment_loki_configs_enforce_cascade_and_scope() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    platform = runtime.platform_config_service
    for environment_code, bases in (
        ("sanjiu-test1", ("guanlan",)),
        ("sanjiu-test2", ("guanlan", "chenzhou")),
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
        _loki_payload(
            code="loki-unified-global",
            scope_type="global",
            base_url=GLOBAL_LOKI_URL,
        ),
        actor_id="user_local_admin",
    )
    resources.create_resource(
        _loki_payload(
            code="loki-sanjiu-test2",
            scope_type="environment",
            environment_code="sanjiu-test2",
            base_url=ENVIRONMENT_LOKI_URL,
        ),
        actor_id="user_local_admin",
    )

    discovery_calls: list[dict[str, object]] = []

    class SnapshotDiscoveryGateway:
        def test_and_labels(self, **kwargs: object) -> list[str]:
            discovery_calls.append({"operation": "test", **kwargs})
            return list(OBSERVED_LABEL_CHAIN)

        def label_values(self, **kwargs: object) -> list[str]:
            discovery_calls.append({"operation": "values", **kwargs})
            draft = dict(kwargs["draft"])  # type: ignore[arg-type]
            config = dict(draft["config"])
            label = str(kwargs["label"])
            conditions = dict(kwargs["conditions"])  # type: ignore[arg-type]
            if label == "customer":
                return (
                    ["sanjiu-test2"]
                    if config["base_url"] == ENVIRONMENT_LOKI_URL
                    else ["sanjiu-test1", "sanjiu-test2"]
                )
            if label == "workshop" and conditions == {"customer": "sanjiu-test1"}:
                return ["guanlan"]
            if label == "workshop" and conditions == {"customer": "sanjiu-test2"}:
                return ["chenzhou", "guanlan", "shunfeng"]
            return []

    platform.loki_draft_discovery.gateway = SnapshotDiscoveryGateway()
    global_test = platform.loki_draft_discovery.test_draft(
        "loki-unified-global",
        actor_id="user_local_admin",
    )
    assert global_test["labels"] == sorted(OBSERVED_LABEL_CHAIN)
    global_customers = platform.loki_draft_discovery.label_values(
        "loki-unified-global",
        test_session_id=str(global_test["test_session_id"]),
        label="customer",
        selected_conditions={},
        actor_id="user_local_admin",
    )
    assert global_customers["values"] == ["sanjiu-test1", "sanjiu-test2"]
    global_bases = platform.loki_draft_discovery.label_values(
        "loki-unified-global",
        test_session_id=str(global_test["test_session_id"]),
        label="workshop",
        selected_conditions={"customer": "sanjiu-test1"},
        actor_id="user_local_admin",
    )
    assert global_bases["values"] == ["guanlan"]

    environment_test = platform.loki_draft_discovery.test_draft(
        "loki-sanjiu-test2",
        actor_id="user_local_admin",
    )
    environment_customers = platform.loki_draft_discovery.label_values(
        "loki-sanjiu-test2",
        test_session_id=str(environment_test["test_session_id"]),
        label="customer",
        selected_conditions={},
        actor_id="user_local_admin",
    )
    assert environment_customers["values"] == ["sanjiu-test2"]
    environment_bases = platform.loki_draft_discovery.label_values(
        "loki-sanjiu-test2",
        test_session_id=str(environment_test["test_session_id"]),
        label="workshop",
        selected_conditions={"customer": "sanjiu-test2"},
        actor_id="user_local_admin",
    )
    assert environment_bases["values"] == ["chenzhou", "guanlan", "shunfeng"]
    assert discovery_calls[-1]["conditions"] == {"customer": "sanjiu-test2"}

    verifier = _PassingLokiResourceVerifier()
    resource_revisions: dict[str, dict[str, object]] = {}
    for code in ("loki-unified-global", "loki-sanjiu-test2"):
        resources.verify_draft(code, actor_id="user_local_admin", verifier=verifier)
        resource_revisions[code] = resources.publish_draft(
            code,
            actor_id="user_local_admin",
        )

    policies = platform.loki_scope_policies
    with pytest.raises(NonRetryableExecutionError) as cross_environment:
        policies.create(
            {
                "code": "loki-cross-environment-invalid",
                "environment_code": "sanjiu-test1",
                "resource_revision_id": resource_revisions["loki-sanjiu-test2"]["id"],
                "conditions": [{"key": "customer", "value": "sanjiu-test1"}],
            },
            actor_id="user_local_admin",
        )
    assert cross_environment.value.error_code == "loki_scope_policy_resource_invalid"

    policy_http_calls: list[dict[str, object]] = []

    def fake_urlopen(request: object, *, timeout: int) -> _Response:
        full_url = str(getattr(request, "full_url"))
        selector = parse_qs(urlparse(full_url).query)["match[]"][0]
        policy_http_calls.append(
            {
                "url": full_url,
                "selector": selector,
                "tenant": getattr(request, "get_header")("X-scope-orgid"),
                "timeout": timeout,
            }
        )
        data: list[dict[str, str]] = []
        if selector == '{customer="sanjiu-test1",workshop="guanlan"}':
            data = [{"customer": "sanjiu-test1", "workshop": "guanlan"}]
        return _Response({"status": "success", "data": data})

    policies.verifier = LokiScopePolicyTechnicalVerifier(
        resolve_secret=lambda _ref: "",
        urlopen_func=fake_urlopen,
    )
    base_policy = policies.create(
        {
            "code": "loki-sanjiu-test1-guanlan",
            "environment_code": "sanjiu-test1",
            "base_code": "guanlan",
            "resource_revision_id": resource_revisions["loki-unified-global"]["id"],
            "conditions": [
                {"key": "customer", "value": "sanjiu-test1"},
                {"key": "workshop", "value": "guanlan"},
            ],
        },
        actor_id="user_local_admin",
    )
    environment_policy = policies.create(
        {
            "code": "loki-sanjiu-test2-environment",
            "environment_code": "sanjiu-test2",
            "resource_revision_id": resource_revisions["loki-sanjiu-test2"]["id"],
            "conditions": [{"key": "customer", "value": "sanjiu-test2"}],
        },
        actor_id="user_local_admin",
    )

    published_policies: dict[str, dict[str, object]] = {}
    for code in ("loki-sanjiu-test1-guanlan", "loki-sanjiu-test2-environment"):
        evidence = policies.verify(
            code,
            expected_draft_revision=1,
            actor_id="user_local_admin",
        )
        published_policies[code] = policies.publish(
            code,
            verification_id=str(evidence["id"]),
            expected_policy_revision=1,
            actor_id="user_local_admin",
        )

    assert policy_http_calls == [
        {
            "url": policy_http_calls[0]["url"],
            "selector": '{customer="sanjiu-test1",workshop="guanlan"}',
            "tenant": "tenant1",
            "timeout": 5,
        },
        {
            "url": policy_http_calls[1]["url"],
            "selector": '{customer="sanjiu-test2"}',
            "tenant": "tenant1",
            "timeout": 5,
        },
    ]
    assert base_policy["draft"]["conditions"] == [
        {"key": "customer", "value": "sanjiu-test1"},
        {"key": "workshop", "value": "guanlan"},
    ]
    assert environment_policy["draft"]["conditions"] == [
        {"key": "customer", "value": "sanjiu-test2"}
    ]
    assert published_policies["loki-sanjiu-test1-guanlan"]["health_status"] == "HEALTHY"
    assert (
        published_policies["loki-sanjiu-test2-environment"]["health_status"] == "EMPTY"
    )
    assert published_policies["loki-sanjiu-test2-environment"]["conditions"] == [
        {"key": "customer", "value": "sanjiu-test2"}
    ]

    effective = build_effective_selector(
        {"role": "edge", "logtype": "data-sync-ERROR"},
        mandatory_conditions=(
            ("customer", "sanjiu-test1"),
            ("workshop", "guanlan"),
        ),
        require_mandatory=True,
    )
    assert effective == {
        "customer": "sanjiu-test1",
        "workshop": "guanlan",
        "role": "edge",
        "logtype": "data-sync-ERROR",
    }
    with pytest.raises(PolicyViolation):
        build_effective_selector(
            {"customer": "sanjiu-test2"},
            mandatory_conditions=(
                ("customer", "sanjiu-test1"),
                ("workshop", "guanlan"),
            ),
            require_mandatory=True,
        )
    with pytest.raises(PolicyViolation):
        build_effective_selector(
            {"workshop": "chenzhou"},
            mandatory_conditions=(
                ("customer", "sanjiu-test1"),
                ("workshop", "guanlan"),
            ),
            require_mandatory=True,
        )

    runtime.database.close()
