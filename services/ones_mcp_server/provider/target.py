from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit


class ProviderContractError(ValueError):
    """Raised when deployment configuration violates the fixed ONES contract."""


@dataclass(frozen=True, slots=True)
class ProviderTarget:
    base_url: str
    host: str
    allow_insecure_local: bool


def validate_provider_target(
    base_url: str,
    *,
    allowed_hosts: tuple[str, ...],
    app_env: str,
    allow_insecure_local: bool,
) -> ProviderTarget:
    candidate = base_url.strip()
    parsed = urlsplit(candidate)
    host = (parsed.hostname or "").lower().rstrip(".")
    hosts = {item.strip().lower().rstrip(".") for item in allowed_hosts if item.strip()}
    if not candidate or not host or host not in hosts:
        raise ProviderContractError("ONES Provider host is not allowlisted")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProviderContractError("ONES Provider URL must be an origin without credentials")
    if parsed.path not in {"", "/"}:
        raise ProviderContractError("ONES Provider URL must not include an API path")
    if parsed.scheme == "https":
        return ProviderTarget(candidate.rstrip("/"), host, False)
    local_http = (
        parsed.scheme == "http"
        and allow_insecure_local
        and app_env.strip().lower() in {"local", "test"}
    )
    if not local_http:
        raise ProviderContractError("ONES Provider must use HTTPS")
    return ProviderTarget(candidate.rstrip("/"), host, True)
