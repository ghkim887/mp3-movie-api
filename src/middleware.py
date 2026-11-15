"""Record request IDs, response status codes, and elapsed time."""

import logging
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

from .diagnostics import current_request_id, journal

logger = logging.getLogger(__name__)


async def log_requests(request: Request, call_next):
    """Log one request and attach its request ID to the response."""
    request_id = uuid.uuid4().hex[:8]
    request.state.request_id = request_id
    started = time.perf_counter()
    capture = request.url.path != "/" and not request.url.path.startswith(("/ui/", "/static/", "/sample_movies.csv"))
    token = journal.begin(request_id, request.method, request.url.path) if capture else None

    try:
        try:
            response = await call_next(request)
        except Exception:
            logger.error(
                "request_id=%s Unexpected error handling %s %s",
                request_id, request.method, request.url.path, exc_info=True,
            )
            response = JSONResponse(status_code=500, content={"detail": "Internal server error"})

        duration_ms = (time.perf_counter() - started) * 1000
        message = (
            f"request_id={request_id} {request.method} {request.url.path} "
            f"status={response.status_code} duration={duration_ms:.1f}ms"
        )
        if response.status_code >= 500:
            logger.error(message)
        elif response.status_code >= 400:
            logger.warning(message)
        else:
            logger.info(message)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        if token is not None:
            current_request_id.reset(token)
