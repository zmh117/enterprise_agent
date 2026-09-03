from __future__ import annotations

import re
from typing import Any


EXTERNAL_ACTION_CONFIRMATION_CARD_PURPOSE = "external_action_confirmation"
EXTERNAL_ACTION_CONFIRMATION_CARD_CONTRACT_VERSION = "external-action-confirmation-v1"

_CARD_TEMPLATE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,248}\.schema$")


def normalize_dingtalk_card_template_id(value: object) -> str:
    candidate = str(value or "").strip()
    return candidate if _CARD_TEMPLATE_ID_PATTERN.fullmatch(candidate) else ""


def external_action_confirmation_card_binding(
    metadata: dict[str, Any],
    *,
    connector_id: str,
    connector_revision: int,
) -> dict[str, Any] | None:
    card_templates = metadata.get("card_templates")
    if not isinstance(card_templates, dict):
        return None
    configured = card_templates.get(EXTERNAL_ACTION_CONFIRMATION_CARD_PURPOSE)
    if not isinstance(configured, dict):
        return None
    template_id = normalize_dingtalk_card_template_id(configured.get("template_id"))
    contract_version = str(configured.get("contract_version") or "").strip()
    if not template_id or contract_version != EXTERNAL_ACTION_CONFIRMATION_CARD_CONTRACT_VERSION:
        return None
    return {
        "purpose": EXTERNAL_ACTION_CONFIRMATION_CARD_PURPOSE,
        "template_id": template_id,
        "contract_version": contract_version,
        "connector_id": connector_id,
        "connector_revision": connector_revision,
    }
