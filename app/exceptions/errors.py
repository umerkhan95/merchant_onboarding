class AppError(Exception):
    """Base application error."""

    def __init__(self, detail: str, status_code: int = 500) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class ValidationError(AppError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail=detail, status_code=422)


class NotFoundError(AppError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail=detail, status_code=404)


class AuthenticationError(AppError):
    def __init__(self, detail: str = "Invalid or missing API key") -> None:
        super().__init__(detail=detail, status_code=401)


class ForbiddenError(AppError):
    def __init__(self, detail: str = "Insufficient permissions") -> None:
        super().__init__(detail=detail, status_code=403)


class SSRFError(AppError):
    def __init__(self, detail: str = "URL validation failed") -> None:
        super().__init__(detail=detail, status_code=400)


class CircuitOpenError(AppError):
    def __init__(self, domain: str) -> None:
        super().__init__(detail=f"Circuit breaker open for {domain}", status_code=503)


class ExtractionError(AppError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail=detail, status_code=502)
