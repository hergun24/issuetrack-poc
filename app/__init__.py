"""Contract-shaped error handling helpers."""

from .errors import ApiError, Detail  # re-export

__all__ = ["ApiError", "Detail"]
