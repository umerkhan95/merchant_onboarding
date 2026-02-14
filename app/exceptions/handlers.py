from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.exceptions.errors import AppError


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": "about:blank",
                "title": type(exc).__name__,
                "status": exc.status_code,
                "detail": exc.detail,
                "instance": str(request.url),
            },
        )
