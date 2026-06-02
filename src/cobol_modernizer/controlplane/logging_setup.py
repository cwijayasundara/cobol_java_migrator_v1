"""Make the control plane observable: a formatted handler on the `cobol_modernizer`
logger (so app logs show alongside uvicorn's), plus a catch-all exception handler
that logs the full traceback for ANY unhandled error and returns its type+message
in the response — so a 500 is never silent again.

Level is `LOG_LEVEL` (default INFO). Idempotent; safe to call at import + startup."""
from __future__ import annotations

import logging
import os
import sys

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("cobol_modernizer")

# UI status-poll endpoints the cockpit hits every 1.5–10s (useJob backoff + SSE).
# A successful GET to one of these is noise that buries real events, so we drop it
# from uvicorn's access log — POSTs, 4xx/5xx, and everything else still log.
_POLL_SUFFIXES = ("/enrichment", "/stages", "/budget", "/blueprint/improve", "/events")


class _AccessLogPollFilter(logging.Filter):
    """Suppress uvicorn.access lines for successful UI status polls.

    uvicorn logs access records as `'%s - "%s %s HTTP/%s" %d'` with
    args = (client_addr, method, full_path, http_version, status_code); we read
    that tuple. Anything that isn't a 2xx/3xx GET to a known poll path passes
    through unchanged, so mutations and errors stay visible."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        method, path, status = args[1], args[2], args[4]
        try:
            code = int(status)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return True
        if method != "GET" or code >= 400:
            return True
        return not str(path).split("?", 1)[0].endswith(_POLL_SUFFIXES)


def quiet_access_logs() -> None:
    """Attach the poll filter to uvicorn's access logger (idempotent). Disable with
    QUIET_POLL_LOGS=0 to see every request again."""
    if os.getenv("QUIET_POLL_LOGS", "1").lower() in ("0", "false", "no"):
        return
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _AccessLogPollFilter) for f in access.filters):
        access.addFilter(_AccessLogPollFilter())


def configure_logging(level: str | None = None) -> logging.Logger:
    lvl = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    if not any(getattr(h, "_cobol_mod", False) for h in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s :: %(message)s", "%H:%M:%S"))
        handler._cobol_mod = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.setLevel(lvl)
    logger.propagate = False  # don't double-log through the root logger
    quiet_access_logs()
    return logger


def install_exception_logging(app: FastAPI) -> None:
    """Log every unhandled exception with a traceback and return a JSON 500 whose
    `detail` names the error, instead of an opaque empty 500."""
    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": f"{type(exc).__name__}: {exc}"})
