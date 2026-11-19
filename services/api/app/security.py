"""API-key check. Every route except /health requires the X-API-Key header."""

import secrets

from fastapi import Header, HTTPException

from .config import get_settings


def require_api_key(x_api_key: str = Header(default="")) -> None:
    expected = get_settings().saathi_api_key
    # Compare as bytes in constant time: avoids timing leaks, and non-ASCII input
    # cannot raise an error (which would return 500 instead of 401).
    if not secrets.compare_digest(x_api_key.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="invalid api key")
