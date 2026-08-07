from __future__ import annotations

import json

import pytest

from app.modules.platform_config.application.governed_resources import (
    ResourceVerificationOutcome,
)
from app.bootstrap import build_test_container
from app.modules.platform_config.application.workshop_partition_policies import (
    normalize_workshop_partition_draft,
)
from app.modules.platform_config.application.workshop_partition_verifier import (
    RedisWorkshopPartitionTechnicalVerifier,
)
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_business_application_control_plane import (
    control_plane_settings,
)


def _policy_payload(
    *,
    database_rule_enabled: bool = True,
    database_table_prefix: object = "GL001_",
    redis_rule_enabled: bool = True,
    redis_prefixes: object = None,
) -> dict[str, object]:
    return {
        "database_rule_enabled": database_rule_enabled,
        "database_table_prefix": database_table_prefix,
        "redis_rule_enabled": redis_rule_enabled,
        "redis_prefixes": (
            ["cr999.crmes.CRMES_TEST_GL#GL001@$"] if redis_prefixes is None else redis_prefixes
        ),
    }


def test_workshop_partition_policy_accepts_exact_database_and_redis_prefixes() -> None:
    normalized = normalize_workshop_partition_draft(
        _policy_payload(
            redis_prefixes=[
                "cr999.crmes.CRMES_TEST_GL#GL001@$",
                "cr999.crmes.CRMES_ARCHIVE_GL#GL001@$",
            ]
        ),
        workshop_code="GL001",
    )

    assert normalized == {
        "database_rule_enabled": True,
        "database_table_prefix": "GL001_",
        "redis_rule_enabled": True,
        "redis_prefixes": [
            "cr999.crmes.CRMES_ARCHIVE_GL#GL001@$",
            "cr999.crmes.CRMES_TEST_GL#GL001@$",
        ],
    }


@pytest.mark.parametrize(
    "database_table_prefix",
    ["", "   ", ["GL001_", "GL002_"], "GL001*", "GL001%", "^GL001_"],
)
def test_workshop_partition_policy_rejects_missing_multiple_or_fuzzy_database_prefix(
    database_table_prefix: object,
) -> None:
    with pytest.raises(NonRetryableExecutionError) as rejected:
        normalize_workshop_partition_draft(
            _policy_payload(
                database_table_prefix=database_table_prefix,
                redis_rule_enabled=False,
                redis_prefixes=[],
            ),
            workshop_code="GL001",
        )

    assert rejected.value.error_code == "workshop_partition_policy_invalid"


@pytest.mark.parametrize(
    "redis_prefixes",
    [
        [],
        ["GL001"],
        ["*GL001*"],
        ["^cr999.*GL001$"],
        ["cr999.crmes.CRMES_TEST_GL#GL002@$"],
        [
            "cr999.crmes.CRMES_TEST_GL#GL001@$",
            "cr999.crmes.CRMES_TEST_GL#GL001@$",
        ],
    ],
)
def test_workshop_partition_policy_rejects_incomplete_fuzzy_or_duplicate_redis_prefixes(
    redis_prefixes: object,
) -> None:
    with pytest.raises(NonRetryableExecutionError) as rejected:
        normalize_workshop_partition_draft(
            _policy_payload(
                database_rule_enabled=False,
                database_table_prefix="",
                redis_prefixes=redis_prefixes,
            ),
            workshop_code="GL001",
        )

    assert rejected.value.error_code == "workshop_partition_policy_invalid"


def test_workshop_partition_policy_rejects_hidden_or_empty_rules() -> None:
    for payload in (
        _policy_payload(
            database_rule_enabled=False,
            database_table_prefix="GL001_",
            redis_rule_enabled=False,
            redis_prefixes=[],
        ),
        _policy_payload(
            database_rule_enabled=False,
            database_table_prefix="",
            redis_rule_enabled=False,
            redis_prefixes=["cr999.crmes.CRMES_TEST_GL#GL001@$"],
        ),
    ):
        with pytest.raises(NonRetryableExecutionError) as rejected:
            normalize_workshop_partition_draft(payload, workshop_code="GL001")
        assert rejected.value.error_code == "workshop_partition_policy_invalid"


