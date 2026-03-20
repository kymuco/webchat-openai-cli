import argparse
import asyncio
import base64
import json
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_AUTH_PATH = Path("auth_data.json")
DEFAULT_AUTH_TIMEOUT = 120.0
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
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "api_key": self.api_key,
            "cookies": self.cookies,
            "headers": self.headers,
            "expires": self.expires,
            "proof_token": self.proof_token,
            "turnstile_token": self.turnstile_token,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                delete=False,
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
            ) as file:
                json.dump(data, file, indent=2, ensure_ascii=False)
                temp_path = Path(file.name)
            temp_path.replace(path)
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
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


def _import_zendriver():
    try:
        import zendriver as nodriver
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "Dependency 'zendriver' is not installed. "
            "Install auth fetcher requirements with "
            "`python -m pip install -r requirements.txt` or "
            "`python -m pip install -U zendriver platformdirs`."
        ) from error
    return nodriver


def _reset_auth_state(auth_cls, request_config_cls):
    auth_cls.request_config = request_config_cls()
    auth_cls._api_key = None
    auth_cls._headers = None
    auth_cls._cookies = None
    auth_cls._expires = None


def _normalize_probe_prompt(value: str | None) -> str:
    normalized = str(value or "").strip()
    return normalized or DEFAULT_AUTH_PROMPT


def _print_cleanup_warning(action: str, error: Exception) -> None:
    print(f"Warning: failed to {action}: {type(error).__name__}: {error}")


def _auth_capture_is_complete(auth_cls) -> bool:
    return bool(auth_cls._api_key and auth_cls.request_config.proof_token is not None)


async def _refresh_access_token_from_page(page, auth_cls) -> None:
    if auth_cls._api_key is not None:
        return
    remix_context = _unwrap_page_value(
        await page.evaluate(
            "JSON.stringify(window.__remixContext)",
            return_by_value=True,
        )
    )
    auth_cls._api_key = _extract_access_token(remix_context) or auth_cls._api_key


async def _capture_page_state(page, auth_cls, get_cookies) -> None:
    try:
        auth_cls.request_config.data_build = _unwrap_page_value(
            await page.evaluate(
                "document.documentElement.getAttribute('data-build')",
                return_by_value=True,
            )
        )
    except Exception as error:
        _print_cleanup_warning("capture page build metadata", error)
    try:
        auth_cls.request_config.cookies = await page.send(get_cookies([auth_cls.url]))
    except Exception as error:
        _print_cleanup_warning("capture browser cookies", error)
    try:
        await page.close()
    except Exception as error:
        _print_cleanup_warning("close the browser page cleanly", error)


async def _submit_probe_prompt(page, auth_cls, prompt: str = DEFAULT_AUTH_PROMPT):
    normalized_prompt = _normalize_probe_prompt(prompt)
    try:
        if getattr(auth_cls, "needs_auth", False):
            await asyncio.wait_for(
                page.select('[data-testid="accounts-profile-button"]', 300),
                timeout=30,
            )
    except Exception:
        pass

    textarea = await asyncio.wait_for(page.select("#prompt-textarea", 300), timeout=60)
    await textarea.send_keys(normalized_prompt)
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


async def _wait_for_auth_capture(
    page,
    auth_cls,
    *,
    auth_timeout: float,
    proof_grace: float,
    status_message: str | None = None,
    require_request_activity: bool = False,
    has_new_request_activity=None,
):
    capture_started_at = time.perf_counter()
    access_token_at = None
    last_notice_at = 0.0
    request_activity_seen = not require_request_activity

    while True:
        elapsed = time.perf_counter() - capture_started_at
        if elapsed >= auth_timeout:
            break

        if status_message and elapsed - last_notice_at >= 15.0:
            print(status_message)
            last_notice_at = elapsed

        if not request_activity_seen and has_new_request_activity is not None:
            request_activity_seen = bool(has_new_request_activity())

        await _refresh_access_token_from_page(page, auth_cls)

        if auth_cls._api_key and access_token_at is None and request_activity_seen:
            access_token_at = time.perf_counter()

        if _auth_capture_is_complete(auth_cls) and request_activity_seen:
            break

        if access_token_at is not None:
            waited_for_proof = time.perf_counter() - access_token_at
            if waited_for_proof >= proof_grace:
                break

        await asyncio.sleep(DEFAULT_POLL_INTERVAL)


