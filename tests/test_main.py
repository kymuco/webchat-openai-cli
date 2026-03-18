from __future__ import annotations

import json
import shutil
import threading
import builtins
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Iterator

import main
import pytest

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 40


def _build_client() -> main.ChatGPTWebClient:
    client = object.__new__(main.ChatGPTWebClient)
    client.auth = main.AuthData(cookies={})
    client.timeout = 10
    client.base_headers = {"user-agent": "pytest-agent"}
    client.curl_bin = shutil.which("curl.exe") or shutil.which("curl")
    client.prefetched_requirements = None
    client.prefetched_proof_header = None
    client.prefetched_ts = 0.0
    if not client.curl_bin:
        raise RuntimeError("curl is required for tests")
    return client


@contextmanager
def _serve(handler_cls: type[BaseHTTPRequestHandler]) -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class CookieHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Set-Cookie", "session=internal; Path=/")
        self.end_headers()
        self.wfile.write(PNG_BYTES)

    def log_message(self, format: str, *args) -> None:
        return None


class RedirectHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header(
                "Location",
                f"http://127.0.0.1:{self.server.server_address[1]}/image.png",
            )
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Set-Cookie", "poisoned=1; Path=/")
        self.end_headers()
        self.wfile.write(PNG_BYTES)

    def log_message(self, format: str, *args) -> None:
        return None


def test_run_curl_persists_cookies_by_default() -> None:
    client = _build_client()

    with _serve(CookieHandler) as base_url:
        status, body, _ = client._run_curl(
            "GET",
            f"{base_url}/image.png",
            {"user-agent": client.base_headers["user-agent"]},
        )

    assert status == 200
    assert body == PNG_BYTES
    assert client.auth.cookies["session"] == "internal"


def test_media_url_download_follows_redirects_without_polluting_auth_cookies() -> None:
    client = _build_client()

    with _serve(RedirectHandler) as base_url:
        body = client._media_to_bytes(f"{base_url}/redirect")

    assert body == PNG_BYTES
    assert "poisoned" not in client.auth.cookies


def test_load_auth_data_uses_env_token_when_auth_file_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("accessToken", raising=False)
    (tmp_path / ".env").write_text("accessToken=not.a.jwt\n", encoding="utf-8")

    auth = main.load_auth_data(tmp_path / "missing_auth.json")

    assert auth.api_key == "not.a.jwt"
    assert auth.api_key_source == ".env:accessToken"
    assert auth.cookies == {}
    assert auth.headers == {}


def test_load_auth_data_without_sources_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("accessToken", raising=False)

    with pytest.raises(RuntimeError, match="No access token found"):
        main.load_auth_data(tmp_path / "missing_auth.json")


def test_cli_chat_app_uses_custom_state_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class FakeTransport:
        def __init__(self, auth_file: str | None = None, timeout: int = 90):
            self.auth = main.AuthData(api_key="token", api_key_source="test")

    custom_state = tmp_path / "custom_state.json"
    default_state = tmp_path / "webchat_state.json"
    custom_state.write_text(
        json.dumps(
            {
                "active_chat_id": "x",
                "chats": {
                    "x": {
                        "title": "Custom",
                        "temporary": False,
                        "conversation": None,
                        "model": None,
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    default_state.write_text(
        json.dumps(
            {
                "active_chat_id": "y",
                "chats": {
                    "y": {
                        "title": "Default",
                        "temporary": False,
                        "conversation": None,
                        "model": None,
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main, "ChatGPTWebClient", FakeTransport)

    app = main.CliChatApp(state_path=custom_state)
    created_chat_id = app.new_chat("Added")

    custom_payload = json.loads(custom_state.read_text(encoding="utf-8"))
    default_payload = json.loads(default_state.read_text(encoding="utf-8"))

    assert app.get_active_chat_id() == created_chat_id
    assert "x" in app._chats
    assert created_chat_id in custom_payload["chats"]
    assert default_payload["active_chat_id"] == "y"
    assert list(default_payload["chats"]) == ["y"]


def test_handle_command_writes_runtime_to_custom_state_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class FakeTransport:
        def __init__(self, auth_file: str | None = None, timeout: int = 90):
            self.auth = main.AuthData(api_key="token", api_key_source="test")

    custom_state = tmp_path / "custom_state.json"
    default_state = tmp_path / "webchat_state.json"
    custom_state.write_text(
        json.dumps(
            {
                "runtime": {
                    "model": "gpt-4o-mini",
                    "language": "en",
                    "web_search": False,
                    "reasoning_effort": None,
                    "show_metrics": True,
                },
                "active_chat_id": "x",
                "chats": {
                    "x": {
                        "title": "Custom",
                        "temporary": False,
                        "conversation": None,
                        "model": None,
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    default_state.write_text(
        json.dumps(
            {
                "runtime": {
                    "model": "default-model",
                    "language": "en",
                    "web_search": False,
                    "reasoning_effort": None,
                    "show_metrics": True,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main, "ChatGPTWebClient", FakeTransport)

    app = main.CliChatApp(state_path=custom_state)
    state = main.load_cli_state(custom_state)
    main.handle_command(app, state, "/model changed-model")

    custom_payload = json.loads(custom_state.read_text(encoding="utf-8"))
    default_payload = json.loads(default_state.read_text(encoding="utf-8"))

    assert custom_payload["runtime"]["model"] == "changed-model"
    assert default_payload["runtime"]["model"] == "default-model"


def test_load_cli_state_warns_and_falls_back_for_corrupted_state(
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    state_path = tmp_path / "webchat_state.json"
    state_path.write_text('{"runtime":', encoding="utf-8")

    state = main.load_cli_state(state_path)

    captured = capsys.readouterr()
    assert state == main.DEFAULT_RUNTIME_STATE
    assert f"Warning: failed to load JSON from {state_path}" in captured.out


def test_main_returns_friendly_startup_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FailingApp:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(main, "CliChatApp", FailingApp)
    monkeypatch.setattr(main, "load_cli_state", lambda *args, **kwargs: main.DEFAULT_RUNTIME_STATE.copy())

    rc = main.main()

    captured = capsys.readouterr()
    assert rc == 1
    assert "Startup error: RuntimeError: boom" in captured.out


def test_main_localizes_warmup_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeTransport:
        def __init__(self):
            self.auth = main.AuthData(api_key="token", api_key_source="test")

        def warmup(self) -> bool:
            return True

    class FakeApp:
        def __init__(self, *args, **kwargs):
            self.transport = FakeTransport()
            self._chat = {
                "title": "Новый чат",
                "temporary": False,
                "conversation": None,
            }

        def get_active_chat_id(self) -> str | None:
            return "chat1"

        def get_active_chat(self) -> dict[str, object]:
            return self._chat

        def _save_chats(self) -> None:
            return None

    state = main.DEFAULT_RUNTIME_STATE.copy()
    state["language"] = "ru"
    monkeypatch.setattr(main, "CliChatApp", FakeApp)
    monkeypatch.setattr(main, "load_cli_state", lambda *args, **kwargs: state.copy())
    monkeypatch.setattr(builtins, "input", lambda *args, **kwargs: (_ for _ in ()).throw(EOFError()))

    rc = main.main()

    captured = capsys.readouterr()
    assert rc == 0
    assert "Прогрев... ok" in captured.out
