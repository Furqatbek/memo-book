"""Provider registry. Real providers register here as they are integrated."""
from app.config import get_settings
from app.domain.errors import DomainError, ErrorCode
from app.payments.dev import DevPaymentProvider

_dev = DevPaymentProvider()


def available_providers() -> list[str]:
    names = []
    if get_settings().dev_payments_enabled:
        names.append(_dev.name)
    return names


def get_provider(name: str):
    if name == _dev.name and get_settings().dev_payments_enabled:
        return _dev
    raise DomainError(ErrorCode.NOT_FOUND, f"unknown payment provider {name!r}")
