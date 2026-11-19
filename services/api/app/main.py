"""Saathi API entry point.

Each phase adds its routers to the PROTECTED ROUTERS block below, one line per router:
    app.include_router(channels.router, dependencies=protected)
Only /health is public. Every other route requires the X-API-Key header.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from .db import close_pool
from .routers import health
from .security import require_api_key

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    # Shutdown: release database connections cleanly.
    close_pool()


app = FastAPI(title="Saathi API", version="1.0.0", lifespan=lifespan)

# Public: used by Docker's health check and uptime monitors.
app.include_router(health.router)

# Applied to every router below, so a new router cannot forget authentication.
protected = [Depends(require_api_key)]

# --- PROTECTED ROUTERS (added phase by phase) ---
# Phase 1: channels, media
# Phase 2: inbox, brief
# Phase 3: brain, memory
# Phase 4: money
