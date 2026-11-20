"""Outbound Telegram and WhatsApp channel adapters."""

from typing import Literal

import httpx

from ..config import get_settings

Channel = Literal["telegram", "whatsapp", "test"]


class ChannelError(RuntimeError):
    """A channel provider request failed."""


def _json_result(response):
    if isinstance(response, dict):
        return response
    if hasattr(response, "json"):
        return response.json()
    return response


def _describe(response: httpx.Response) -> str:
    status = f"HTTP {response.status_code}"
    try:
        body = response.json()
    except (ValueError, TypeError):
        body = None

    if isinstance(body, dict):
        description = body.get("description")
        if not description and isinstance(body.get("error"), dict):
            description = body["error"].get("message")
        if isinstance(description, str) and description:
            return f"{status}: {description}"
    return status


def _request(method: str, url: str, what: str, **kwargs) -> dict:
    try:
        response = httpx.request(method, url, timeout=30, **kwargs)
        status_code = getattr(response, "status_code", 200)
        if status_code >= 400:
            raise httpx.HTTPStatusError(
                "provider error",
                request=httpx.Request(method, url),
                response=response,
            )
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise ChannelError(f"{what} failed: {_describe(exc.response)}") from None
    except httpx.RequestError:
        raise ChannelError(f"{what} failed: network request failed") from None
    except ValueError:
        raise ChannelError(f"{what} failed: invalid provider response") from None


def _telegram_settings() -> tuple[str, str]:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise ChannelError("Telegram channel is not configured")
    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    return settings.telegram_bot_token, base


def _whatsapp_settings() -> tuple[str, str, dict]:
    settings = get_settings()
    if not settings.whatsapp_token or not settings.whatsapp_phone_number_id:
        raise ChannelError("WhatsApp channel is not configured")
    base = (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}/"
        f"{settings.whatsapp_phone_number_id}"
    )
    headers = {"Authorization": "Bearer " + settings.whatsapp_token}
    return settings.whatsapp_token, base, headers


def _telegram_button_bytes(buttons: list[dict]) -> None:
    for button in buttons:
        if len(button["data"].encode("utf-8")) > 64:
            raise ValueError("Telegram callback data must be 64 bytes or less")


def send_text(channel: Channel, chat_id: str, text: str, buttons: list[dict] | None = None) -> dict:
    if channel == "test":
        return {"status": "skipped"}
    if channel not in ("telegram", "whatsapp"):
        raise ValueError(f"unsupported channel: {channel}")

    buttons = buttons or []
    if channel == "telegram":
        _telegram_button_bytes(buttons)
        _token, base = _telegram_settings()
        payload = {"chat_id": chat_id, "text": text}
        if buttons:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": button["text"], "callback_data": button["data"]} for button in buttons]
                ]
            }
        return _json_result(_request("POST", f"{base}/sendMessage", "telegram sendMessage", json=payload))

    _token, base, headers = _whatsapp_settings()
    calls: list[dict] = []
    if len(text) > 1024:
        calls.append(
            _request(
                "POST",
                f"{base}/messages",
                "whatsapp text message",
                headers=headers,
                json={
                    "messaging_product": "whatsapp",
                    "to": chat_id,
                    "type": "text",
                    "text": {"body": text},
                },
            )
        )
    if buttons:
        shown = buttons[:3]
        calls.append(
            _request(
                "POST",
                f"{base}/messages",
                "whatsapp buttons",
                headers=headers,
                json={
                    "messaging_product": "whatsapp",
                    "to": chat_id,
                    "type": "interactive",
                    "interactive": {
                        "type": "button",
                        "body": {"text": text if len(text) <= 1024 else "Tap an option below:"},
                        "action": {
                            "buttons": [
                                {
                                    "type": "reply",
                                    "reply": {"id": button["data"], "title": button["text"][:20]},
                                }
                                for button in shown
                            ]
                        },
                    },
                },
            )
        )
    elif len(text) <= 4096:
        calls.append(
            _request(
                "POST",
                f"{base}/messages",
                "whatsapp text message",
                headers=headers,
                json={
                    "messaging_product": "whatsapp",
                    "to": chat_id,
                    "type": "text",
                    "text": {"body": text},
                },
            )
        )
    return _json_result(calls[-1])


