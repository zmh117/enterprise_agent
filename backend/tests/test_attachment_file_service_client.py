from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from app.modules.attachments.file_service_client import FileServiceAttachmentImporter
from app.shared.exceptions import NonRetryableExecutionError


class _TokenProvider:
    def access_token(self) -> str:
        return "opaque-test-token"


def _http_error(payload: dict[str, str]) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="http://file-service/internal/v1/attachments/opaque/content",
        code=403,
        msg="Forbidden",
        hdrs={},
        fp=io.BytesIO(json.dumps(payload).encode()),
    )


def test_attachment_importer_preserves_bounded_file_service_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(*_args: object, **_kwargs: object) -> object:
        raise _http_error(
            {
                "error": "文件扩展名与媒体类型不一致",
                "error_code": "document_source_media_type_mismatch",
            }
        )

    monkeypatch.setattr(urllib.request, "urlopen", reject)
    importer = FileServiceAttachmentImporter(
        base_url="http://file-service",
        allowed_hosts=("file-service",),
        token_provider=_TokenProvider(),
    )

    with pytest.raises(NonRetryableExecutionError) as denied:
        importer.import_content(
            attachment_id="attachment-opaque",
            data=b"safe bytes",
            content_type="image/jpeg",
        )

    assert denied.value.error_code == "document_source_media_type_mismatch"
    assert denied.value.safe_message == "附件导入被拒绝"


def test_attachment_importer_rejects_untrusted_remote_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(*_args: object, **_kwargs: object) -> object:
        raise _http_error(
            {
                "error": "do not copy this response",
                "error_code": "unexpected.remote/value",
            }
        )

    monkeypatch.setattr(urllib.request, "urlopen", reject)
    importer = FileServiceAttachmentImporter(
        base_url="http://file-service",
        allowed_hosts=("file-service",),
        token_provider=_TokenProvider(),
    )

    with pytest.raises(NonRetryableExecutionError) as denied:
        importer.import_content(
            attachment_id="attachment-opaque",
            data=b"safe bytes",
            content_type="image/jpeg",
        )

    assert denied.value.error_code == "file_attachment_import_denied"
    assert "do not copy" not in str(denied.value)
