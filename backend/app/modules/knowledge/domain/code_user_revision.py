"""Recognize explicit numeric SVN versions in the actual user request, never tool arguments."""

import re
from app.modules.knowledge.domain.code_answers import svn_revision
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError

# Deliberately exclude unrelated order numbers/dates. A bare number is ambiguous.
_VERSION = re.compile(
    r"(?i)(?<![\w])(?:svn\s*(?:版本(?:号)?\s*)?[=:：#]?\s*r?\s*|r)([0-9]{1,19})(?![\w.])"
)


def user_svn_revisions(text: str) -> tuple[int, ...]:
    if not isinstance(text, str) or len(text) > 128000:
        raise CodeKnowledgeError("SVN_REVISION_REQUIRED")
    values = tuple(sorted({svn_revision(int(match[1])) for match in _VERSION.finditer(text)}))
    if not 1 <= len(values) <= 2:
        raise CodeKnowledgeError("SVN_REVISION_REQUIRED")
    return values
