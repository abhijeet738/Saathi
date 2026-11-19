"""Public health endpoint (no API key). Used by Docker's HEALTHCHECK and uptime monitors."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..db import ping

router = APIRouter(tags=["health"])


# Plain `def` on purpose: ping() blocks, so FastAPI runs this in a worker thread.
@router.get("/health")
def health() -> JSONResponse:
    db_ok = ping()
    # 503 when the database is unreachable, so Docker and uptime monitors see a failure.
    return JSONResponse(
        status_code=200 if db_ok else 503,
        content={"status": "ok" if db_ok else "degraded", "db": db_ok},
    )
