"""Password hashing and legacy verification for the Shopbot admin."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets

_ITERATIONS = 600_000
_DEFAULT_HASH = hashlib.sha256(b"admin123").hexdigest()


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not 1 <= len(password) <= 1024:
        raise ValueError("invalid password length")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> tuple[bool, bool]:
    """Return (valid, needs_rehash); never treat a stored hash as a password."""
    if not isinstance(password, str) or not 1 <= len(password) <= 1024 or not stored or stored == "admin123" or stored.lower() == _DEFAULT_HASH:
        return False, False
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, iterations_text, salt_hex, digest_hex = stored.split("$")
            iterations = int(iterations_text)
            salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
            if not 100_000 <= iterations <= 2_000_000 or len(salt) != 16 or len(expected) != 32:
                return False, False
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            return hmac.compare_digest(actual, expected), iterations < _ITERATIONS
        except (ValueError, TypeError):
            return False, False
    if re.fullmatch(r"[0-9a-fA-F]{64}", stored):
        actual = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(actual, stored.lower()), True
    return hmac.compare_digest(password.encode("utf-8"), stored.encode("utf-8")), True