async def _collect_auth_tokens(
    auth_cls,
    *,
    proxy: str | None = None,
    auth_timeout: float = DEFAULT_AUTH_TIMEOUT,
    proof_grace: float = DEFAULT_PROOF_GRACE,
    mode: str = "auto",
    ready_timeout: float | None = None,
    probe_prompt: str = DEFAULT_AUTH_PROMPT,
):
    try:
        from g4f.Provider.needs_auth.OpenaiChat import get_cookies
        from g4f.Provider.openai.har_file import (
            RequestConfig,
            backend_anon_url,
            backend_url,
            conversation_url,
            prepare_url,
            start_url,
        )
        from g4f.requests import get_nodriver_session
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "Dependency 'g4f' is not installed in this Python environment. "
            "Activate the project venv or install requirements."
        ) from error
    except ImportError as error:
        raise RuntimeError(
            "Installed 'g4f' does not expose the browser auth helpers "
            "required by auth_fetcher.py. Reinstall project dependencies "
            "or update the script for your g4f version."
        ) from error

    nodriver = _import_zendriver()

    _reset_auth_state(auth_cls, RequestConfig)
    started_at = time.perf_counter()
    user_agent = None
    normalized_probe_prompt = _normalize_probe_prompt(probe_prompt)
    conversation_request_count = 0

    async with get_nodriver_session(proxy=proxy) as browser:
        page = await browser.get(auth_cls.url)

        def on_request(event, page=None):
            nonlocal conversation_request_count
            request = getattr(event, "request", None)
            if request is None:
                return

            headers = {
                str(key).lower(): value
                for key, value in getattr(request, "headers", {}).items()
            }
            request_url = getattr(request, "url", "")

            if request_url == start_url or request_url.startswith(conversation_url):
                conversation_request_count += 1
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
                    "No probe message will be sent automatically."
                )
                await _wait_for_chat_input(page, ready_timeout=ready_timeout)
                baseline_request_count = conversation_request_count
                print(
                    "Chat input detected. Send any message in the browser to trigger auth capture."
                )
                await _wait_for_auth_capture(
                    page,
                    auth_cls,
                    auth_timeout=auth_timeout,
                    proof_grace=proof_grace,
                    status_message=(
                        "Still waiting for a ChatGPT request from the browser. "
                        "Send any message in the chat to continue auth capture."
                    ),
                    require_request_activity=True,
                    has_new_request_activity=(
                        lambda: conversation_request_count > baseline_request_count
                    ),
                )
            else:
                await _submit_probe_prompt(page, auth_cls, prompt=normalized_probe_prompt)
                await _wait_for_auth_capture(
                    page,
                    auth_cls,
                    auth_timeout=auth_timeout,
                    proof_grace=proof_grace,
                )
        finally:
            await _capture_page_state(page, auth_cls, get_cookies)

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
    probe_prompt: str = DEFAULT_AUTH_PROMPT,
):
    """Run auth via NoDriver and save collected tokens into JSON."""
    normalized_probe_prompt = _normalize_probe_prompt(probe_prompt)
    print(f"Start authorization via NoDriver (mode={mode})...")
    if mode == "wait":
        print(
            "Wait mode keeps the browser open for login or registration. "
            "After the chat becomes ready, send any message manually to trigger capture."
        )
    else:
        print(
            "Probe prompt will be sent once to trigger auth capture: "
            f"{normalized_probe_prompt!r}"
        )

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
        probe_prompt=normalized_probe_prompt,
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
        help="auto = capture quickly from an already logged-in session; wait = keep browser open until chat is ready, then capture after you send a message manually.",
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
        help="Seconds to wait for auth capture after the trigger action starts.",
    )
    parser.add_argument(
        "--ready-timeout",
        type=float,
        default=DEFAULT_READY_TIMEOUT,
        help="Only for wait mode: seconds to wait for login/chat readiness. 0 means wait indefinitely.",
    )
    parser.add_argument(
        "--probe-prompt",
        default=DEFAULT_AUTH_PROMPT,
        help="Prompt text to send once in auto mode to trigger auth capture.",
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
                probe_prompt=args.probe_prompt,
            )
        )
    except KeyboardInterrupt:
        print("Operation interrupted by user.")
