from __future__ import annotations

import pytest

from app.modules.managed_channel.domain import (
    DingTalkEnterpriseStatus,
    normalize_dingtalk_corp_id,
    require_dingtalk_enterprise_transition,
    require_immutable_dingtalk_corp_id,
)
from app.shared.exceptions import NonRetryableExecutionError


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("PENDING_VERIFICATION", "ACTIVE"),
        ("PENDING_VERIFICATION", "DISABLED"),
        ("ACTIVE", "DISABLED"),
        ("DISABLED", "PENDING_VERIFICATION"),
        ("DISABLED", "ARCHIVED"),
        ("ARCHIVED", "PENDING_VERIFICATION"),
    ],
)
def test_dingtalk_enterprise_allows_only_governed_transitions(
    current: str,
    target: str,
) -> None:
    assert require_dingtalk_enterprise_transition(current, target) == target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("PENDING_VERIFICATION", "ARCHIVED"),
        ("ACTIVE", "PENDING_VERIFICATION"),
        ("ACTIVE", "ARCHIVED"),
        ("DISABLED", "ACTIVE"),
        ("ARCHIVED", "ACTIVE"),
    ],
)
def test_dingtalk_enterprise_rejects_illegal_transitions(
    current: str,
    target: str,
) -> None:
    with pytest.raises(
        NonRetryableExecutionError,
        match="Illegal DingTalk enterprise transition",
    ):
        require_dingtalk_enterprise_transition(current, target)


def test_dingtalk_corp_id_is_trimmed_but_kept_opaque_and_immutable() -> None:
    assert normalize_dingtalk_corp_id("  dingCorpABC123  ") == "dingCorpABC123"
    assert require_immutable_dingtalk_corp_id("", "dingCorpABC123") == "dingCorpABC123"
    assert (
        require_immutable_dingtalk_corp_id("dingCorpABC123", " dingCorpABC123 ") == "dingCorpABC123"
    )

    with pytest.raises(NonRetryableExecutionError) as mismatch:
        require_immutable_dingtalk_corp_id("dingCorpABC123", "dingCorpOther")
    assert mismatch.value.error_code == "dingtalk_corp_id_mismatch"


@pytest.mark.parametrize("value", ["", "   ", "corp id", "corp\nid", "x" * 129])
def test_dingtalk_corp_id_rejects_empty_whitespace_control_and_oversize(
    value: str,
) -> None:
    with pytest.raises(NonRetryableExecutionError) as error:
        normalize_dingtalk_corp_id(value)
    assert error.value.error_code == "dingtalk_corp_id_invalid"


def test_dingtalk_enterprise_status_has_exact_four_state_vocabulary() -> None:
    assert {item.value for item in DingTalkEnterpriseStatus} == {
        "PENDING_VERIFICATION",
        "ACTIVE",
        "DISABLED",
        "ARCHIVED",
    }
