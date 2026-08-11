from __future__ import annotations

from .errors import PolicyViolation
import re

ALLOWED_SELECTOR_LABELS = {
    "app",
    "cluster",
    "container",
    "logtype",
    "region",
    "replica",
    "role",
    "service",
    "service_name",
}
ALLOWED_DISCOVERY_LABELS = ALLOWED_SELECTOR_LABELS.union({"customer", "workshop"})
_EXACT_VALUE = re.compile(r"[^\x00-\x1f*?{}|]{1,256}")


def assert_loki_label_allowed(label: str) -> None:
    if label not in ALLOWED_DISCOVERY_LABELS:
        raise PolicyViolation(f"Loki selector label is not allowed: {label}")


def build_effective_selector(
    selector: dict[str, str],
    *,
    mandatory_conditions: tuple[tuple[str, str], ...] = (),
    require_mandatory: bool = False,
) -> dict[str, str]:
    """AND exact diagnostic filters with an immutable mandatory Scope Policy."""

    mandatory = dict(mandatory_conditions)
    if require_mandatory and not mandatory:
        raise PolicyViolation("Published Loki Scope Policy is required")
    effective = dict(mandatory)
    for label, value in selector.items():
        if label not in ALLOWED_SELECTOR_LABELS:
            raise PolicyViolation(f"Loki selector label is not allowed: {label}")
        if label in mandatory:
            raise PolicyViolation("Loki diagnostic filter cannot override mandatory scope")
        if _EXACT_VALUE.fullmatch(str(value)) is None:
            raise PolicyViolation("Loki selector value must be exact")
        effective[label] = str(value)
    if not effective:
        raise PolicyViolation("Loki selector is required")
    return effective