def send_photo(channel: Channel, chat_id: str, image: bytes) -> dict:
    if channel == "test":
        return {"status": "skipped"}
    if channel == "telegram":
        _token, base = _telegram_settings()
        return _json_result(
            _request(
                "POST",
                f"{base}/sendPhoto",
                "telegram sendPhoto",
                data={"chat_id": chat_id},
                files={"photo": ("photo.jpg", image, "image/jpeg")},
            )
        )
    if channel == "whatsapp":
        _token, base, headers = _whatsapp_settings()
        upload = _json_result(
            _request(
                "POST",
                f"{base}/media",
                "whatsapp media upload",
                headers=headers,
                files={"file": ("photo.jpg", image, "image/jpeg")},
                data={"messaging_product": "whatsapp", "type": "image/jpeg"},
            )
        )
        media_id = upload.get("id")
        if not media_id:
            raise ChannelError("whatsapp media upload failed: invalid provider response")
        return _json_result(
            _request(
                "POST",
                f"{base}/messages",
                "whatsapp send image",
                headers=headers,
                json={
                    "messaging_product": "whatsapp",
                    "to": chat_id,
                    "type": "image",
                    "image": {"id": media_id},
                },
            )
        )
    raise ValueError(f"unsupported channel: {channel}")


def typing(channel: Channel, chat_id: str) -> None:
    if channel == "test":
        return
    try:
        if channel == "telegram":
            _token, base = _telegram_settings()
            _request("POST", f"{base}/sendChatAction", "telegram typing", json={"chat_id": chat_id, "action": "typing"})
        elif channel == "whatsapp":
            _token, base, headers = _whatsapp_settings()
            _request(
                "POST",
                f"{base}/messages",
                "whatsapp typing",
                headers=headers,
                json={"messaging_product": "whatsapp", "to": chat_id, "type": "text", "text": {"body": ""}},
            )
        else:
            raise ValueError(f"unsupported channel: {channel}")
    except (ChannelError, ValueError):
        return


def answer_callback(channel: Channel, callback_query_id: str | None, text: str = "") -> None:
    if channel == "test":
        return
    try:
        if channel == "telegram":
            _token, base = _telegram_settings()
            _request(
                "POST",
                f"{base}/answerCallbackQuery",
                "telegram callback answer",
                json={"callback_query_id": callback_query_id, "text": text},
            )
        else:
            raise ValueError(f"unsupported channel: {channel}")
    except (ChannelError, ValueError):
        return


def _download(url: str, what: str, headers: dict | None = None) -> bytes:
    limit = get_settings().max_upload_mb * 1024 * 1024
    chunks: list[bytes] = []
    total = 0

    try:
        with httpx.stream("GET", url, headers=headers, timeout=60) as response:
            status_code = getattr(response, "status_code", 200)
            if status_code >= 400:
                raise httpx.HTTPStatusError(
                    "download error",
                    request=httpx.Request("GET", url),
                    response=response,
                )
            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > limit:
                        raise ValueError("file too large")
                except ValueError as exc:
                    if str(exc) == "file too large":
                        raise
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > limit:
                    raise ValueError("file too large")
                chunks.append(chunk)
    except httpx.HTTPStatusError as exc:
        raise ChannelError(f"{what} failed: {_describe(exc.response)}") from None
    except httpx.RequestError:
        raise ChannelError(f"{what} failed: network request failed") from None
    return b"".join(chunks)


def fetch_media(channel: Channel, file_ref: str) -> bytes:
    if channel == "telegram":
        _token, base = _telegram_settings()
        data = _json_result(
            _request(
                "GET",
                f"{base}/getFile",
                "telegram getFile",
                params={"file_id": file_ref},
            )
        )
        try:
            file_path = data["result"]["file_path"]
        except (KeyError, TypeError):
            raise ChannelError("telegram getFile failed: invalid provider response") from None
        download_url = f"https://api.telegram.org/file/bot{_token}/{file_path}"
        return _download(download_url, "telegram download")
    if channel == "whatsapp":
        _token, base, headers = _whatsapp_settings()
        data = _json_result(
            _request(
                "GET",
                f"https://graph.facebook.com/{get_settings().whatsapp_api_version}/{file_ref}",
                "whatsapp media lookup",
                headers=headers,
            )
        )
        download_url = data.get("url")
        if not download_url:
            raise ChannelError("whatsapp media lookup failed: invalid provider response")
        return _download(download_url, "whatsapp download", headers)
    raise ValueError(f"unsupported channel: {channel}")