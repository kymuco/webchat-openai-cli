from __future__ import annotations

import asyncio
import json
import sys
import types
from datetime import datetime, timezone

import auth_fetcher


class FakeDateTime:
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return datetime(2026, 1, 1, 15, 0, 0)
        return datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc)


def test_auth_result_timestamp_is_saved_in_utc(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(auth_fetcher, "datetime", FakeDateTime)

    target = tmp_path / "auth_data.json"
    auth_fetcher.AuthResult("token", {}, {}, 0, None, None).to_json(target)

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["timestamp"] == "2026-01-01T09:00:00Z"


def test_submit_probe_prompt_uses_custom_prompt_and_fallback_enter(
    monkeypatch,
) -> None:
    class FakeTextarea:
        def __init__(self) -> None:
            self.values: list[str] = []

        async def send_keys(self, value: str) -> None:
            self.values.append(value)

    class FakePage:
        def __init__(self) -> None:
            self.textarea = FakeTextarea()

        async def select(self, selector: str, timeout: int | None = None):
            if selector == "#prompt-textarea":
                return self.textarea
            if selector == '[data-testid="send-button"]':
                return None
            return object()

    class FakeAuth:
        needs_auth = False

    async def _fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(auth_fetcher.asyncio, "sleep", _fake_sleep)
    page = FakePage()

    asyncio.run(auth_fetcher._submit_probe_prompt(page, FakeAuth, prompt="Ping"))

    assert page.textarea.values == ["Ping", "\n"]


def test_capture_page_state_warns_but_keeps_partial_data(
    capsys,
) -> None:
    class RequestConfig:
        def __init__(self) -> None:
            self.data_build = None
            self.cookies = None

    class FakeAuth:
        url = "https://chatgpt.com/"
        request_config = RequestConfig()

    class FakePage:
        async def evaluate(self, script: str, return_by_value: bool = False):
            raise RuntimeError("page is gone")

        async def send(self, payload):
            return {"session": "abc"}

        async def close(self) -> None:
            raise RuntimeError("close failed")

    def fake_get_cookies(urls):
        return {"urls": urls}

    asyncio.run(auth_fetcher._capture_page_state(FakePage(), FakeAuth, fake_get_cookies))

    captured = capsys.readouterr()
    assert FakeAuth.request_config.data_build is None
    assert FakeAuth.request_config.cookies == {"session": "abc"}
    assert "Warning: failed to capture page build metadata" in captured.out
    assert "Warning: failed to close the browser page cleanly" in captured.out


def test_parse_args_accepts_probe_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "auth_fetcher.py",
            "--mode",
            "wait",
            "--probe-prompt",
            "Ping",
        ],
    )

    args = auth_fetcher._parse_args()

    assert args.mode == "wait"
    assert args.probe_prompt == "Ping"
    assert args.timeout == 120.0


def test_collect_auth_tokens_wait_mode_skips_automatic_probe(monkeypatch) -> None:
    class FakeRequestConfig:
        def __init__(self) -> None:
            self.data_build = None
            self.cookies = {}
            self.headers = None
            self.proof_token = None
            self.turnstile_token = None

    class FakeAuth:
        url = "https://chatgpt.com/"
        request_config = FakeRequestConfig()
        _api_key = None
        _headers = None
        _cookies = None
        _expires = None
        created_args = None
        api_key_set = None

        @classmethod
        def _create_request_args(cls, cookies, headers, user_agent=None):
            cls.created_args = (cookies, headers, user_agent)

        @classmethod
        def _set_api_key(cls, value):
            cls.api_key_set = value

    class FakePage:
        def add_handler(self, *_args, **_kwargs):
            return None

        async def reload(self) -> None:
            return None

        async def evaluate(self, script: str, return_by_value: bool = False):
            if script == "window.navigator.userAgent":
                return "pytest-agent"
            if script == "JSON.stringify(window.__remixContext)":
                return '{"accessToken":"captured-token"}'
            return None

        async def send(self, payload):
            return {"cookies": "ok"}

        async def close(self) -> None:
            return None

    class FakeBrowser:
        def __init__(self) -> None:
            self.page = FakePage()

        async def get(self, _url: str):
            return self.page

    class FakeSession:
        async def __aenter__(self):
            return FakeBrowser()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    fake_openai_chat = types.ModuleType("g4f.Provider.needs_auth.OpenaiChat")
    fake_openai_chat.get_cookies = lambda urls: {"urls": urls}

    fake_har_file = types.ModuleType("g4f.Provider.openai.har_file")
    fake_har_file.RequestConfig = FakeRequestConfig
    fake_har_file.backend_anon_url = "https://chatgpt.com/backend-api/anon"
    fake_har_file.backend_url = "https://chatgpt.com/backend-api"
    fake_har_file.conversation_url = "https://chatgpt.com/backend-api/f/conversation"
    fake_har_file.prepare_url = "https://chatgpt.com/backend-api/sentinel/chat-requirements"
    fake_har_file.start_url = "https://chatgpt.com/backend-api/conversation/start"

    fake_requests = types.ModuleType("g4f.requests")
    fake_requests.get_nodriver_session = lambda proxy=None: FakeSession()

    monkeypatch.setitem(sys.modules, "g4f.Provider.needs_auth.OpenaiChat", fake_openai_chat)
    monkeypatch.setitem(sys.modules, "g4f.Provider.openai.har_file", fake_har_file)
    monkeypatch.setitem(sys.modules, "g4f.requests", fake_requests)
    monkeypatch.setattr(
        auth_fetcher,
        "_import_zendriver",
        lambda: types.SimpleNamespace(
            cdp=types.SimpleNamespace(
                network=types.SimpleNamespace(RequestWillBeSent=object())
            )
        ),
    )

    waited_for_chat = {"called": False}
    waited_for_capture = {"called": False}

    async def fake_wait_for_chat_input(page, *, ready_timeout=None):
        waited_for_chat["called"] = True
        return object()

    async def fake_wait_for_auth_capture(page, auth_cls, **kwargs):
        waited_for_capture["called"] = True
        assert kwargs["require_request_activity"] is True
        assert "Send any message" in kwargs["status_message"]
        auth_cls._api_key = "captured-token"
        auth_cls.request_config.proof_token = {"ok": True}

    async def fail_submit_probe(*_args, **_kwargs):
        raise AssertionError("wait mode must not send the probe automatically")

    monkeypatch.setattr(auth_fetcher, "_wait_for_chat_input", fake_wait_for_chat_input)
    monkeypatch.setattr(auth_fetcher, "_wait_for_auth_capture", fake_wait_for_auth_capture)
    monkeypatch.setattr(auth_fetcher, "_submit_probe_prompt", fail_submit_probe)

    asyncio.run(auth_fetcher._collect_auth_tokens(FakeAuth, mode="wait", auth_timeout=1.0))

    assert waited_for_chat["called"] is True
    assert waited_for_capture["called"] is True
    assert FakeAuth.api_key_set == "captured-token"
