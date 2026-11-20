
"""Voice notes -> text, photos -> description (+ receipt fields).

n8n sends only a reference to the file (Telegram file_id / WhatsApp media id). The API
downloads it with the bot token, so the token never leaves .env, then asks Gemini.
"""

import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from ..core.channels import ChannelError, fetch_media
from ..core.llm import LLMError, file_part, generate_json, generate_text, load_prompt

router = APIRouter(prefix="/media", tags=["media"])

IMAGE_KINDS = {"receipt", "document", "screenshot", "photo", "other"}
TEXT_CONTENT_MAX = 1500


class MediaRef(BaseModel):
    channel: Literal["telegram", "whatsapp"]
    file_ref: str = Field(min_length=1, max_length=512)  # Telegram file_id or WhatsApp media id
    mime_type: str
    caption: str | None = Field(default=None, max_length=500)

    @field_validator("mime_type")
    @classmethod
    def _plain_mime_type(cls, value: str) -> str:
        # WhatsApp sends e.g. "audio/ogg; codecs=opus". Gemini wants just "audio/ogg".
        base = value.split(";")[0].strip().lower()
        if not re.fullmatch(r"[a-z]+/[a-z0-9.+-]+", base):
            raise ValueError("invalid mime type")
        return base


# Gemini response schemas. Fields have no defaults on purpose: the Gemini API rejects defaults.
class Receipt(BaseModel):
    amount: float | None
    merchant: str | None
    date: str | None  # ISO date if visible
    category: str | None


class ImageResult(BaseModel):
    kind: str  # receipt | document | screenshot | photo | other
    description: str
    text_content: str | None
    receipt: Receipt | None


def _download(ref: MediaRef, expected_type: str) -> bytes:
    """Fetch the file, turning each failure into a clear HTTP error."""
    if not ref.mime_type.startswith(expected_type + "/"):
        raise HTTPException(status_code=415, detail=f"expected {expected_type}/*, got {ref.mime_type}")
    try:
        return fetch_media(ref.channel, ref.file_ref)
    except ChannelError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:  # file larger than MAX_UPLOAD_MB
        raise HTTPException(status_code=413, detail=str(exc)) from exc


@router.post("/transcribe")
def transcribe(ref: MediaRef) -> dict:
    audio = _download(ref, "audio")
    try:
        text = generate_text(load_prompt("transcribe"), [file_part(audio, ref.mime_type)], temperature=0)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"text": text or "[unclear audio]"}


@router.post("/image", response_model=ImageResult)
def analyze_image(ref: MediaRef) -> ImageResult:
    image = _download(ref, "image")
    # Break any closing tag in the caption, so it cannot escape the <caption> wrapper in the prompt.
    caption = (ref.caption or "(no caption)").replace("</", "<\u200b/")
    prompt = load_prompt("image_analyze", caption=caption)
    try:
        result = generate_json(prompt, ImageResult, [file_part(image, ref.mime_type)])
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Do not trust the model's output blindly.
    if result.kind not in IMAGE_KINDS:
        result.kind = "other"
    if result.kind != "receipt":
        result.receipt = None
    if result.text_content:
        result.text_content = result.text_content[:TEXT_CONTENT_MAX]
    return result