def test_workshop_partition_policy_lifecycle_freezes_revisions_and_requires_copy() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    runtime.platform_config_service.upsert_environment(
        {"code": "policy-lifecycle"},
        actor_id="user_local_admin",
    )
    runtime.platform_config_service.upsert_base(
        {
            "environment_code": "policy-lifecycle",
            "code": "guanlan",
            "engine": "mysql",
        },
        actor_id="user_local_admin",
    )
    runtime.platform_config_service.upsert_workshop(
        {
            "environment_code": "policy-lifecycle",
            "base_code": "guanlan",
            "code": "GL001",
        },
        actor_id="user_local_admin",
    )
    service = runtime.platform_config_service.workshop_partition_policies
    database_only = _policy_payload(
        redis_rule_enabled=False,
        redis_prefixes=[],
    )
    created = service.create(
        {
            "code": "policy-lifecycle-gl001",
            "environment_code": "policy-lifecycle",
            "base_code": "guanlan",
            "workshop_code": "GL001",
            **database_only,
        },
        actor_id="user_local_admin",
    )
    assert created["draft"]["draft_revision"] == 1
    assert created["draft"]["status"] == "DRAFT"

    evidence = service.verify(
        "policy-lifecycle-gl001",
        expected_draft_revision=1,
        actor_id="user_local_admin",
    )
    assert evidence["status"] == "PASSED"
    assert evidence["redis_summary"]["enabled"] is False
    first = service.publish(
        "policy-lifecycle-gl001",
        verification_id=str(evidence["id"]),
        expected_policy_revision=1,
        actor_id="user_local_admin",
    )
    repeated = service.publish(
        "policy-lifecycle-gl001",
        verification_id=str(evidence["id"]),
        expected_policy_revision=1,
        actor_id="user_local_admin",
    )
    assert repeated["id"] == first["id"]
    assert first["revision"] == 1
    assert first["database_table_prefix"] == "GL001_"
    assert first["redis_prefixes"] == []
    assert service.detail("policy-lifecycle-gl001")["draft"] is None

    with pytest.raises(NonRetryableExecutionError) as missing_draft:
        service.save_draft(
            "policy-lifecycle-gl001",
            expected_draft_revision=1,
            payload={**database_only, "database_table_prefix": "GL001_NEXT_"},
            actor_id="user_local_admin",
        )
    assert missing_draft.value.error_code == "workshop_partition_policy_draft_missing"

    copied = service.copy_revision_to_draft(
        "policy-lifecycle-gl001",
        source_revision_id=str(first["id"]),
        expected_policy_revision=1,
        actor_id="user_local_admin",
    )
    assert copied["draft_revision"] == 2
    changed = service.save_draft(
        "policy-lifecycle-gl001",
        expected_draft_revision=2,
        payload={**database_only, "database_table_prefix": "GL001_NEXT_"},
        actor_id="user_local_admin",
    )
    assert changed["draft_revision"] == 3
    assert changed["status"] == "DRAFT"
    next_evidence = service.verify(
        "policy-lifecycle-gl001",
        expected_draft_revision=3,
        actor_id="user_local_admin",
    )
    second = service.publish(
        "policy-lifecycle-gl001",
        verification_id=str(next_evidence["id"]),
        expected_policy_revision=1,
        actor_id="user_local_admin",
    )
    assert second["revision"] == 2
    assert second["database_table_prefix"] == "GL001_NEXT_"

    detail = service.detail("policy-lifecycle-gl001")
    assert [item["revision"] for item in detail["revisions"]] == [2, 1]
    assert detail["revisions"][1]["database_table_prefix"] == "GL001_"
    assert detail["revisions"][1]["content_hash"] == first["content_hash"]
    runtime.database.close()


