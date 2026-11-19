"""FastAPI application factory + error handling (contract error shape)."""

import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import router as api_router
from .db import DB
from .errors import ApiError
from .ops import logger, setup_logging

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")

# Restrictive CORS (SEC-025): no wildcard; no credentials.
_CORS_ORIGINS = [
    "http://localhost:40309",
    "http://localhost:47775",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://0.0.0.0:8000",
]


def create_app(db_path: str, disable_ratelimit: bool = False, auto_seed: bool = True) -> FastAPI:
    setup_logging()
    app = FastAPI(title="IssueTrack Lite", version="0.2.0-rc1", docs_url=None, redoc_url=None)

    db = DB(db_path)
    app.state.db = db
    app.state.disable_ratelimit = disable_ratelimit

    if auto_seed:
        from .seed import seed  # local import avoids module-load ordering issues
        seed(db, force=False)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(api_router)

    @app.get("/", include_in_schema=False)
    def index():
        with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as fh:
            return fh.read()

    @app.get("/app.js", include_in_schema=False)
    def app_js():
        with open(os.path.join(STATIC_DIR, "app.js"), encoding="utf-8") as fh:
            return fh.read()

    @app.get("/styles.css", include_in_schema=False)
    def styles():
        with open(os.path.join(STATIC_DIR, "styles.css"), encoding="utf-8") as fh:
            return fh.read()

    # ---------------- error handlers ----------------

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        body = {"error": {"code": exc.code, "message": exc.message}}
        if exc.details:
            body["error"]["details"] = [d.to_dict() for d in exc.details]
        if exc.status_code == 429:
            body["error"]["details"] = body.get("error", {}).get("details") or [
                {"field": None, "reason": "Rate limit exceeded; try again later."}]
        if exc.status_code == 500:
            logger.error("api.500", extra={"path": request.url.path})
        elif exc.status_code in (401, 403, 409):
            logger.info("api.denied", extra={"status": exc.status_code, "path": request.url.path})
        return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        # Malformed bodies / contract shape errors -> 400 VALIDATION_ERROR
        details = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc") if x != "body")
            details.append({"field": loc or "body", "reason": str(err.get("msg"))})
        if exc.errors() and any("value is not a valid email address" in str(e.get("msg")) for e in exc.errors()):
            return JSONResponse(status_code=400, content={
                "error": {"code": "VALIDATION_ERROR",
                          "message": "Registration failed." if "register" in request.url.path else "Login failed.",
                          "details": [{"field": "email", "reason": "Invalid email."}]}})
        return JSONResponse(status_code=400, content={
            "error": {"code": "VALIDATION_ERROR", "message": "Malformed request body.",
                      "details": details}})

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        code = "NOT_FOUND"
        if exc.status_code == 401:
            code = "UNAUTHENTICATED"
        elif exc.status_code == 403:
            code = "FORBIDDEN"
        elif exc.status_code == 405:
            code = "METHOD_NOT_ALLOWED"
        msg = "Resource not found." if exc.status_code == 404 else "Method not allowed."
        return JSONResponse(status_code=exc.status_code, content={
            "error": {"code": code, "message": msg}
        })

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logger.exception("api.unhandled", exc_info=exc)
        return JSONResponse(status_code=500, content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred."}})

    # The rate limiter is per-app state: each create_app() installs its own
    # instance into app.state so that creating multiple app instances in one
    # process (tests) does not share rate-limit state.  disable_ratelimit=True
    # installs a passthrough instead.  It must NOT mutate shared module state,
    # or a later create_app(disable_ratelimit=False) would silently inherit a
    # passthrough (that bug broke test_login_rate_limit_429 in the full suite).
    from .ops import SlidingWindowLimiter

    class _Passthrough:
        def allow(self, key):
            return True

    if disable_ratelimit:
        app.state.auth_limiter = _Passthrough()
    else:
        app.state.auth_limiter = SlidingWindowLimiter(max_events=20, window_seconds=60.0)

    return app
