from __future__ import annotations

import json

import pytest

from app.modules.internal_api_platform.domain.errors import PolicyViolation
from app.modules.internal_api_platform.domain.redis_policy import enforce_key_namespace
from app.modules.internal_api_platform.domain.sql.analyzer import analyze_readonly_query
from app.modules.internal_api_platform.domain.topology import DatabaseEngine
from app.modules.platform_config.application.workshop_partition_verifier import (
    RedisWorkshopPartitionTechnicalVerifier,
)


DATABASE_PREFIXES = {
    "GL001": "GL001_",
    "GL002": "GL002_",
    "CZ002": "CZ002_",
}

REDIS_PREFIXES = {
    "GL001": "cr999.crmes.CRMES_TEST_GL#GL001@$",
    "GL002": "cr999.crmes.CRMES_TEST_GL#GL002@$",
    "CZ002": "cr999.crmes.CRMES_TEST_CZ#CZ002@$",
}

REDIS_KEYS = {
    "GL001": (
        "cr999.crmes.CRMES_TEST_GL#GL001@$"
        "EBRDataText.809901890274822.Sheet4.rows",
        "cr999.crmes.CRMES_TEST_GL#GL001@$"
        "[WEIGH]:wo.20250627MAOYAN10-yapi5:weigh_id.list",
        "cr999.crmes.CRMES_TEST_GL#GL001@$"
        "[BATCH_RECORD]:674351510281286:exec_param",
        "cr999.crmes.CRMES_TEST_GL#GL001@$"
        "[BATCH_RECORD]:675454427238982:states",
    ),
    # GL002 follows the same deployed namespace contract as the supplied GL001 sample.
    "GL002": (
        "cr999.crmes.CRMES_TEST_GL#GL002@$"
        "EBRDataText.809901890274822.Sheet4.rows",
    ),
    "CZ002": (
        "cr999.crmes.CRMES_TEST_CZ#CZ002@$"
        "[WEIGH]:wo.20260410-11:weigh_id.list",
    ),
}


@pytest.mark.parametrize("workshop_code", tuple(DATABASE_PREFIXES))
def test_database_table_prefix_allows_own_workshop_and_rejects_cross_scope(
    workshop_code: str,
) -> None:
    prefix = DATABASE_PREFIXES[workshop_code]
    own_table = f"{workshop_code}_EBR_ORDER"

    analyzed = analyze_readonly_query(
        f"select * from {own_table}",
        engine=DatabaseEngine.MYSQL,
        max_rows=50,
        table_prefix=prefix,
    )
    assert analyzed.tables == [own_table]

    for other_code in DATABASE_PREFIXES.keys() - {workshop_code}:
        with pytest.raises(PolicyViolation):
            analyze_readonly_query(
                f"select * from {other_code}_EBR_ORDER",
                engine=DatabaseEngine.MYSQL,
                max_rows=50,
                table_prefix=prefix,
            )


@pytest.mark.parametrize("workshop_code", tuple(REDIS_PREFIXES))
def test_redis_namespace_allows_complete_keys_and_rejects_cross_scope(
    workshop_code: str,
) -> None:
    prefix = REDIS_PREFIXES[workshop_code]
    for key in REDIS_KEYS[workshop_code]:
        assert enforce_key_namespace(key, key_prefixes=(prefix,)) == prefix

    for other_code in REDIS_PREFIXES.keys() - {workshop_code}:
        with pytest.raises(PolicyViolation):
            enforce_key_namespace(
                REDIS_KEYS[other_code][0],
                key_prefixes=(prefix,),
            )


def test_real_redis_namespaces_preserve_exact_scope_when_all_probes_match_zero() -> None:
    calls: list[dict[str, object]] = []

    class EmptyClient:
        def scan(self, **kwargs: object) -> tuple[int, list[str]]:
            calls.append(kwargs)
            return 0, []

        def close(self) -> None:
            return None

    verifier = RedisWorkshopPartitionTechnicalVerifier(
        resolve_secret=lambda _ref: "",
        connect_factory=lambda **_kwargs: EmptyClient(),
        scan_count=100,
    )
    exact_prefixes = tuple(REDIS_PREFIXES.values())
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
        prefixes=exact_prefixes,
    )

    assert outcome.status == "PASSED"
    assert outcome.zero_match_warning is True
    assert outcome.redis_summary["prefix_count"] == 3
    assert [call["match"] for call in calls] == [
        f"{prefix}*" for prefix in exact_prefixes
    ]
    assert all(call["cursor"] == 0 and call["count"] == 100 for call in calls)

    persisted = json.dumps(outcome.redis_summary, ensure_ascii=False)
    assert all(prefix not in persisted for prefix in exact_prefixes)
    assert all(key not in persisted for keys in REDIS_KEYS.values() for key in keys)
