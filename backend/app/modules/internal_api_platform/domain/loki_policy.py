from __future__ import annotations

from .errors import PolicyViolation
from .topology import Workshop

ALLOWED_SELECTOR_LABELS = {"cluster", "container", "region", "service", "service_name", "workshop"}


def build_effective_selector(
    selector: dict[str, str],
    *,
    workshop: Workshop | None,
) -> dict[str, str]:
    """Merge the caller selector with the workshop label, enforcing the label allowlist."""

    effective = dict(selector)
    for label in effective:
        if label not in ALLOWED_SELECTOR_LABELS:
            raise PolicyViolation(f"Loki selector label is not allowed: {label}")
    if workshop is not None:
        for label, value in workshop.loki_label.items():
            effective[label] = value
    if not effective:
        raise PolicyViolation("Loki selector is required")
    return effective
