from __future__ import annotations

from dataclasses import dataclass, field

from .addressing import TargetRef
from .errors import AuthorizationError

_WILDCARD = "*"


@dataclass(frozen=True)
class ScopeRule:
    """A single grant. '*' matches any value at that level."""

    environment: str = _WILDCARD
    base: str = _WILDCARD
    workshop: str = _WILDCARD

    def matches(self, target: TargetRef) -> bool:
        if self.environment not in {_WILDCARD, target.environment}:
            return False
        if self.base not in {_WILDCARD, target.base}:
            return False
        if self.workshop == _WILDCARD:
            return True
        return target.workshop == self.workshop


@dataclass(frozen=True)
class AccessScope:
    """The set of grants a single caller holds."""

    rules: list[ScopeRule] = field(default_factory=list)

    def allows(self, target: TargetRef) -> bool:
        return any(rule.matches(target) for rule in self.rules)


@dataclass(frozen=True)
class AccessPolicy:
    scopes: dict[str, AccessScope] = field(default_factory=dict)

    def authorize(self, *, user_id: str, target: TargetRef) -> None:
        if not user_id:
            raise AuthorizationError("Caller identity is required")
        scope = self.scopes.get(user_id)
        if scope is None or not scope.allows(target):
            location = f"{target.environment}/{target.base}"
            if target.workshop:
                location = f"{location}/{target.workshop}"
            raise AuthorizationError(f"Caller is not authorized for {location}")
