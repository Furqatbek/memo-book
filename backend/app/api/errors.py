"""The consistent error envelope (spec Part 5):
{"error": {"code": ..., "message": ..., "details": {...}}}
The frontend switches on `code`, never on `message`.
"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.domain.errors import DomainError, ErrorCode

STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.PHOTOS_INSUFFICIENT: 409,
    ErrorCode.INVALID_PAGE_TIER: 422,
    ErrorCode.INVALID_PLACEMENT: 422,
    ErrorCode.RESOLUTION_TOO_LOW: 422,
    ErrorCode.VERSION_CONFLICT: 409,
    ErrorCode.VERSION_REQUIRED: 428,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.BOOK_LOCKED: 423,
    ErrorCode.BOOK_EXPIRED: 410,
    ErrorCode.ILLEGAL_TRANSITION: 409,
    ErrorCode.AMOUNT_MISMATCH: 400,
    ErrorCode.SIGNATURE_INVALID: 403,
    ErrorCode.ORDER_NOT_FOUND: 404,
    ErrorCode.PREVIEW_NOT_CONFIRMED: 422,
    ErrorCode.PREVIEW_STALE: 409,
    ErrorCode.PAGES_INCOMPLETE: 409,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.RATE_LIMITED: 429,
}


def envelope(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=STATUS_BY_CODE.get(exc.code, 400),
            content=envelope(exc.code.value, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {"loc": [str(part) for part in e["loc"]], "msg": e["msg"], "type": e["type"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=envelope(ErrorCode.VALIDATION_ERROR.value,
                             "request validation failed", {"errors": errors}),
        )
