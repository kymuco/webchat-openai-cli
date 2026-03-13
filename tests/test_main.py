from __future__ import annotations

import shutil
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Iterator

import main

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
