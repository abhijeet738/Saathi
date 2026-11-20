
"""Thin wrapper around the Gemini SDK. The only file that talks to Gemini for text, JSON and files.

Swap models or providers here without touching routers. Model names come from .env.
"""

import re
import time
from functools import lru_cache
from pathlib import Path

from google import genai
from google.genai import errors, types

from ..config import get_settings

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Temporary Gemini failures worth retrying: rate limit (429) and server-side hiccups.
RETRY_CODES = {429, 500, 503, 504}
RETRY_DELAYS = (1.5, 4.0)  # seconds to wait before attempt 2 and attempt 3
REQUEST_TIMEOUT_MS = 60_000

_sleep = time.sleep  # tests replace this so they do not really wait


class LLMError(RuntimeError):
    """The model call failed or returned something unusable."""


@lru_cache
def client() -> genai.Client:
    return genai.Client(
        api_key=get_settings().gemini_api_key,
        http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
    )


def load_prompt(name: str, /, **values: str) -> str:
    """Read app/prompts/<name>.md and fill its {placeholders}.

    `name` is positional-only, so a prompt may have a {name} placeholder of its own.
    Without values the file is returned as is. With values, any literal curly brace in the
    prompt (for example a JSON example) must be written doubled: {{ and }}.
    """
    if not re.fullmatch(r"[a-z0-9_]+", name):
        raise ValueError(f"invalid prompt name: {name!r}")
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    return text.format(**values) if values else text


def fence(text: str, label: str = "data") -> str:
    """Wrap untrusted text (emails, web pages, saved facts) so the model treats it as data.

    Any closing tag inside the text is broken, so the content cannot escape the wrapper.
    The prompt itself must also say that fenced content is never to be obeyed as instructions.
    """
    safe = text.replace("</", "<\u200b/")
    return f"<{label}>\n{safe}\n</{label}>"


def _call_model(**kwargs):
    """generate_content with a couple of retries for rate limits and temporary server errors."""
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            return client().models.generate_content(model=get_settings().gemini_chat_model, **kwargs)
        except errors.APIError as exc:
            retryable = exc.code in RETRY_CODES
            if not retryable or attempt == len(RETRY_DELAYS):
                raise LLMError(f"gemini request failed (HTTP {exc.code})") from exc
            _sleep(RETRY_DELAYS[attempt])
    raise AssertionError("unreachable")  # the loop always returns or raises


def generate_text(prompt: str, parts: list | None = None, temperature: float = 0.3) -> str:
    resp = _call_model(
        contents=[prompt, *(parts or [])],
        config=types.GenerateContentConfig(temperature=temperature),
    )
    return (resp.text or "").strip()


def generate_json(prompt: str, schema, parts: list | None = None):
    """Returns an instance of `schema` (a Pydantic model, or list[Model])."""
    resp = _call_model(
        contents=[prompt, *(parts or [])],
        config=types.GenerateContentConfig(
            temperature=0.1,
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )
    if resp.parsed is None:
        raise LLMError(f"model returned unparseable JSON: {(resp.text or '')[:200]!r}")
    return resp.parsed


def file_part(data: bytes, mime_type: str) -> types.Part:
    """Audio, image or PDF bytes -> a part Gemini can read."""
    return types.Part.from_bytes(data=data, mime_type=mime_type)
