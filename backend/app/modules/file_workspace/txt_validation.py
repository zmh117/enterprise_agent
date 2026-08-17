"""Bounded compatibility facade for legacy TXT-only callers.

New workspace code must use :mod:`text_format_policy` and pass the frozen
policy version explicitly. Keeping this adapter prevents old jobs and tests
from inheriting text-v2 behavior implicitly.
"""

from app.modules.file_workspace.text_format_policy import (
    MAX_TEXT_BYTES,
    TextStreamValidator,
    TextValidationResult,
)


MAX_TXT_BYTES = MAX_TEXT_BYTES
TxtValidationResult = TextValidationResult


class TxtStreamValidator(TextStreamValidator):
    pass
