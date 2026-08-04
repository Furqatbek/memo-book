"""Closed enum of API error codes (spec Part 5) and domain exceptions.

The frontend switches on `code`, never on `message`. Add codes here only —
nowhere else — so the enum stays the single source of truth.
"""
from enum import StrEnum


class ErrorCode(StrEnum):
    PHOTOS_INSUFFICIENT = "PHOTOS_INSUFFICIENT"
    INVALID_PAGE_TIER = "INVALID_PAGE_TIER"
    INVALID_PLACEMENT = "INVALID_PLACEMENT"
    RESOLUTION_TOO_LOW = "RESOLUTION_TOO_LOW"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    BOOK_LOCKED = "BOOK_LOCKED"
    BOOK_EXPIRED = "BOOK_EXPIRED"
    ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    SIGNATURE_INVALID = "SIGNATURE_INVALID"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    PREVIEW_NOT_CONFIRMED = "PREVIEW_NOT_CONFIRMED"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"


class DomainError(Exception):
    """Base class for domain rule violations. Carries a closed-enum code."""

    def __init__(self, code: ErrorCode, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class InvalidPlacement(DomainError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(ErrorCode.INVALID_PLACEMENT, message, details)


class IllegalTransition(DomainError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(ErrorCode.ILLEGAL_TRANSITION, message, details)


class AmountMismatch(DomainError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(ErrorCode.AMOUNT_MISMATCH, message, details)
