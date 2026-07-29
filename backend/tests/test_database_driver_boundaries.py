from __future__ import annotations

from app.modules.internal_api_platform.infrastructure.db.drivers import (
    _rows_from_cursor,
)


class Cursor:
    description = [("id",), ("text",)]

    def fetchmany(self, _count: int) -> list[tuple[object, ...]]:
        return [
            (1, "ok"),
            (2, "过大" * 100),
            (3, "not-reached"),
        ]


def test_cursor_rows_are_bounded_by_rows_and_utf8_bytes() -> None:
    result = _rows_from_cursor(
        Cursor(),
        3,
        max_response_bytes=30,
    )

    assert result.rows == [{"id": 1, "text": "ok"}]
    assert result.truncated is True
    assert 0 < result.response_bytes <= 30
