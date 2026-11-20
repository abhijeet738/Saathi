
"""Outbound adapter: n8n calls these endpoints instead of talking to Telegram/WhatsApp itself.

That keeps the bot tokens in .env. A failed Telegram/WhatsApp call becomes HTTP 502 with a
safe message (no tokens), and an invalid request such as a too-long button becomes HTTP 400.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core import channels
from ..core.channels import ChannelError

router = APIRouter(prefix="/channels", tags=["channels"])

Channel = Literal["telegram", "whatsapp", "test"]


class Button(BaseModel):
    text: str = Field(max_length=40)
    # Telegram's callback_data limit is 64 bytes; core/channels.py re-checks it in bytes.
    data: str = Field(max_length=64)


class SendRequest(BaseModel):
    channel: Channel
    chat_id: str
    text: str = Field(min_length=1, max_length=4000)
    buttons: list[Button] = Field(default_factory=list)


class ChatRef(BaseModel):
    channel: Channel
    chat_id: str


class CallbackAck(BaseModel):
    channel: Channel
    callback_query_id: str | None = None
    text: str = ""


def _message_id(raw: dict) -> str | None:
    """Best-effort id of the sent message, so n8n can log it. None for the test channel."""
    try:
        if "result" in raw:  # Telegram
            return str(raw["result"]["message_id"])
        if raw.get("messages"):  # WhatsApp
            return str(raw["messages"][0]["id"])
    except (KeyError, TypeError, IndexError):
        pass
    return None


@router.post("/send")
def send(req: SendRequest) -> dict:
    try:
        raw = channels.send_text(req.channel, req.chat_id, req.text, [b.model_dump() for b in req.buttons])
    except ChannelError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "sent", "message_id": _message_id(raw), "raw": raw}


@router.post("/typing")
def typing(req: ChatRef) -> dict:
    channels.typing(req.channel, req.chat_id)
    return {"status": "ok"}


@router.post("/answer-callback")
def answer_callback(req: CallbackAck) -> dict:
    channels.answer_callback(req.channel, req.callback_query_id, req.text)
    return {"status": "ok"}
