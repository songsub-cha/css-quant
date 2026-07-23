"""Password hashing — argon2id (SoT B4.6).

``PasswordHasher`` defaults to the Argon2id variant, so no extra
configuration is needed to satisfy the SoT's "argon2id" requirement.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHash):
        return False
