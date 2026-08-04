"""Money: integers in minor units, never floats (spec Part 8).

UZS minor unit is the tiyin: 1 sum = 100 tiyin. Conversion to/from provider
formats happens at the provider boundary only; everything inside the system
is an int in tiyin.
"""
from app.domain.errors import AmountMismatch

MINOR_PER_MAJOR = 100  # tiyin per sum


def to_minor(major: int, minor_part: int = 0) -> int:
    """Build a minor-unit amount from integer major units (+ optional minor part).
    Floats are rejected by design — there is deliberately no float path."""
    if isinstance(major, float) or isinstance(minor_part, float):
        raise TypeError("monetary amounts must be integers, never floats")
    if minor_part < 0 or minor_part >= MINOR_PER_MAJOR:
        raise ValueError(f"minor_part must be in [0, {MINOR_PER_MAJOR})")
    if major < 0:
        raise ValueError("negative amounts are not supported")
    return major * MINOR_PER_MAJOR + minor_part


def from_minor(amount_minor: int) -> tuple[int, int]:
    """Split a minor-unit amount into (major, minor_part)."""
    if isinstance(amount_minor, float):
        raise TypeError("monetary amounts must be integers, never floats")
    if amount_minor < 0:
        raise ValueError("negative amounts are not supported")
    return divmod(amount_minor, MINOR_PER_MAJOR)


def assert_amount_matches(expected_minor: int, received_minor: int) -> None:
    """R10 companion: never trust the amount in a callback — compare it against
    the stored order amount and reject mismatches."""
    if isinstance(expected_minor, float) or isinstance(received_minor, float):
        raise TypeError("monetary amounts must be integers, never floats")
    if expected_minor != received_minor:
        raise AmountMismatch(
            "callback amount does not match order amount",
            {"expected_minor": expected_minor, "received_minor": received_minor},
        )
