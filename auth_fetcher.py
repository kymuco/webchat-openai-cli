import argparse
import asyncio
import base64
import json
import re
import time
from datetime import datetime
from pathlib import Path

DEFAULT_AUTH_PATH = Path("auth_data.json")
DEFAULT_AUTH_TIMEOUT = 45.0
DEFAULT_PROOF_GRACE = 6.0
DEFAULT_POLL_INTERVAL = 0.25
DEFAULT_AUTH_PROMPT = "Hello"
DEFAULT_READY_TIMEOUT = 0.0


class AuthResult:
    def __init__(self, api_key, cookies, headers, expires, proof_token, turnstile_token):
        self.api_key = api_key
        self.cookies = cookies
        self.headers = headers
        self.expires = expires
        self.proof_token = proof_token
        self.turnstile_token = turnstile_token

    @classmethod
    def from_json(cls, path: str | Path):
        """Load AuthResult from a JSON file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"File {path} not found")

        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        return cls(
            api_key=data.get("api_key"),
            cookies=data.get("cookies"),
            headers=data.get("headers"),
            expires=data.get("expires"),
            proof_token=data.get("proof_token"),
            turnstile_token=data.get("turnstile_token"),
        )

    def to_json(self, path: str | Path):
        """Save AuthResult into a JSON file."""
        path = Path(path)
        data = {
            "timestamp": datetime.now().isoformat() + "Z",
            "api_key": self.api_key,
            "cookies": self.cookies,
            "headers": self.headers,
            "expires": self.expires,
            "proof_token": self.proof_token,
            "turnstile_token": self.turnstile_token,
        }
        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
        return path


def _unwrap_page_value(value):
    return getattr(value, "value", value)


def _extract_access_token(remix_context_json: str | None) -> str | None:
    if not remix_context_json:
        return None
    match = re.search(r'"accessToken":"(.+?)"', remix_context_json)
    return match.group(1) if match else None


def _decode_proof_token(header_value: str):
    encoded_payload = header_value.split("gAAAAAB", 1)[-1].split("~", 1)[0].encode()
    padding = (-len(encoded_payload)) % 4
    if padding:
        encoded_payload += b"=" * padding
    try:
        return json.loads(base64.b64decode(encoded_payload).decode())
    except Exception:
        return None


def _reset_auth_state(auth_cls, request_config_cls):
    auth_cls.request_config = request_config_cls()
    auth_cls._api_key = None
    auth_cls._headers = None
    auth_cls._cookies = None
    auth_cls._expires = None


async def _submit_probe_prompt(page, auth_cls):
    try:
        if getattr(auth_cls, "needs_auth", False):
            await asyncio.wait_for(
                page.select('[data-testid="accounts-profile-button"]', 300),
                timeout=30,
            )
    except Exception:
        pass

    textarea = await asyncio.wait_for(page.select("#prompt-textarea", 300), timeout=60)
    await textarea.send_keys(DEFAULT_AUTH_PROMPT)
    await asyncio.sleep(0.3)

    try:
        button = await asyncio.wait_for(
            page.select('[data-testid="send-button"]'),
            timeout=3,
        )
    except Exception:
        button = None

    if button:
        await button.click()
    else:
        await textarea.send_keys("\n")


async def _wait_for_chat_input(
    page,
    *,
    ready_timeout: float | None = None,
):
    started_at = time.perf_counter()
    last_notice_at = 0.0
    while True:
        try:
            textarea = await asyncio.wait_for(page.select("#prompt-textarea", 300), timeout=5)
            if textarea is not None:
                return textarea
        except Exception:
            pass

        elapsed = time.perf_counter() - started_at
        if elapsed - last_notice_at >= 10.0:
            print("Waiting for login/registration to finish and chat input to appear...")
            last_notice_at = elapsed

        if ready_timeout is not None and ready_timeout > 0 and elapsed >= ready_timeout:
            raise RuntimeError(
                f"Timed out after {elapsed:.1f}s while waiting for the chat input."
            )

        await asyncio.sleep(1.0)


async def _collect_auth_tokens(
    auth_cls,
    *,
    proxy: str | None = None,
    auth_timeout: float = DEFAULT_AUTH_TIMEOUT,
    proof_grace: float = DEFAULT_PROOF_GRACE,
    mode: str = "auto",
    ready_timeout: float | None = None,
):
    from g4f.Provider.needs_auth.OpenaiChat import get_cookies, nodriver
    from g4f.Provider.openai.har_file import (
        RequestConfig,
        backend_anon_url,
        backend_url,
        conversation_url,
        prepare_url,
        start_url,
    )
    from g4f.requests import get_nodriver_session

    _reset_auth_state(auth_cls, RequestConfig)
    started_at = time.perf_counter()
    access_token_at = None
    user_agent = None

    async with get_nodriver_session(proxy=proxy) as browser:
        page = await browser.get(auth_cls.url)

        def on_request(event, page=None):
            request = getattr(event, "request", None)
            if request is None:
                return

            headers = {
                str(key).lower(): value
                for key, value in getattr(request, "headers", {}).items()
            }
            request_url = getattr(request, "url", "")

            if request_url == start_url or request_url.startswith(conversation_url):
                if auth_cls.request_config.headers is None:
                    auth_cls.request_config.headers = {}
                auth_cls.request_config.headers.update(headers)
                return

            if request_url not in (backend_url, backend_anon_url, prepare_url):
                return

            proof_header = headers.get("openai-sentinel-proof-token")
            if proof_header and auth_cls.request_config.proof_token is None:
                decoded_proof = _decode_proof_token(proof_header)
                if decoded_proof is not None:
                    auth_cls.request_config.proof_token = decoded_proof

            turnstile_token = headers.get("openai-sentinel-turnstile-token")
            if turnstile_token and auth_cls.request_config.turnstile_token is None:
                auth_cls.request_config.turnstile_token = turnstile_token

            authorization = headers.get("authorization")
            if authorization and auth_cls._api_key is None:
                auth_cls._api_key = authorization.split()[-1]

        page.add_handler(nodriver.cdp.network.RequestWillBeSent, on_request)
        await page.reload()

        try:
            user_agent = _unwrap_page_value(
                await page.evaluate("window.navigator.userAgent", return_by_value=True)
            )
            if mode == "wait":
                print(
                    "Wait mode enabled. Complete login/registration in the opened browser. "
                    "Capture will continue automatically once the chat input is ready."
                )
                await _wait_for_chat_input(page, ready_timeout=ready_timeout)
            await _submit_probe_prompt(page, auth_cls)
            capture_started_at = time.perf_counter()

            while True:
                elapsed = time.perf_counter() - capture_started_at
                if elapsed >= auth_timeout:
                    break

                if auth_cls._api_key is None:
                    remix_context = _unwrap_page_value(
                        await page.evaluate(
                            "JSON.stringify(window.__remixContext)",
                            return_by_value=True,
                        )
                    )
                    auth_cls._api_key = _extract_access_token(remix_context) or auth_cls._api_key

                if auth_cls._api_key and access_token_at is None:
                    access_token_at = time.perf_counter()

                if auth_cls._api_key and auth_cls.request_config.proof_token is not None:
                    break

                if access_token_at is not None:
                    waited_for_proof = time.perf_counter() - access_token_at
                    if waited_for_proof >= proof_grace:
                        break

                await asyncio.sleep(DEFAULT_POLL_INTERVAL)
        finally:
            auth_cls.request_config.data_build = _unwrap_page_value(
                await page.evaluate(
                    "document.documentElement.getAttribute('data-build')",
                    return_by_value=True,
                )
            )
            auth_cls.request_config.cookies = await page.send(get_cookies([auth_cls.url]))
            await page.close()

    auth_cls._create_request_args(
        auth_cls.request_config.cookies,
        auth_cls.request_config.headers,
        user_agent=user_agent,
    )
    if auth_cls._api_key:
        auth_cls._set_api_key(auth_cls._api_key)

    total_wait = time.perf_counter() - started_at
    if not auth_cls._api_key:
        raise RuntimeError(
            f"Authorization timed out after {total_wait:.1f}s: access token was not captured."
        )

    if auth_cls.request_config.proof_token is None:
        print(
            "Warning: proof_token was not captured. Saving partial auth_data.json "
            "with accessToken/cookies/headers."
        )


async def run_auth_and_save(
    proxy: str | None = None,
    output_file: str | Path = DEFAULT_AUTH_PATH,
    auth_timeout: float = DEFAULT_AUTH_TIMEOUT,
    mode: str = "auto",
    ready_timeout: float | None = DEFAULT_READY_TIMEOUT,
):
    """Run auth via NoDriver and save collected tokens into JSON."""
    print(f"Start authorization via NoDriver (mode={mode})...")

    try:
        from g4f.Provider.needs_auth import OpenaiChat
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "Dependency 'g4f' is not installed in this Python environment. "
            "Activate project venv or install requirements."
        ) from error

    await _collect_auth_tokens(
        OpenaiChat,
        proxy=proxy,
        auth_timeout=auth_timeout,
        mode=mode,
        ready_timeout=ready_timeout if (ready_timeout and ready_timeout > 0) else None,
    )

    auth_result = AuthResult(
        api_key=getattr(OpenaiChat, "_api_key", None),
        cookies=getattr(OpenaiChat.request_config, "cookies", None),
        headers=getattr(OpenaiChat.request_config, "headers", None),
        expires=getattr(OpenaiChat, "_expires", None),
        proof_token=getattr(OpenaiChat.request_config, "proof_token", None),
        turnstile_token=getattr(OpenaiChat.request_config, "turnstile_token", None),
    )

    path = auth_result.to_json(output_file)
    print(f"Authorization complete. Data saved to {path}")
    return auth_result


async def load_auth_or_refresh(
    path: str | Path = DEFAULT_AUTH_PATH,
    proxy: str | None = None,
):
    target_path = Path(path)
    try:
        return AuthResult.from_json(target_path)
    except FileNotFoundError:
        print(f"File {target_path} not found. Running authorization...")
        return await run_auth_and_save(proxy=proxy, output_file=target_path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch ChatGPT web auth data via NoDriver.")
    parser.add_argument(
        "--mode",
        choices=("auto", "wait"),
        default="auto",
        help="auto = capture quickly from an already logged-in session; wait = keep browser open until chat is ready.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_AUTH_PATH),
        help="Path to auth_data.json output file.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_AUTH_TIMEOUT,
        help="Seconds to wait for access token capture after the probe message is sent.",
    )
    parser.add_argument(
        "--ready-timeout",
        type=float,
        default=DEFAULT_READY_TIMEOUT,
        help="Only for wait mode: seconds to wait for login/chat readiness. 0 means wait indefinitely.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        asyncio.run(
            run_auth_and_save(
                output_file=args.output,
                auth_timeout=args.timeout,
                mode=args.mode,
                ready_timeout=args.ready_timeout,
            )
        )
    except KeyboardInterrupt:
        print("Operation interrupted by user.")
