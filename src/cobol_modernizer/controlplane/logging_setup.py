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
