from __future__ import annotations

from datetime import UTC, datetime

from app.modules.dingding.application.dingtalk_stream_service import _attachments


def test_attachment_keeps_safe_original_unicode_file_name() -> None:
    attachments = _attachments(
        {
            "msgtype": "file",
            "content": {
                "downloadCode": "opaque-download-code",
                "fileName": "生产拓扑图 终版.PNG",
            },
        },
        credential_ttl_seconds=300,
    )

    assert [item.file_name for item in attachments] == ["生产拓扑图 终版.PNG"]


def test_native_picture_without_file_name_uses_local_message_time() -> None:
    created_at = int(datetime(2026, 8, 19, 1, 40, 47, tzinfo=UTC).timestamp() * 1000)
    attachments = _attachments(
        {
            "msgtype": "picture",
            "createAt": created_at,
            "content": {"downloadCode": "opaque-download-code"},
        },
        credential_ttl_seconds=300,
    )

    assert [item.file_name for item in attachments] == ["图片-20260819-094047.png"]


def test_attachment_file_name_drops_source_path_and_replaces_unsafe_characters() -> None:
    attachments = _attachments(
        {
            "msgtype": "file",
            "content": {
                "downloadCode": "opaque-download-code",
                "fileName": r"C:\Users\user\生产图?.png",
            },
        },
        credential_ttl_seconds=300,
    )

    assert [item.file_name for item in attachments] == ["生产图_.png"]
