"""Strict source decoding shared by the readonly Runtime and SVN history executor."""

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError


def decode_source(data: bytes) -> tuple[str, str]:
    encodings = (
        ("utf-16",)
        if data.startswith((b"\xff\xfe", b"\xfe\xff"))
        else (("utf-8-sig",) if data.startswith(b"\xef\xbb\xbf") else ("utf-8", "gb18030"))
    )
    for encoding in encodings:
        try:
            text = data.decode(encoding)
            if "\x00" in text or any(ord(c) < 9 or 13 < ord(c) < 32 for c in text):
                raise CodeKnowledgeError("CODE_SOURCE_BINARY")
            return text, encoding
        except UnicodeError:
            continue
    raise CodeKnowledgeError("CODE_SOURCE_ENCODING_UNSUPPORTED")
