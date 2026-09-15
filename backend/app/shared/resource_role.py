"""Resource instance selector, deliberately independent of authorization roles."""

import re

RESOURCE_ROLE_PATTERN = r"^[A-Za-z0-9\u3400-\u9fff_.:-]{1,64}$"
RESOURCE_ROLE_MESSAGE = "资源角色最多 64 字符，仅支持中文、字母、数字及 _ . : -；可留空"


def normalize_resource_role(value: object | None) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(RESOURCE_ROLE_MESSAGE)
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(RESOURCE_ROLE_MESSAGE)
    role = value.strip()
    if role and not re.fullmatch(RESOURCE_ROLE_PATTERN, role):
        raise ValueError(RESOURCE_ROLE_MESSAGE)
    return role
