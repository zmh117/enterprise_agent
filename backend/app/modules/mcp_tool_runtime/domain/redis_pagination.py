from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace

from app.shared.exceptions import ToolPolicyError


def invalid_scan_cursor() -> ToolPolicyError:
    return ToolPolicyError(
        "Redis pagination position is invalid",
        safe_message="分页游标无效，请从第一页重新查询",
        error_code="mcp_pagination_cursor_invalid",
    )


def stale_scan_cursor() -> ToolPolicyError:
    return ToolPolicyError(
        "Redis scan batch or topology changed during pagination",
        safe_message="Redis 扫描批次或集群拓扑已变化，请从第一页重新查询",
        error_code="mcp_pagination_cursor_stale",
    )


def scan_fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def _unsigned(value: object) -> bool:
    return type(value) is int and 0 <= value < 2**64


def _digest(value: object) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


@dataclass(frozen=True)
class RedisScanPosition:
    """Bounded replay state; never stores keys or cluster addresses in a public cursor."""

    provider_cursor: int = 0
    offset: int = 0
    batch_hash: str = ""
    node_index: int = 0
    topology_hash: str = ""

    @classmethod
    def parse(cls, value: object) -> RedisScanPosition:
        # Scalar cursors also support existing standalone pages and the fake adapter.
        if _unsigned(value):
            assert isinstance(value, int)
            return cls(provider_cursor=value)
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise invalid_scan_cursor()
        if not all(_unsigned(value[k]) for k in ("provider_cursor", "offset", "node_index")):
            raise invalid_scan_cursor()
        if (value["offset"] == 0 and value["batch_hash"] != "") or (
            value["offset"] > 0 and not _digest(value["batch_hash"])
        ):
            raise invalid_scan_cursor()
        if value["topology_hash"] != "" and not _digest(value["topology_hash"]):
            raise invalid_scan_cursor()
        if value["node_index"] and not value["topology_hash"]:
            raise invalid_scan_cursor()
        return cls(**value)

    def as_cursor(self) -> dict[str, object]:
        return asdict(self)

    def page(
        self, keys: list[str], *, next_cursor: int, limit: int, node_count: int = 1
    ) -> tuple[list[str], object]:
        # COUNT is a provider hint. Re-read the same batch until every key is emitted.
        # Sorting tolerates ordering changes, but membership/next-cursor changes fail closed.
        ordered = sorted(keys)
        batch_hash = scan_fingerprint([next_cursor, ordered])
        if self.offset and (batch_hash != self.batch_hash or self.offset >= len(ordered)):
            raise stale_scan_cursor()
        page = ordered[self.offset : self.offset + limit]
        consumed = self.offset + len(page)
        if consumed < len(ordered):
            return page, replace(self, offset=consumed, batch_hash=batch_hash).as_cursor()
        if next_cursor:
            return page, replace(
                self, provider_cursor=next_cursor, offset=0, batch_hash=""
            ).as_cursor()
        if self.node_index + 1 < node_count:
            return page, replace(
                self, provider_cursor=0, offset=0, batch_hash="", node_index=self.node_index + 1
            ).as_cursor()
        return page, 0


def valid_scan_position(value: object) -> bool:
    try:
        RedisScanPosition.parse(value)
        return True
    except ToolPolicyError:
        return False


def scan_complete(value: object) -> bool:
    # A structured zero provider cursor may still have a batch remainder or another node.
    return type(value) is int and value == 0
