from __future__ import annotations

import asyncio
import json
import sys
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
