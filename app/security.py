"""Token + password utilities."""

import hashlib
import hmac
import secrets

import bcrypt


def new_token() -> str:
    """Opaque bearer token (hex, 64 chars). ≤64 char contract limit."""
    return secrets.token_hex(32)


def token_hash(token: str) -> str:
    """SHA-256 of the raw token; only hashes are persisted at rest."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    # bcrypt cost 12 (modern adaptive hash; SEC-001)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, stored: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
    except ValueError:
        return False


def const_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