def test_redis_policy_verifier_scans_each_exact_prefix_once_without_persisting_keys() -> None:
    calls: list[dict[str, object]] = []

    class Client:
        def scan(self, **kwargs: object) -> tuple[int, list[str]]:
            calls.append(kwargs)
            if "ARCHIVE" in str(kwargs["match"]):
                return 0, []
            return 9, ["business-key-1", "business-key-2", "business-key-3"]

        def close(self) -> None:
            return None

    verifier = RedisWorkshopPartitionTechnicalVerifier(
        resolve_secret=lambda _ref: "",
        connect_factory=lambda **_kwargs: Client(),
        scan_count=2,
    )
    prefixes = (
        "cr999.crmes.CRMES_TEST_GL#GL001@$",
        "cr999.crmes.CRMES_ARCHIVE_GL#GL001@$",
    )
    outcome = verifier.verify_redis(
        resource_revision={
            "provider_type": "redis",
            "config": {
                "host": "redis.internal",
                "port": 6379,
                "database": 0,
                "username": "",
                "tls": {"enabled": False, "verify_certificate": True},
            },
            "secret_refs": {},
        },
        prefixes=prefixes,
    )

    assert [call["match"] for call in calls] == [f"{prefix}*" for prefix in prefixes]
    assert all(call["cursor"] == 0 and call["count"] == 2 for call in calls)
    assert outcome.status == "PASSED"
    assert outcome.zero_match_warning is True
    assert outcome.redis_summary["probes"][0]["match_count"] == 2
    assert outcome.redis_summary["probes"][0]["truncated"] is True
    persisted = json.dumps(outcome.redis_summary, ensure_ascii=False)
    assert "business-key" not in persisted
    assert all(prefix not in persisted for prefix in prefixes)


def test_redis_policy_zero_match_warning_can_be_published_with_covering_resource() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    platform = runtime.platform_config_service
    platform.upsert_environment({"code": "policy-redis"}, actor_id="user_local_admin")
    platform.upsert_base(
        {
            "environment_code": "policy-redis",
            "code": "guanlan",
            "engine": "mysql",
        },
        actor_id="user_local_admin",
    )
    platform.upsert_workshop(
        {
            "environment_code": "policy-redis",
            "base_code": "guanlan",
            "code": "GL001",
        },
        actor_id="user_local_admin",
    )
    resources = platform.governed_resources
    created_resource = resources.create_resource(
        {
            "code": "policy-redis-base",
            "name": "Policy Redis",
            "resource_kind": "redis",
            "scope_type": "base",
            "environment_code": "policy-redis",
            "base_code": "guanlan",
            "provider_type": "redis",
            "config": {
                "host": "redis.internal",
                "port": 6379,
                "database": 0,
                "username": "",
                "tls": {"enabled": False, "verify_certificate": True},
            },
            "secret_refs": {},
        },
        actor_id="user_local_admin",
    )

    class PassingRedisResourceVerifier:
        def verify(self, **_kwargs: object) -> ResourceVerificationOutcome:
            return ResourceVerificationOutcome(
                status="PASSED",
                provider_contract_version="redis_v1",
                checks={"connection": True, "ping": True},
            )

    resources.verify_draft(
        "policy-redis-base",
        actor_id="user_local_admin",
        verifier=PassingRedisResourceVerifier(),
    )
    resource_revision = resources.publish_draft(
        "policy-redis-base",
        actor_id="user_local_admin",
    )
    assert created_resource["resource"]["scope_type"] == "base"

    class EmptyClient:
        def scan(self, **_kwargs: object) -> tuple[int, list[str]]:
            return 0, []

        def close(self) -> None:
            return None

    policies = platform.workshop_partition_policies
    policies.redis_verifier = RedisWorkshopPartitionTechnicalVerifier(
        resolve_secret=lambda _ref: "",
        connect_factory=lambda **_kwargs: EmptyClient(),
    )
    policies.create(
        {
            "code": "policy-redis-gl001",
            "environment_code": "policy-redis",
            "base_code": "guanlan",
            "workshop_code": "GL001",
            **_policy_payload(database_rule_enabled=False, database_table_prefix=""),
        },
        actor_id="user_local_admin",
    )
    evidence = policies.verify(
        "policy-redis-gl001",
        expected_draft_revision=1,
        redis_resource_revision_id=str(resource_revision["id"]),
        actor_id="user_local_admin",
    )
    assert evidence["status"] == "PASSED"
    assert evidence["zero_match_warning"] is True
    assert evidence["redis_resource_revision_id"] == resource_revision["id"]
    assert "cr999.crmes" not in json.dumps(evidence["redis_summary"])
    published = policies.publish(
        "policy-redis-gl001",
        verification_id=str(evidence["id"]),
        expected_policy_revision=1,
        actor_id="user_local_admin",
    )
    assert published["status"] == "PUBLISHED"
    runtime.database.close()
