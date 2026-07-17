from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError


class PasswordService:
    def __init__(self) -> None:
        self.hasher = PasswordHasher()

    def hash(self, password: str) -> str:
        if len(password) < 12:
            raise ValueError("Password must contain at least 12 characters")
        return self.hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        if not password_hash:
            return False
        try:
            return bool(self.hasher.verify(password_hash, password))
        except (VerifyMismatchError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self.hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return True
