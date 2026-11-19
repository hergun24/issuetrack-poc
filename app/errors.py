"""Error types matching the 06-API-CONTRACT-REFERENCE error shape.

Every error response is:
    {"error": {"code": "<CODE>", "message": "<text>"}}
with optional "details": [{"field": ..., "reason": ...}] for 422/400.
"""

from typing import Optional


class ApiError(Exception):
    """Raised by service layer / dependencies; converted to JSON by main app."""

    def __init__(self, status_code: int, code: str, message: str,
                 details: Optional[list] = None, headers: Optional[dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details  # list of {"field": ..., "reason": ...}
        self.headers = headers or {}


class Validation(ApiError):
    """422 semantic validation failure."""

    def __init__(self, message: str = "Validation error.", details: Optional[list] = None):
        super().__init__(422, "VALIDATION_ERROR", message, details)


class Detail:
    """One entry of an error response "details" array."""

    def __init__(self, field, reason):
        self.field = field
        self.reason = reason

    def to_dict(self):
        return {"field": self.field, "reason": self.reason}

    def __repr__(self):
        return f"Detail(field={self.field!r}, reason={self.reason!r})"


# Standard helpers ---------------------------------------------------------

def not_found(message: str = "Resource not found."):
    return ApiError(404, "NOT_FOUND", message)


def forbidden(message: str = "Forbidden."):
    return ApiError(403, "FORBIDDEN", message)


def conflict(message: str):
    return ApiError(409, "CONFLICT", message)


def unauthenticated():
    return ApiError(401, "UNAUTHENTICATED", "Authentication required.")


def auth_failed():
    """Identical body for unknown email / wrong password (SEC-002)."""
    return ApiError(401, "AUTHENTICATION_FAILED", "Invalid credentials.")


def rate_limited():
    return ApiError(429, "RATE_LIMITED", "Too many requests; slow down.")


def internal():
    return ApiError(500, "INTERNAL_ERROR", "An unexpected error occurred.")
