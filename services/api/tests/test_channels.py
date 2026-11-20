
"""Tests for the Telegram/WhatsApp adapter and its HTTP endpoints. No real network calls."""

from contextlib import contextmanager

import httpx
import pytest

from app.config import get_settings
from app.core import channels
from app.core.channels import ChannelError, send_photo, send_text


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


# One reply that satisfies every code path (Telegram, WhatsApp message, WhatsApp media upload).
OK_REPLY = {"ok": True, "result": {"message_id": 7}, "messages": [{"id": "wamid.1"}], "id": "media1"}


@pytest.fixture
def configured(monkeypatch):
    """Pretend both channels are set up, with a 1 MB download limit."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "SECRET-TOKEN")
    monkeypatch.setenv("WHATSAPP_TOKEN", "wa-token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123")
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def sent(configured, monkeypatch):
    """Record every outbound call as (method, url, what, kwargs) instead of sending it."""
    calls = []

    def fake_request(method, url, what, **kwargs):
        calls.append((method, url, what, kwargs))
        return FakeResponse(OK_REPLY)

    monkeypatch.setattr(channels, "_request", fake_request)
    return calls


# --- the test channel never sends ---


def test_test_channel_never_sends(sent):
    assert send_text("test", "x", "hello", [{"text": "Yes", "data": "act:1:yes"}]) == {"status": "skipped"}
    assert send_photo("test", "x", b"png") == {"status": "skipped"}
    assert sent == []


# --- Telegram ---


def test_telegram_plain_text(sent):
    send_text("telegram", "42", "hello")
    _method, url, _what, kwargs = sent[0]
    assert url.endswith("/sendMessage")
    assert kwargs["json"]["chat_id"] == "42"
    assert kwargs["json"]["text"] == "hello"
    assert "reply_markup" not in kwargs["json"]


def test_telegram_buttons_are_one_row(sent):
    buttons = [{"text": "Yes", "data": "act:1:yes"}, {"text": "No", "data": "act:1:no"}]
    send_text("telegram", "42", "ok?", buttons)
    keyboard = sent[0][3]["json"]["reply_markup"]["inline_keyboard"]
    assert keyboard == [[{"text": "Yes", "callback_data": "act:1:yes"}, {"text": "No", "callback_data": "act:1:no"}]]


def test_telegram_button_data_limit_is_in_bytes(sent):
    with pytest.raises(ValueError):
        send_text("telegram", "42", "x", [{"text": "Y", "data": "é" * 33}])  # 33 characters, 66 bytes
    assert sent == []


# --- WhatsApp ---


def test_whatsapp_short_message_is_one_call_with_trimmed_buttons(sent):
    buttons = [{"text": "✅ A very long button title", "data": f"id{i}"} for i in range(4)]
    send_text("whatsapp", "9", "short", buttons)
    assert len(sent) == 1
    shown = sent[0][3]["json"]["interactive"]["action"]["buttons"]
    assert len(shown) == 3  # WhatsApp allows at most 3
    assert all(len(b["reply"]["title"]) <= 20 for b in shown)


def test_whatsapp_long_message_is_sent_in_full_before_the_buttons(sent):
    long_text = "x" * 1500
    send_text("whatsapp", "9", long_text, [{"text": "Confirm", "data": "id1"}])
    assert len(sent) == 2
    assert sent[0][3]["json"]["type"] == "text"
    assert sent[0][3]["json"]["text"]["body"] == long_text  # nothing cut off
    assert sent[1][3]["json"]["interactive"]["body"]["text"] == "Tap an option below:"


# --- misc behaviour ---


def test_unsupported_channel_is_a_value_error(sent):
    with pytest.raises(ValueError):
        send_text("sms", "1", "x")
    with pytest.raises(ValueError):
        channels.fetch_media("sms", "file")


def test_typing_and_callback_ack_ignore_failures(configured, monkeypatch):
    def boom(*args, **kwargs):
        raise ChannelError("down")

    monkeypatch.setattr(channels, "_request", boom)
    channels.typing("telegram", "42")  # must not raise
    channels.answer_callback("telegram", "cb1", "ok")  # must not raise


def test_telegram_not_configured_is_a_clear_error(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(ChannelError, match="not configured"):
            send_text("telegram", "42", "hi")
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


# --- errors never leak the bot token ---


def test_network_error_message_has_no_url_or_token(configured, monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("could not reach https://api.telegram.org/botSECRET-TOKEN/sendMessage")

    monkeypatch.setattr(channels.httpx, "request", fail)
    with pytest.raises(ChannelError) as exc:
        channels._request("POST", "https://api.telegram.org/botSECRET-TOKEN/sendMessage", "telegram sendMessage")
    assert "SECRET-TOKEN" not in str(exc.value)
    assert exc.value.__cause__ is None  # the original error (which contains the URL) is dropped


def test_http_error_message_uses_the_api_description(configured, monkeypatch):
    reply = httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})
    monkeypatch.setattr(channels.httpx, "request", lambda *a, **k: reply)
    with pytest.raises(ChannelError) as exc:
        channels._request("POST", "https://api.telegram.org/botSECRET-TOKEN/sendMessage", "telegram sendMessage")
    assert str(exc.value) == "telegram sendMessage failed: HTTP 400: Bad Request: chat not found"


def test_describe_handles_graph_and_odd_bodies():
    graph_error = httpx.Response(401, json={"error": {"message": "Invalid token"}})
    assert channels._describe(graph_error) == "HTTP 401: Invalid token"
    assert channels._describe(httpx.Response(500, json=["weird"])) == "HTTP 500"
    assert channels._describe(httpx.Response(502, text="<html>")) == "HTTP 502"


# --- downloads ---


class FakeStream:
    def __init__(self, chunks, headers=None):
        self._chunks = chunks
        self.headers = headers or {}
        self.is_error = False
        self.status_code = 200

    def iter_bytes(self):
        yield from self._chunks


def _patch_stream(monkeypatch, stream):
    @contextmanager
    def fake(method, url, **kwargs):
        yield stream

    monkeypatch.setattr(channels.httpx, "stream", fake)


def test_download_returns_the_bytes(configured, monkeypatch):
    _patch_stream(monkeypatch, FakeStream([b"abc", b"def"]))
    assert channels._download("https://example.test/f", "download") == b"abcdef"


def test_download_stops_when_the_file_grows_past_the_limit(configured, monkeypatch):
    _patch_stream(monkeypatch, FakeStream([b"x" * 600_000, b"x" * 600_000]))  # 1.2 MB, limit is 1 MB
    with pytest.raises(ValueError, match="too large"):
        channels._download("https://example.test/f", "download")


def test_download_rejects_a_declared_size_over_the_limit(configured, monkeypatch):
    _patch_stream(monkeypatch, FakeStream([b"x"], headers={"content-length": str(5 * 1024 * 1024)}))
    with pytest.raises(ValueError, match="too large"):
        channels._download("https://example.test/f", "download")


def test_fetch_media_telegram_looks_up_the_file_then_downloads_it(configured, monkeypatch):
    monkeypatch.setattr(
        channels, "_request", lambda *a, **k: FakeResponse({"result": {"file_path": "voice/file_1.oga"}})
    )
    downloaded = []
    monkeypatch.setattr(channels, "_download", lambda url, what, headers=None: downloaded.append(url) or b"audio")
    assert channels.fetch_media("telegram", "FILE_ID") == b"audio"
    assert downloaded[0].endswith("/voice/file_1.oga")


# --- HTTP endpoints ---


def test_send_needs_the_api_key(client):
    r = client.post("/channels/send", json={"channel": "test", "chat_id": "1", "text": "hi"})
    assert r.status_code == 401


def test_send_on_the_test_channel(client, auth):
    r = client.post("/channels/send", json={"channel": "test", "chat_id": "1", "text": "hi"}, headers=auth)
    assert r.status_code == 200
    assert r.json() == {"status": "sent", "message_id": None, "raw": {"status": "skipped"}}


def test_send_returns_the_telegram_message_id(client, auth, sent):
    r = client.post("/channels/send", json={"channel": "telegram", "chat_id": "42", "text": "hi"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["message_id"] == "7"


@pytest.mark.parametrize(
    "body",
    [
        {"channel": "sms", "chat_id": "1", "text": "hi"},  # unknown channel
        {"channel": "test", "chat_id": "1", "text": ""},  # empty text
        {"channel": "test", "chat_id": "1", "text": "x" * 4001},  # too long
    ],
)
def test_send_rejects_invalid_requests(client, auth, body):
    assert client.post("/channels/send", json=body, headers=auth).status_code == 422


def test_send_maps_channel_failure_to_502(client, auth, configured, monkeypatch):
    def fail(*args, **kwargs):
        raise ChannelError("telegram sendMessage failed: HTTP 400: chat not found")

    monkeypatch.setattr(channels, "_request", fail)
    r = client.post("/channels/send", json={"channel": "telegram", "chat_id": "42", "text": "hi"}, headers=auth)
    assert r.status_code == 502
    assert "chat not found" in r.json()["detail"]
    assert "SECRET-TOKEN" not in r.text


def test_send_maps_oversized_button_to_400(client, auth, sent):
    body = {
        "channel": "telegram",
        "chat_id": "42",
        "text": "hi",
        "buttons": [{"text": "Y", "data": "é" * 33}],  # passes the 64-character check, fails the 64-byte one
    }
    assert client.post("/channels/send", json=body, headers=auth).status_code == 400


def test_typing_endpoint(client, auth):
    r = client.post("/channels/typing", json={"channel": "test", "chat_id": "1"}, headers=auth)
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
