#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

CHAT_URL = "https://chatgpt.com/"
CHAT_REQUIREMENTS_URL = "https://chatgpt.com/backend-api/sentinel/chat-requirements"
CHAT_BACKEND_URL = "https://chatgpt.com/backend-api/f/conversation"
CHAT_FILES_URL = "https://chatgpt.com/backend-api/files"
DEFAULT_AUTH_FILE = Path("auth_data.json")
APP_STATE_FILE = Path("webchat_state.json")
LEGACY_CLI_STATE_FILE = Path("cli_state.json")
LEGACY_CHATS_STATE_FILE = Path("g4f_chats.json")
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT_SECONDS = 90
PREFETCH_TTL_SECONDS = 20.0
SUPPORTED_MODELS = [
    "gpt-5-2",
    "gpt-5-2-instant",
    "gpt-5-2-thinking",
    "gpt-5-1",
    "gpt-5-1-instant",
    "gpt-5-1-thinking",
    "gpt-5",
    "gpt-5-instant",
    "gpt-5-thinking",
    "gpt-4",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.5",
    "gpt-4o",
    "gpt-4o-mini",
    "o1",
    "o1-mini",
    "o3-mini",
    "o3-mini-high",
    "o4-mini",
    "o4-mini-high",
]
MODEL_ALIASES = {
    "gpt-5.1": "gpt-5-1",
    "gpt-4.1": "gpt-4.1",
    "gpt-4.1-mini": "gpt-4.1-mini",
    "gpt-4.5": "gpt-4.5",
}
DEFAULT_RUNTIME_STATE = {
    "model": DEFAULT_MODEL,
    "language": "en",
    "web_search": False,
    "reasoning_effort": None,
    "show_metrics": True,
}
UPLOAD_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.8",
    "priority": "u=1, i",
    "referer": CHAT_URL,
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "cross-site",
}
FILE_CACHE: dict[str, dict[str, Any]] = {}


class UiColors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GRAY = "\033[90m"


def supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    return sys.stdout.isatty()


USE_COLOR = supports_color()


def paint(text: str, color: str = "", bold: bool = False, dim: bool = False) -> str:
    if not USE_COLOR:
        return text
    prefix = ""
    if bold:
        prefix += UiColors.BOLD
    if dim:
        prefix += UiColors.DIM
    if color:
        prefix += color
    return f"{prefix}{text}{UiColors.RESET}"


def info(text: str) -> None:
    print(paint(text, UiColors.BLUE))


def success(text: str) -> None:
    print(paint(text, UiColors.GREEN))


def warning(text: str) -> None:
    print(paint(text, UiColors.YELLOW))


def error(text: str) -> None:
    print(paint(text, UiColors.RED, bold=True))


TRANSLATIONS = {
    "en": {
        "assistant_prefix": "assistant> ",
        "warmup": "Warmup...",
        "warmup_ok": "ok",
        "warmup_skip": "skip",
        "mini_cli": "Mini ChatGPT CLI. Type /help",
        "auth_source": "Auth source: {auth_source}",
        "no_active_chat": "No active chat selected",
        "new_chat_title": "New chat",
        "active_chat": "Active: {chat_id} [{mode}] {title} (conversation_id: {conversation_id})",
        "temporary_mode": "temporary",
        "persistent_mode": "persistent",
        "chat_list_empty": "Chat list is empty",
        "settings": "Settings: model={model}, language={language}, search_hint={search_hint}, effort_hint={effort_hint}, metrics={metrics}",
        "model_not_listed": "Current model is not in the list: {model}",
        "img_usage": "Usage: /img <path_or_url> :: <prompt>",
        "file_not_found": "File not found: {path}",
        "empty_media_path": "Empty media path",
        "help_text": """\
Commands:
  /help                    Show commands
  /models                  Show available models
  /list                    Show chats
  /active                  Show active chat
  /new [tmp=true|false] [title]
  /use <chat_id>
  /delete [chat_id]
  /reset
  /tmp <true|false>
  /title <text>
  /rename <text>
  /clear

Runtime:
  /settings
  /model <name>
  /lang <en|ru>            Set interface + default reply language
  /ws <true|false>         Best-effort web search hint
  /effort <standard|extended|off>
                            Best-effort reasoning hint
  /metrics <true|false>    Toggle metrics output

Media:
  /img <path_or_url> :: <prompt>

  /exit
""",
        "created_chat": "Created chat: {chat_id} (temporary={temporary})",
        "created_default_chat": "Created default chat: {chat_id}",
        "usage_use": "Usage: /use <chat_id>",
        "deleted_chat": "Deleted chat: {chat_id}",
        "no_chats_left": "No chats left. Create a new one with /new",
        "reset_chat": "Reset chat context: {chat_id}",
        "temporary_value": "temporary={value}",
        "usage_title": "Usage: /title <text>",
        "unknown_command": "Unknown command. Type /help",
        "search_hint_info": "web_search is a best-effort hint. Use /reset or /new to apply it cleanly.",
        "effort_hint_info": "reasoning_effort is a best-effort hint. Use /reset or /new to apply it cleanly.",
        "command_error": "Command error: {error_type}: {error}",
        "request_error": "Request error: {error_type}: {error}",
    },
    "ru": {
        "assistant_prefix": "ассистент> ",
        "warmup": "Прогрев...",
        "warmup_ok": "ok",
        "warmup_skip": "skip",
        "mini_cli": "Mini ChatGPT CLI. Введите /help",
        "auth_source": "Источник авторизации: {auth_source}",
        "no_active_chat": "Активный чат не выбран",
        "new_chat_title": "Новый чат",
        "active_chat": "Активный чат: {chat_id} [{mode}] {title} (conversation_id: {conversation_id})",
        "temporary_mode": "temporary",
        "persistent_mode": "persistent",
        "chat_list_empty": "Список чатов пуст",
        "settings": "Настройки: model={model}, language={language}, search_hint={search_hint}, effort_hint={effort_hint}, metrics={metrics}",
        "model_not_listed": "Текущей модели нет в списке: {model}",
        "img_usage": "Использование: /img <path_or_url> :: <prompt>",
        "file_not_found": "Файл не найден: {path}",
        "empty_media_path": "Пустой путь к файлу",
        "help_text": """\
Команды:
  /help                    Показать команды
  /models                  Показать доступные модели
  /list                    Показать чаты
  /active                  Показать активный чат
  /new [tmp=true|false] [title]
  /use <chat_id>
  /delete [chat_id]
  /reset
  /tmp <true|false>
  /title <text>
  /rename <text>
  /clear

Режим:
  /settings
  /model <name>
  /lang <en|ru>            Язык интерфейса и ответов по умолчанию
  /ws <true|false>         Best-effort подсказка для web search
  /effort <standard|extended|off>
                            Best-effort подсказка для reasoning
  /metrics <true|false>    Включить или выключить метрики

Медиа:
  /img <path_or_url> :: <prompt>

  /exit
""",
        "created_chat": "Создан чат: {chat_id} (temporary={temporary})",
        "created_default_chat": "Создан чат по умолчанию: {chat_id}",
        "usage_use": "Использование: /use <chat_id>",
        "deleted_chat": "Удален чат: {chat_id}",
        "no_chats_left": "Чатов не осталось. Создайте новый через /new",
        "reset_chat": "Сброшен контекст чата: {chat_id}",
        "temporary_value": "temporary={value}",
        "usage_title": "Использование: /title <text>",
        "unknown_command": "Неизвестная команда. Введите /help",
        "search_hint_info": "web_search работает как best-effort hint. Для чистого применения используйте /reset или /new.",
        "effort_hint_info": "reasoning_effort работает как best-effort hint. Для чистого применения используйте /reset или /new.",
        "command_error": "Ошибка команды: {error_type}: {error}",
        "request_error": "Ошибка запроса: {error_type}: {error}",
    },
}


def normalize_language(value: Any) -> str:
    normalized = str(value or "en").strip().lower()
    return normalized if normalized in {"en", "ru"} else "en"


def tr(locale: str, key: str, **kwargs: Any) -> str:
    normalized = normalize_language(locale)
    template = TRANSLATIONS.get(normalized, TRANSLATIONS["en"]).get(key)
    if template is None:
        template = TRANSLATIONS["en"].get(key, key)
    return str(template).format(**kwargs)


def assistant_prefix_text(language: str) -> str:
    return paint(tr(language, "assistant_prefix"), UiColors.GREEN, bold=True)


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


def parse_reasoning_effort(value: str) -> str | None:
    normalized = value.strip().lower()
    if normalized in {"off", "none", "-", ""}:
        return None
    if normalized not in {"standard", "extended"}:
        raise ValueError("Effort must be one of: standard, extended, off")
    return normalized


def parse_language(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in {"en", "ru"}:
        raise ValueError("Language must be one of: en, ru")
    return normalized


def _safe_print(text: str) -> None:
    try:
        print(text, end="", flush=True)
    except UnicodeEncodeError:
        data = text.encode(sys.stdout.encoding or "utf-8", errors="replace")
        if hasattr(sys.stdout, "buffer"):
            sys.stdout.buffer.write(data)
            sys.stdout.flush()
        else:
            sys.stdout.write(data.decode(sys.stdout.encoding or "utf-8", errors="replace"))
            sys.stdout.flush()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _format_metric_seconds(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.3f}s"
    return "-"


def _read_json_dict(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_app_state_payload() -> dict[str, Any]:
    return _read_json_dict(APP_STATE_FILE)


def _save_app_state_payload(payload: dict[str, Any]) -> None:
    APP_STATE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _build_runtime_system_prompt(
    language: str,
    web_search: bool,
    reasoning_effort: Optional[str],
) -> Optional[str]:
    lines: list[str] = []
    if normalize_language(language) == "ru":
        lines.append("Always answer in Russian unless the user explicitly asks for another language.")
    else:
        lines.append("Always answer in English unless the user explicitly asks for another language.")
    if not web_search:
        lines.append("Do not browse the web or use search unless the user explicitly asks for it.")
    if reasoning_effort == "standard":
        lines.append("Prefer concise reasoning and avoid extended deliberation unless necessary.")
    elif reasoning_effort == "extended":
        lines.append("Take extra care and reason more thoroughly before answering.")
    if not lines:
        return None
    return "\n".join(lines)


def load_cli_state() -> dict[str, Any]:
    state = DEFAULT_RUNTIME_STATE.copy()
    payload = _load_app_state_payload().get("runtime")
    if not isinstance(payload, dict):
        payload = _read_json_dict(LEGACY_CLI_STATE_FILE)
    model = payload.get("model")
    if isinstance(model, str) and model.strip():
        state["model"] = model.strip()
    language = payload.get("language")
    if isinstance(language, str):
        state["language"] = normalize_language(language)
    if isinstance(payload.get("web_search"), bool):
        state["web_search"] = payload["web_search"]
    reasoning_effort = payload.get("reasoning_effort")
    if reasoning_effort is None:
        state["reasoning_effort"] = None
    elif isinstance(reasoning_effort, str):
        try:
            state["reasoning_effort"] = parse_reasoning_effort(reasoning_effort)
        except ValueError:
            pass
    if isinstance(payload.get("show_metrics"), bool):
        state["show_metrics"] = payload["show_metrics"]
    return state


def save_cli_state(state: dict[str, Any]) -> None:
    runtime_payload = {
        "model": state["model"],
        "language": normalize_language(state["language"]),
        "web_search": bool(state["web_search"]),
        "reasoning_effort": state["reasoning_effort"],
        "show_metrics": bool(state["show_metrics"]),
    }
    payload = _load_app_state_payload()
    payload["runtime"] = runtime_payload
    _save_app_state_payload(payload)


@dataclass
class AuthData:
    api_key: Optional[str] = None
    api_key_source: Optional[str] = None
    cookies: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    expires: Optional[int] = None
    proof_token: Any = None
    turnstile_token: Optional[str] = None

    @classmethod
    def from_json(cls, path: str | Path) -> "AuthData":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            api_key=payload.get("api_key"),
            cookies=payload.get("cookies") or {},
            headers=payload.get("headers") or {},
            expires=payload.get("expires"),
            proof_token=payload.get("proof_token"),
            turnstile_token=payload.get("turnstile_token"),
        )


def _iter_env_candidates() -> list[Path]:
    script_dir = Path(__file__).resolve().parent
    candidates = [
        Path.cwd() / ".env",
        script_dir / ".env",
        script_dir.parent / ".env",
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _load_access_token() -> Optional[str]:
    if os.getenv("accessToken"):
        return os.getenv("accessToken")
    for env_path in _iter_env_candidates():
        if not env_path.is_file():
            continue
        try:
            text = env_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() != "accessToken":
                continue
            token = value.strip().strip("'").strip('"')
            if token:
                os.environ["accessToken"] = token
                return token
    return None


def _get_access_token_expiry(access_token: Optional[str]) -> Optional[datetime]:
    if not access_token or access_token.count(".") < 2:
        return None
    try:
        payload = access_token.split(".", 2)[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        exp = data.get("exp")
        if exp is None:
            return None
        return datetime.fromtimestamp(int(exp), tz=timezone.utc)
    except Exception:
        return None


def load_auth_data(auth_file: str | Path = DEFAULT_AUTH_FILE) -> AuthData:
    auth = AuthData.from_json(auth_file)
    candidates: list[tuple[str, str]] = []
    if auth.api_key:
        candidates.append((f"{Path(auth_file).name}:api_key", auth.api_key))
    env_api_key = _load_access_token()
    if env_api_key and env_api_key != auth.api_key:
        candidates.append((".env:accessToken", env_api_key))

    expired_sources: list[str] = []
    now_utc = datetime.now(timezone.utc)
    for source, token in candidates:
        expires_at = _get_access_token_expiry(token)
        if expires_at is not None and expires_at <= now_utc:
            expires_local = expires_at.astimezone()
            expired_sources.append(
                f"{source} expired at {expires_local.strftime('%Y-%m-%d %H:%M:%S %z')}"
            )
            continue
        auth.api_key = token
        auth.api_key_source = source
        break

    if not auth.api_key:
        if expired_sources:
            raise RuntimeError(
                "All available access tokens are expired: "
                + "; ".join(expired_sources)
                + ". Refresh authorization before running the CLI."
            )
        raise RuntimeError(
            f"No access token found. Expected api_key in {Path(auth_file).name}"
            " or accessToken in .env."
        )
    return auth


def _build_base_headers(auth: AuthData) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in auth.headers.items():
        if key is None or value is None:
            continue
        key_str = str(key).lower()
        if key_str in {"authorization", "cookie"}:
            continue
        headers[key_str] = str(value)
    headers.setdefault("accept", "*/*")
    headers.setdefault("accept-language", "en-US,en;q=0.8")
    headers.setdefault("content-type", "application/json")
    headers.setdefault("referer", CHAT_URL)
    headers.setdefault(
        "user-agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    )
    return headers


def _generate_answer(seed: str, diff: str, config: list[Any], max_attempts: int = 500_000) -> tuple[str, bool]:
    diff_len = len(diff)
    seed_encoded = seed.encode()
    p1 = (json.dumps(config[:3], separators=(",", ":"), ensure_ascii=False)[:-1] + ",").encode()
    p2 = ("," + json.dumps(config[4:9], separators=(",", ":"), ensure_ascii=False)[1:-1] + ",").encode()
    p3 = ("," + json.dumps(config[10:], separators=(",", ":"), ensure_ascii=False)[1:]).encode()
    target_diff = bytes.fromhex(diff)
    for i in range(max_attempts):
        d1 = str(i).encode()
        d2 = str(i >> 1).encode()
        string = p1 + d1 + p2 + d2 + p3
        base_encode = base64.b64encode(string)
        hash_value = hashlib.new("sha3_512", seed_encoded + base_encode).digest()
        if hash_value[:diff_len] <= target_diff:
            return base_encode.decode(), True
    fallback = base64.b64encode(f'"{seed}"'.encode()).decode()
    return "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D" + fallback, False


def _get_requirements_token(config: list[Any]) -> str:
    require, solved = _generate_answer(format(random.random()), "0fffff", config)
    if not solved:
        raise RuntimeError("Failed to solve requirements challenge")
    return "gAAAAAC" + require


def _generate_proof_token(
    *,
    required: bool,
    seed: str = "",
    difficulty: str = "",
    user_agent: Optional[str] = None,
    proof_token: Any = None,
) -> Optional[str]:
    if not required:
        return None
    if proof_token is None:
        screen = random.choice([3008, 4010, 6000]) * random.choice([1, 2, 4])
        parse_time = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        proof_token = [
            screen,
            parse_time,
            None,
            0,
            user_agent,
            "https://tcr9i.chat.openai.com/v2/35536E1E-65B4-4D96-9D97-6ADB7EFF8147/api.js",
            "dpl=1440a687921de39ff5ee56b92807faaadce73f13",
            "en",
            "en-US",
            None,
            "plugins-[object PluginArray]",
            random.choice(
                [
                    "_reactListeningcfilawjnerp",
                    "_reactListening9ne2dfo1i47",
                    "_reactListening410nzwhan2a",
                ]
            ),
            random.choice(["alert", "ontransitionend", "onprogress"]),
        ]
    diff_len = len(difficulty)
    for i in range(100_000):
        proof_token[3] = i
        payload = json.dumps(proof_token)
        base = base64.b64encode(payload.encode()).decode()
        hash_value = hashlib.sha3_512((seed + base).encode()).digest()
        if hash_value.hex()[:diff_len] <= difficulty:
            return "gAAAAAB" + base
    fallback = base64.b64encode(f'"{seed}"'.encode()).decode()
    return "gAAAAABwQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D" + fallback


def _extract_data_uri(data_uri: str) -> bytes:
    match = re.match(r"^data:([^;]+);base64,(.+)$", data_uri, re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError("Invalid data URI")
    return base64.b64decode(match.group(2))


def _detect_file_type(binary_data: bytes) -> tuple[str, str]:
    if binary_data.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if binary_data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if binary_data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif", "image/gif"
    if binary_data.startswith(b"RIFF") and binary_data[8:12] == b"WEBP":
        return ".webp", "image/webp"
    raise ValueError("Unsupported media format")


def _get_png_size(data: bytes) -> tuple[Optional[int], Optional[int]]:
    if len(data) < 24:
        return None, None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _get_gif_size(data: bytes) -> tuple[Optional[int], Optional[int]]:
    if len(data) < 10:
        return None, None
    return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")


def _get_jpeg_size(data: bytes) -> tuple[Optional[int], Optional[int]]:
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if marker in {0x01} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(data):
            break
        segment_length = int.from_bytes(data[index:index + 2], "big")
        if segment_length < 2 or index + segment_length > len(data):
            break
        if marker in {
            0xC0, 0xC1, 0xC2, 0xC3,
            0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB,
            0xCD, 0xCE, 0xCF,
        }:
            if index + 7 <= len(data):
                height = int.from_bytes(data[index + 3:index + 5], "big")
                width = int.from_bytes(data[index + 5:index + 7], "big")
                return width, height
            break
        index += segment_length
    return None, None


def _get_webp_size(data: bytes) -> tuple[Optional[int], Optional[int]]:
    if len(data) < 30:
        return None, None
    chunk_type = data[12:16]
    if chunk_type == b"VP8X" and len(data) >= 30:
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    if chunk_type == b"VP8 " and len(data) >= 30:
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return width, height
    if chunk_type == b"VP8L" and len(data) >= 25:
        bits = int.from_bytes(data[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    return None, None


def _get_image_size(data: bytes, mime_type: str) -> tuple[Optional[int], Optional[int]]:
    if mime_type == "image/png":
        return _get_png_size(data)
    if mime_type == "image/gif":
        return _get_gif_size(data)
    if mime_type == "image/jpeg":
        return _get_jpeg_size(data)
    if mime_type == "image/webp":
        return _get_webp_size(data)
    return None, None


class ChatGPTWebClient:
    def __init__(self, auth_file: str | Path = DEFAULT_AUTH_FILE, timeout: int = DEFAULT_TIMEOUT_SECONDS):
        self.auth = load_auth_data(auth_file)
        self.timeout = max(10, int(timeout))
        self.base_headers = _build_base_headers(self.auth)
        self.curl_bin = shutil.which("curl.exe") or shutil.which("curl")
        if not self.curl_bin:
            raise RuntimeError(
                "curl executable was not found. Install curl or run on a system where curl is available."
            )
        self.prefetched_requirements: Optional[dict[str, Any]] = None
        self.prefetched_proof_header: Optional[str] = None
        self.prefetched_ts = 0.0

    def _build_headers(self, extra: Optional[dict[str, str]] = None) -> dict[str, str]:
        headers = dict(self.base_headers)
        if self.auth.api_key:
            headers["authorization"] = f"Bearer {self.auth.api_key}"
        if self.auth.cookies:
            headers["cookie"] = "; ".join(f"{k}={v}" for k, v in self.auth.cookies.items())
        if extra:
            headers.update({key: value for key, value in extra.items() if value is not None})
        return headers

    def _update_cookies_from_text(self, header_text: str) -> None:
        for raw_line in header_text.splitlines():
            if not raw_line.lower().startswith("set-cookie:"):
                continue
            raw_cookie = raw_line.split(":", 1)[1].strip()
            jar = SimpleCookie()
            jar.load(raw_cookie)
            for key, morsel in jar.items():
                self.auth.cookies[key] = morsel.value

    @staticmethod
    def _extract_status_code(header_text: str) -> int:
        status = 0
        for raw_line in header_text.splitlines():
            line = raw_line.strip()
            if not line.startswith("HTTP/"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                status = int(parts[1])
        return status

    def _build_curl_command(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        header_path: str,
        body_path: Optional[str] = None,
        *,
        no_buffer: bool = False,
        follow_redirects: bool = False,
    ) -> list[str]:
        command = [
            self.curl_bin,
            "-sS",
            "--compressed",
            "--connect-timeout",
            "10",
            "--max-time",
            str(self.timeout),
            "-X",
            method.upper(),
            url,
            "-D",
            header_path,
        ]
        if no_buffer:
            command.insert(1, "-N")
        if follow_redirects:
            command.insert(1, "-L")
        for key, value in headers.items():
            command.extend(["-H", f"{key}: {value}"])
        if body_path is not None:
            command.extend(["--data-binary", f"@{body_path}"])
        return command

    def _run_curl(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: Optional[bytes] = None,
        *,
        persist_cookies: bool = True,
        follow_redirects: bool = False,
    ) -> tuple[int, bytes, str]:
        payload_path: Optional[str] = None
        with tempfile.NamedTemporaryFile(delete=False) as header_file:
            header_path = header_file.name
        try:
            if body is not None:
                with tempfile.NamedTemporaryFile(delete=False) as payload_file:
                    payload_file.write(body)
                    payload_path = payload_file.name
            command = self._build_curl_command(
                method,
                url,
                headers,
                header_path,
                payload_path,
                follow_redirects=follow_redirects,
            )
            result = subprocess.run(command, capture_output=True)
            header_text = Path(header_path).read_text(encoding="utf-8", errors="replace")
            if persist_cookies:
                self._update_cookies_from_text(header_text)
            status = self._extract_status_code(header_text)
            if result.returncode != 0 and not status:
                stderr_text = result.stderr.decode("utf-8", errors="replace")
                raise RuntimeError(f"curl failed: {stderr_text.strip() or result.returncode}")
            return status, result.stdout, header_text
        finally:
            try:
                Path(header_path).unlink(missing_ok=True)
            except OSError:
                pass
            if payload_path:
                try:
                    Path(payload_path).unlink(missing_ok=True)
                except OSError:
                    pass

    def _json_request(
        self,
        method: str,
        url: str,
        payload: Optional[dict[str, Any]],
        headers: dict[str, str],
    ) -> tuple[int, Any]:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        status, raw_body, _ = self._run_curl(method, url, headers, body)
        if not raw_body:
            return status, None
        body_text = raw_body.decode("utf-8", errors="replace")
        try:
            return status, json.loads(body_text)
        except ValueError:
            return status, body_text

    def warmup(self) -> bool:
        try:
            requirements = self._get_chat_requirements()
            proof_header = self._build_proof_header(requirements)
        except Exception:
            return False
        token = requirements.get("token") if isinstance(requirements, dict) else None
        if isinstance(token, str) and token:
            self.prefetched_requirements = requirements
            self.prefetched_proof_header = proof_header
            self.prefetched_ts = time.monotonic()
            return True
        return False

    def _take_prefetched_requirements(self) -> Optional[tuple[dict[str, Any], Optional[str]]]:
        if self.prefetched_requirements is None:
            return None
        if time.monotonic() - self.prefetched_ts > PREFETCH_TTL_SECONDS:
            self.prefetched_requirements = None
            self.prefetched_proof_header = None
            self.prefetched_ts = 0.0
            return None
        requirements = self.prefetched_requirements
        proof_header = self.prefetched_proof_header
        self.prefetched_requirements = None
        self.prefetched_proof_header = None
        self.prefetched_ts = 0.0
        return requirements, proof_header

    def _get_ready_requirements(self) -> tuple[dict[str, Any], Optional[str]]:
        prefetched = self._take_prefetched_requirements()
        if prefetched is not None:
            return prefetched
        requirements = self._get_chat_requirements()
        return requirements, self._build_proof_header(requirements)

    def _get_chat_requirements(self) -> dict[str, Any]:
        req_input = None
        if isinstance(self.auth.proof_token, list):
            try:
                req_input = _get_requirements_token(self.auth.proof_token)
            except Exception:
                req_input = None
        headers = self._build_headers({"accept": "*/*", "content-type": "application/json"})
        status, data = self._json_request("POST", CHAT_REQUIREMENTS_URL, {"p": req_input}, headers)
        if status in {401, 403}:
            raise RuntimeError(f"chat-requirements status={status}")
        if status >= 400:
            raise RuntimeError(f"chat-requirements status={status}: {data}")
        if not isinstance(data, dict):
            raise RuntimeError("chat-requirements response is not a dict")
        return data

    def _build_proof_header(self, requirements: dict[str, Any]) -> Optional[str]:
        proof_block = requirements.get("proofofwork")
        if not isinstance(proof_block, dict):
            return None
        return _generate_proof_token(
            required=bool(proof_block.get("required")),
            seed=str(proof_block.get("seed") or ""),
            difficulty=str(proof_block.get("difficulty") or ""),
            user_agent=self.base_headers.get("user-agent"),
            proof_token=self.auth.proof_token if isinstance(self.auth.proof_token, list) else None,
        )

    def _media_to_bytes(self, media_data: Any) -> bytes:
        if isinstance(media_data, bytes):
            return media_data
        if isinstance(media_data, bytearray):
            return bytes(media_data)
        if isinstance(media_data, Path):
            return media_data.read_bytes()
        if isinstance(media_data, os.PathLike):
            return Path(media_data).read_bytes()
        if isinstance(media_data, str):
            if media_data.startswith("data:"):
                return _extract_data_uri(media_data)
            if media_data.startswith(("http://", "https://")):
                status, raw_body, _ = self._run_curl(
                    "GET",
                    media_data,
                    {"user-agent": self.base_headers.get("user-agent", "")},
                    persist_cookies=False,
                    follow_redirects=True,
                )
                if not 200 <= status < 300:
                    raise RuntimeError(f"Media download failed: status={status}")
                return raw_body
            raise ValueError("Unsupported media string. Use file path, URL, or data URI.")
        raise ValueError("Unsupported media type")

    def _upload_media_files(self, media: list[tuple[Any, Optional[str]]]) -> list[dict[str, Any]]:
        uploaded: list[dict[str, Any]] = []
        for media_item in media:
            media_data, filename = media_item
            data_bytes = self._media_to_bytes(media_data)
            cache_key = hashlib.md5(data_bytes).hexdigest()
            cached = FILE_CACHE.get(cache_key)
            if cached is not None:
                uploaded.append(cached.copy())
                continue
            extension, mime_type = _detect_file_type(data_bytes)
            width, height = _get_image_size(data_bytes, mime_type)
            if not filename and isinstance(media_data, (str, Path, os.PathLike)):
                parsed_path = str(media_data)
                if parsed_path.startswith(("http://", "https://")):
                    filename = Path(urlparse(parsed_path).path).name or None
                else:
                    filename = Path(parsed_path).name or None
            if not filename:
                filename = f"file-{len(data_bytes)}{extension}"
            create_headers = self._build_headers({"content-type": "application/json"})
            create_payload = {
                "file_name": filename,
                "file_size": len(data_bytes),
                "use_case": "multimodal",
            }
            status, created = self._json_request("POST", CHAT_FILES_URL, create_payload, create_headers)
            if status >= 400 or not isinstance(created, dict):
                raise RuntimeError(f"Create file failed: status={status} body={created}")
            upload_headers = {
                **UPLOAD_HEADERS,
                "content-type": mime_type,
                "origin": CHAT_URL.rstrip("/"),
                "user-agent": self.base_headers.get("user-agent", ""),
                "x-ms-blob-type": "BlockBlob",
                "x-ms-version": "2020-04-08",
            }
            upload_status, upload_body, _ = self._run_curl(
                "PUT",
                created["upload_url"],
                upload_headers,
                data_bytes,
                persist_cookies=False,
            )
            if upload_status >= 400:
                body_text = upload_body.decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"Upload file failed: status={upload_status} body={body_text[:300]}"
                )
            finalize_status, finalized = self._json_request(
                "POST",
                f"{CHAT_FILES_URL}/{created['file_id']}/uploaded",
                {},
                create_headers,
            )
            if finalize_status >= 400:
                raise RuntimeError(f"Finalize file failed: status={finalize_status} body={finalized}")
            payload = {
                **create_payload,
                **created,
                "mime_type": mime_type,
                "extension": extension,
                "width": width,
                "height": height,
                "download_url": finalized.get("download_url") if isinstance(finalized, dict) else None,
            }
            FILE_CACHE[cache_key] = payload.copy()
            uploaded.append(payload)
        return uploaded

    def _create_messages(
        self,
        prompt: str,
        system: Optional[str],
        *,
        image_requests: Optional[list[dict[str, Any]]] = None,
        system_hints: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if isinstance(system, str) and system.strip():
            messages.append({"role": "system", "content": system.strip()})
        messages.append({"role": "user", "content": prompt})
        payload: list[dict[str, Any]] = []
        for message in messages:
            payload.append(
                {
                    "id": str(uuid.uuid4()),
                    "author": {"role": message["role"]},
                    "content": {"content_type": "text", "parts": [str(message["content"])]},
                    "metadata": {
                        "serialization_metadata": {"custom_symbol_offsets": []},
                        **({"system_hints": system_hints} if system_hints else {}),
                    },
                    "create_time": time.time(),
                }
            )
        if image_requests:
            payload[-1]["content"] = {
                "content_type": "multimodal_text",
                "parts": [
                    *[
                        {
                            "asset_pointer": f"file-service://{image_request['file_id']}",
                            "height": image_request.get("height"),
                            "size_bytes": image_request.get("file_size"),
                            "width": image_request.get("width"),
                        }
                        for image_request in image_requests
                    ],
                    payload[-1]["content"]["parts"][0],
                ],
            }
            payload[-1]["metadata"] = {
                "attachments": [
                    {
                        "id": image_request["file_id"],
                        "mimeType": image_request.get("mime_type"),
                        "name": image_request.get("file_name"),
                        "size": image_request.get("file_size"),
                        **(
                            {
                                "height": image_request.get("height"),
                                "width": image_request.get("width"),
                            }
                            if image_request.get("width") and image_request.get("height")
                            else {}
                        ),
                    }
                    for image_request in image_requests
                ]
            }
        return payload

    @staticmethod
    def _parse_event(payload: Any, state: dict[str, Any]) -> tuple[list[str], Optional[str]]:
        if not isinstance(payload, dict):
            return [], None
        if payload.get("error"):
            raise RuntimeError(str(payload.get("error")))
        if payload.get("type") == "title_generation":
            title = payload.get("title")
            return [], title.strip() if isinstance(title, str) and title.strip() else None
        output: list[str] = []
        value = payload.get("v")
        path = payload.get("p")
        if isinstance(value, dict):
            conversation_id = value.get("conversation_id")
            if isinstance(conversation_id, str) and conversation_id:
                state["conversation_id"] = conversation_id
            message = value.get("message")
            if isinstance(message, dict):
                recipient = message.get("recipient")
                if isinstance(recipient, str):
                    state["recipient"] = recipient
                if (
                    message.get("author", {}).get("role") == "assistant"
                    and isinstance(message.get("id"), str)
                    and message.get("id")
                ):
                    state["message_id"] = message["id"]
                    state["parent_message_id"] = message["id"]
            return output, None
        if isinstance(value, str):
            if state.get("recipient", "all") == "all" and path in (None, "/message/content/parts/0"):
                output.append(value)
            return output, None
        if isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                if item.get("p") == "/message/content/parts/0" and state.get("recipient", "all") == "all":
                    token = item.get("v")
                    if isinstance(token, str):
                        output.append(token)
                elif item.get("p") == "/message/metadata" and state.get("recipient", "all") == "all":
                    finish_reason = item.get("v", {}).get("finish_details", {}).get("type")
                    if finish_reason:
                        state["finish_reason"] = finish_reason
            return output, None
        return output, None

    def ask_stream(
        self,
        prompt: str,
        *,
        model: str,
        system: Optional[str],
        web_search: bool,
        temporary: bool,
        reasoning_effort: Optional[str],
        conversation: Optional[dict[str, Any]],
        media: Optional[list[tuple[Any, Optional[str]]]] = None,
        token_callback: Optional[Callable[[str], None]] = None,
    ) -> dict[str, Any]:
        image_requests = self._upload_media_files(media or []) if media else None
        requirements, proof_header = self._get_ready_requirements()
        chat_token = requirements.get("token")
        if not isinstance(chat_token, str) or not chat_token:
            raise RuntimeError("chat-requirements token is missing")
        conversation_id = None
        parent_message_id = str(uuid.uuid4())
        user_id = None
        if isinstance(conversation, dict):
            conversation_id = conversation.get("conversation_id") or None
            parent_message_id = (
                conversation.get("parent_message_id")
                or conversation.get("message_id")
                or parent_message_id
            )
            user_id = conversation.get("user_id")
        payload: dict[str, Any] = {
            "action": "next",
            "parent_message_id": parent_message_id,
            "model": MODEL_ALIASES.get(model, model),
            "conversation_mode": {"kind": "primary_assistant"},
            "enable_message_followups": False,
            "supports_buffering": True,
            "supported_encodings": ["v1"],
            "messages": self._create_messages(
                prompt,
                None if conversation_id else system,
                image_requests=image_requests,
                system_hints=["search"] if web_search else None,
            ),
        }
        if temporary:
            payload["history_and_training_disabled"] = True
        if conversation_id:
            payload["conversation_id"] = conversation_id
        if web_search:
            payload["system_hints"] = ["search"]
        if reasoning_effort is not None:
            payload["thinking_effort"] = reasoning_effort
        headers = self._build_headers(
            {
                "accept": "text/event-stream",
                "content-type": "application/json",
                "openai-sentinel-chat-requirements-token": chat_token,
                "openai-sentinel-proof-token": proof_header,
                "openai-sentinel-turnstile-token": self.auth.turnstile_token
                if (requirements.get("turnstile") or {}).get("required")
                else None,
            }
        )
        state = {
            "recipient": "all",
            "conversation_id": conversation_id,
            "message_id": conversation.get("message_id") if isinstance(conversation, dict) else None,
            "parent_message_id": parent_message_id,
            "finish_reason": "stop",
        }
        first_token_latency: Optional[float] = None
        last_token_latency: Optional[float] = None
        full_chunks: list[str] = []
        title_update: Optional[str] = None
        started_at = time.perf_counter()
        payload_path: Optional[str] = None
        with tempfile.NamedTemporaryFile(delete=False) as header_file:
            header_path = header_file.name
        try:
            with tempfile.NamedTemporaryFile(delete=False) as payload_file:
                payload_file.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                payload_path = payload_file.name
            command = self._build_curl_command(
                "POST",
                CHAT_BACKEND_URL,
                headers,
                header_path,
                payload_path,
                no_buffer=True,
            )
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            error_body: list[bytes] = []
            assert process.stdout is not None
            for raw_line in iter(process.stdout.readline, b""):
                if len(error_body) < 64:
                    error_body.append(raw_line)
                if not raw_line.startswith(b"data: "):
                    continue
                if raw_line.startswith(b"data: [DONE]"):
                    break
                try:
                    event_payload = json.loads(raw_line[6:])
                except ValueError:
                    continue
                tokens, maybe_title = self._parse_event(event_payload, state)
                if maybe_title and title_update is None:
                    title_update = maybe_title
                for token in tokens:
                    if not token:
                        continue
                    now = time.perf_counter()
                    if first_token_latency is None:
                        first_token_latency = now - started_at
                    last_token_latency = now - started_at
                    full_chunks.append(token)
                    if token_callback is not None:
                        token_callback(token)
            stderr_text = ""
            if process.stderr is not None:
                stderr_text = process.stderr.read().decode("utf-8", errors="replace")
            return_code = process.wait()
            header_text = Path(header_path).read_text(encoding="utf-8", errors="replace")
            self._update_cookies_from_text(header_text)
            status = self._extract_status_code(header_text)
            if status >= 400:
                body_text = b"".join(error_body).decode("utf-8", errors="replace")
                raise RuntimeError(f"backend status={status}: {body_text[:300]}")
            if return_code != 0:
                raise RuntimeError(f"curl failed: {stderr_text.strip() or return_code}")
        finally:
            try:
                Path(header_path).unlink(missing_ok=True)
            except OSError:
                pass
            if payload_path:
                try:
                    Path(payload_path).unlink(missing_ok=True)
                except OSError:
                    pass
        total_latency = time.perf_counter() - started_at
        self.prefetched_requirements = None
        self.prefetched_proof_header = None
        self.prefetched_ts = 0.0
        return {
            "text": "".join(full_chunks),
            "title": title_update,
            "conversation": {
                "conversation_id": state.get("conversation_id"),
                "message_id": state.get("message_id") or state.get("parent_message_id"),
                "user_id": user_id,
                "finish_reason": state.get("finish_reason"),
                "parent_message_id": state.get("parent_message_id"),
                "is_thinking": False,
            },
            "metrics": {
                "first_token": first_token_latency,
                "last_token": last_token_latency,
                "total": total_latency,
            },
        }
class CliChatApp:
    def __init__(
        self,
        state_path: str | Path = APP_STATE_FILE,
        auth_file: str | Path = DEFAULT_AUTH_FILE,
    ):
        self.transport = ChatGPTWebClient(auth_file=auth_file)
        self.state_path = Path(state_path)
        self._chats: dict[str, dict[str, Any]] = {}
        self._active_chat_id: Optional[str] = None
        self._load_chats()

    def list_models(self) -> list[str]:
        return list(SUPPORTED_MODELS)

    def _load_chats(self) -> None:
        payload = _load_app_state_payload()
        if not payload:
            payload = _read_json_dict(LEGACY_CHATS_STATE_FILE)
        chats = payload.get("chats") if isinstance(payload, dict) else None
        if isinstance(chats, dict):
            self._chats = {
                str(chat_id): data
                for chat_id, data in chats.items()
                if isinstance(data, dict)
            }
        active_chat_id = payload.get("active_chat_id") if isinstance(payload, dict) else None
        if isinstance(active_chat_id, str) and active_chat_id in self._chats:
            self._active_chat_id = active_chat_id

    def _save_chats(self) -> None:
        payload = _load_app_state_payload()
        payload["active_chat_id"] = self._active_chat_id
        payload["chats"] = self._chats
        _save_app_state_payload(payload)

    def new_chat(self, title: Optional[str] = None, temporary: bool = False) -> str:
        chat_id = uuid.uuid4().hex[:10]
        timestamp = _now_iso()
        self._chats[chat_id] = {
            "title": title or "New chat",
            "temporary": bool(temporary),
            "language": "en",
            "conversation": None,
            "model": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        self._active_chat_id = chat_id
        self._save_chats()
        return chat_id

    def list_chats(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for chat_id, data in self._chats.items():
            conversation = data.get("conversation") if isinstance(data, dict) else None
            conversation_id = None
            if isinstance(conversation, dict):
                conversation_id = conversation.get("conversation_id")
            items.append(
                {
                    "chat_id": chat_id,
                    "title": data.get("title", "New chat"),
                    "temporary": bool(data.get("temporary", False)),
                    "model": data.get("model"),
                    "conversation_id": conversation_id,
                    "created_at": data.get("created_at"),
                    "updated_at": data.get("updated_at"),
                }
            )
        return sorted(items, key=lambda item: item.get("updated_at") or "", reverse=True)

    def get_active_chat_id(self) -> Optional[str]:
        return self._active_chat_id

    def get_active_chat(self) -> Optional[dict[str, Any]]:
        if self._active_chat_id is None:
            return None
        return self._chats.get(self._active_chat_id)

    def switch_chat(self, chat_id: str) -> None:
        if chat_id not in self._chats:
            raise ValueError(f"Unknown chat_id: {chat_id}")
        self._active_chat_id = chat_id
        self._save_chats()

    def delete_chat(self, chat_id: Optional[str] = None) -> str:
        target_chat_id = chat_id or self._active_chat_id
        if target_chat_id is None or target_chat_id not in self._chats:
            raise ValueError("Chat not found")
        del self._chats[target_chat_id]
        if not self._chats:
            self._active_chat_id = None
        elif self._active_chat_id == target_chat_id or self._active_chat_id not in self._chats:
            self._active_chat_id = max(
                self._chats.items(),
                key=lambda item: item[1].get("updated_at") or "",
            )[0]
        self._save_chats()
        return target_chat_id

    def set_chat_title(self, title: str, chat_id: Optional[str] = None) -> None:
        target_chat_id = chat_id or self._active_chat_id
        if target_chat_id is None or target_chat_id not in self._chats:
            raise ValueError("Chat not found")
        self._chats[target_chat_id]["title"] = title.strip() or "New chat"
        self._chats[target_chat_id]["updated_at"] = _now_iso()
        self._save_chats()

    def set_chat_temporary(self, temporary: bool, chat_id: Optional[str] = None) -> None:
        target_chat_id = chat_id or self._active_chat_id
        if target_chat_id is None or target_chat_id not in self._chats:
            raise ValueError("Chat not found")
        self._chats[target_chat_id]["temporary"] = bool(temporary)
        self._chats[target_chat_id]["updated_at"] = _now_iso()
        self._save_chats()

    def reset_chat(self, chat_id: Optional[str] = None) -> str:
        target_chat_id = chat_id or self._active_chat_id
        if target_chat_id is None or target_chat_id not in self._chats:
            raise ValueError("Chat not found")
        self._chats[target_chat_id]["conversation"] = None
        self._chats[target_chat_id]["updated_at"] = _now_iso()
        self._save_chats()
        return target_chat_id

    def _ensure_chat(self, chat_id: Optional[str], temporary: Optional[bool]) -> tuple[str, dict[str, Any]]:
        target_chat_id = chat_id or self._active_chat_id
        if target_chat_id is None:
            target_chat_id = self.new_chat(temporary=bool(temporary) if temporary is not None else False)
        if target_chat_id not in self._chats:
            raise ValueError(f"Unknown chat_id: {target_chat_id}")
        self._active_chat_id = target_chat_id
        chat_state = self._chats[target_chat_id]
        chat_state.setdefault("language", "en")
        if temporary is not None:
            chat_state["temporary"] = bool(temporary)
        return target_chat_id, chat_state

    @staticmethod
    def _stream_print(text: str) -> None:
        _safe_print(text)

    def chat(
        self,
        user_prompt: str,
        *,
        model: str = DEFAULT_MODEL,
        language: str = "en",
        stream: bool = False,
        temporary: Optional[bool] = None,
        chat_id: Optional[str] = None,
        web_search: bool = False,
        reasoning_effort: Optional[str] = None,
        show_metrics: bool = True,
        media: Optional[list[tuple[Any, Optional[str]]]] = None,
        stream_prefix: Optional[str] = None,
    ) -> str:
        target_chat_id, chat_state = self._ensure_chat(chat_id, temporary)
        normalized_language = normalize_language(language)
        effective_temporary = bool(chat_state.get("temporary", False))
        normalized_effort = reasoning_effort.strip().lower() if isinstance(reasoning_effort, str) else None
        if normalized_effort in {"", "off", "none", "-"}:
            normalized_effort = None
        if normalized_effort not in {None, "standard", "extended"}:
            raise ValueError("reasoning_effort must be one of: standard, extended, off")
        if stream and stream_prefix:
            print(stream_prefix, end="", flush=True)
        request_kwargs = {
            "model": model,
            "system": _build_runtime_system_prompt(
                normalized_language,
                web_search,
                normalized_effort,
            ),
            "web_search": web_search,
            "temporary": effective_temporary,
            "reasoning_effort": normalized_effort,
            "media": media,
            "token_callback": self._stream_print if stream else None,
        }
        conversation = chat_state.get("conversation")
        try:
            response = self.transport.ask_stream(
                user_prompt,
                conversation=conversation,
                **request_kwargs,
            )
        except RuntimeError as exc:
            message = str(exc)
            if "Conversation not found" not in message and "history_disabled_conversation_not_found" not in message:
                raise
            chat_state["conversation"] = None
            response = self.transport.ask_stream(
                user_prompt,
                conversation=None,
                **request_kwargs,
            )
        output = response["text"]
        if stream and output and not output.endswith("\n"):
            print()
        metrics = response.get("metrics")
        if show_metrics and isinstance(metrics, dict):
            metrics_language = normalized_language
            metrics_label = "[metrics]" if metrics_language == "en" else "[метрики]"
            print(
                paint(
                    f"{metrics_label} "
                    f"first_token={_format_metric_seconds(metrics.get('first_token'))} "
                    f"last_token={_format_metric_seconds(metrics.get('last_token'))} "
                    f"total={_format_metric_seconds(metrics.get('total'))}",
                    UiColors.GRAY,
                    dim=True,
                )
            )
        conversation = response.get("conversation")
        if isinstance(conversation, dict):
            chat_state["conversation"] = conversation
        current_title = str(chat_state.get("title") or "").strip()
        title_update = _sanitize_generated_title(response.get("title"))
        if title_update and _is_placeholder_title(current_title):
            chat_state["title"] = title_update
        chat_state["model"] = model
        chat_state["language"] = normalized_language
        chat_state["temporary"] = effective_temporary
        chat_state["updated_at"] = _now_iso()
        self._active_chat_id = target_chat_id
        self._save_chats()
        return output


def _display_chat_title(title: Any, language: str) -> str:
    normalized = str(title or "").strip()
    if _is_placeholder_title(normalized):
        return tr(language, "new_chat_title")
    return normalized


def _is_placeholder_title(title: Any) -> bool:
    normalized = str(title or "").strip()
    if not normalized:
        return True
    lowered = normalized.lower()
    if lowered in {"new chat", "новый чат", "invalid input", "error", "ошибка"}:
        return True
    return all(ch in {"?", " "} for ch in normalized)


def _sanitize_generated_title(title: Any) -> Optional[str]:
    normalized = str(title or "").strip()
    if _is_placeholder_title(normalized):
        return None
    return normalized


def print_help_compact(language: str) -> None:
    print(
        paint(
            tr(language, "help_text"),
            UiColors.CYAN,
        )
    )


def build_media_item(raw_path: str, language: str) -> tuple[object, str | None]:
    path = raw_path.strip().strip('"').strip("'")
    if not path:
        raise ValueError(tr(language, "empty_media_path"))
    if path.startswith(("http://", "https://", "data:")):
        return path, None
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise ValueError(tr(language, "file_not_found", path=file_path))
    return file_path, file_path.name



def print_active(bot: CliChatApp, language: str) -> None:
    active_chat_id = bot.get_active_chat_id()
    active_chat = bot.get_active_chat()
    if active_chat_id is None or active_chat is None:
        warning(tr(language, "no_active_chat"))
        return
    mode = tr(language, "temporary_mode") if active_chat.get("temporary") else tr(language, "persistent_mode")
    title = _display_chat_title(active_chat.get("title"), language)
    conversation = active_chat.get("conversation") if isinstance(active_chat, dict) else None
    conversation_id = "-"
    if isinstance(conversation, dict):
        conversation_id = conversation.get("conversation_id") or "-"
    info(
        tr(
            language,
            "active_chat",
            chat_id=active_chat_id,
            mode=mode,
            title=title,
            conversation_id=conversation_id,
        )
    )


def print_chats(bot: CliChatApp, language: str) -> None:
    chats = bot.list_chats()
    active_chat_id = bot.get_active_chat_id()
    if not chats:
        warning(tr(language, "chat_list_empty"))
        return
    for chat in chats:
        marker = paint("*", UiColors.GREEN, bold=True) if chat["chat_id"] == active_chat_id else " "
        mode = "tmp" if chat["temporary"] else "perm"
        conversation_id = chat["conversation_id"] or "-"
        title = _display_chat_title(chat["title"], language)
        print(f"{marker} {chat['chat_id']} [{mode}] {title} (conversation_id: {conversation_id})")


def print_settings(state: dict[str, Any]) -> None:
    language = normalize_language(state.get("language"))
    info(
        tr(
            language,
            "settings",
            model=state["model"],
            language=language,
            search_hint=state["web_search"],
            effort_hint=state["reasoning_effort"] or "-",
            metrics=state["show_metrics"],
        )
    )


def print_models(bot: CliChatApp, state: dict[str, Any]) -> None:
    models = bot.list_models()
    current_model = state["model"]
    for model_name in models:
        marker = paint("*", UiColors.GREEN, bold=True) if model_name == current_model else " "
        print(f"{marker} {model_name}")
    if current_model not in models:
        warning(tr(normalize_language(state.get("language")), "model_not_listed", model=current_model))



def send_image_prompt(bot: CliChatApp, state: dict[str, Any], command_line: str) -> None:
    language = normalize_language(state.get("language"))
    payload = command_line.split(maxsplit=1)
    if len(payload) < 2:
        warning(tr(language, "img_usage"))
        return
    body = payload[1].strip()
    if "::" in body:
        media_path, prompt = body.split("::", 1)
        prompt = prompt.strip() or "Describe this image briefly."
    else:
        media_path = body
        prompt = "Describe this image briefly."
    media_item = build_media_item(media_path, language)
    bot.chat(
        prompt,
        stream=True,
        model=state["model"],
        web_search=state["web_search"],
        reasoning_effort=state["reasoning_effort"],
        show_metrics=state["show_metrics"],
        media=[media_item],
        stream_prefix=assistant_prefix_text(language),
    )


def handle_command(bot: CliChatApp, state: dict[str, Any], command_line: str) -> bool:
    language = normalize_language(state.get("language"))
    parts = command_line.strip().split()
    if not parts:
        return False
    command = parts[0].lower()
    args = parts[1:]
    if command in {"/exit", "/quit"}:
        return True
    if command == "/help":
        print_help_compact(language)
        return False
    if command == "/models":
        print_models(bot, state)
        return False
    if command == "/clear":
        os.system("cls" if os.name == "nt" else "clear")
        return False
    if command == "/list":
        print_chats(bot, language)
        return False
    if command == "/active":
        print_active(bot, language)
        return False
    if command == "/settings":
        print_settings(state)
        return False
    if command == "/model":
        if not args:
            info(f"model={state['model']}")
            return False
        state["model"] = args[0]
        save_cli_state(state)
        print_settings(state)
        return False
    if command in {"/lang", "/language"}:
        if not args:
            info(f"language={state['language']}")
            return False
        state["language"] = parse_language(args[0])
        save_cli_state(state)
        active_chat = bot.get_active_chat()
        if isinstance(active_chat, dict):
            active_chat["language"] = state["language"]
            bot._save_chats()
        print_settings(state)
        return False
    if command in {"/ws", "/search"}:
        if not args:
            info(f"web_search={state['web_search']}")
            return False
        state["web_search"] = parse_bool(args[0])
        save_cli_state(state)
        print_settings(state)
        info(tr(language, "search_hint_info"))
        return False
    if command in {"/effort", "/think"}:
        if not args:
            info(f"effort={state['reasoning_effort'] or '-'}")
            return False
        state["reasoning_effort"] = parse_reasoning_effort(args[0])
        save_cli_state(state)
        print_settings(state)
        info(tr(language, "effort_hint_info"))
        return False
    if command == "/metrics":
        if not args:
            info(f"metrics={state['show_metrics']}")
            return False
        state["show_metrics"] = parse_bool(args[0])
        save_cli_state(state)
        print_settings(state)
        return False
    if command == "/img":
        send_image_prompt(bot, state, command_line)
        return False
    if command == "/new":
        temporary = False
        title_parts = []
        for token in args:
            lower_token = token.lower()
            if lower_token.startswith("temporary="):
                temporary = parse_bool(token.split("=", 1)[1])
            elif lower_token.startswith("tmp="):
                temporary = parse_bool(token.split("=", 1)[1])
            else:
                title_parts.append(token)
        title = " ".join(title_parts).strip() or None
        chat_id = bot.new_chat(title=title, temporary=temporary)
        active_chat = bot.get_active_chat()
        if isinstance(active_chat, dict):
            active_chat["language"] = state["language"]
            bot._save_chats()
        success(tr(language, "created_chat", chat_id=chat_id, temporary=temporary))
        return False
    if command == "/use":
        if not args:
            warning(tr(language, "usage_use"))
            return False
        bot.switch_chat(args[0])
        active_chat = bot.get_active_chat()
        if isinstance(active_chat, dict):
            active_chat.setdefault("language", state["language"])
            bot._save_chats()
        print_active(bot, language)
        return False
    if command == "/delete":
        target_chat_id = args[0] if args else None
        deleted_chat_id = bot.delete_chat(target_chat_id)
        success(tr(language, "deleted_chat", chat_id=deleted_chat_id))
        if bot.get_active_chat_id() is None:
            warning(tr(language, "no_chats_left"))
        else:
            print_active(bot, language)
        return False
    if command == "/reset":
        reset_chat_id = bot.reset_chat(args[0] if args else None)
        success(tr(language, "reset_chat", chat_id=reset_chat_id))
        print_active(bot, language)
        return False
    if command == "/tmp":
        if not args:
            active_chat = bot.get_active_chat()
            current = bool(active_chat.get("temporary", False)) if active_chat else False
            info(tr(language, "temporary_value", value=current))
            return False
        temporary = parse_bool(args[0])
        bot.set_chat_temporary(temporary)
        success(tr(language, "temporary_value", value=temporary))
        return False
    if command in {"/title", "/rename"}:
        if not args:
            warning(tr(language, "usage_title"))
            return False
        bot.set_chat_title(" ".join(args))
        print_active(bot, language)
        return False
    warning(tr(language, "unknown_command"))
    return False


def main() -> None:
    bot = CliChatApp()
    state = load_cli_state()
    if bot.get_active_chat_id() is None:
        chat_id = bot.new_chat(temporary=False)
        active_chat = bot.get_active_chat()
        if isinstance(active_chat, dict):
            active_chat["language"] = state["language"]
            bot._save_chats()
        success(tr(state["language"], "created_default_chat", chat_id=chat_id))
    print("Warmup...", end=" ", flush=True)
    warmed = bot.transport.warmup()
    print("ok" if warmed else "skip")
    auth_source = bot.transport.auth.api_key_source or "-"
    info(tr(state["language"], "mini_cli"))
    info(tr(state["language"], "auth_source", auth_source=auth_source))
    active_chat = bot.get_active_chat()
    if isinstance(active_chat, dict):
        active_chat["language"] = state["language"]
        if _is_placeholder_title(active_chat.get("title")):
            active_chat["title"] = tr(state["language"], "new_chat_title")
        bot._save_chats()
    print_settings(state)
    print_active(bot, state["language"])
    while True:
        active_chat_id = bot.get_active_chat_id() or "-"
        active_chat = bot.get_active_chat() or {}
        active_language = normalize_language(state["language"])
        temporary_flag = " tmp" if active_chat.get("temporary") else ""
        prompt_text = f"[{active_chat_id} {state['model']} {active_language}{temporary_flag}]> "
        try:
            user_input = input(paint(prompt_text, UiColors.GRAY, dim=True)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        if user_input.startswith("/"):
            try:
                should_exit = handle_command(bot, state, user_input)
            except Exception as exc:
                error(
                    tr(
                        state["language"],
                        "command_error",
                        error_type=type(exc).__name__,
                        error=exc,
                    )
                )
                continue
            if should_exit:
                break
            continue
        try:
            active_chat = bot.get_active_chat()
            if isinstance(active_chat, dict):
                active_chat["language"] = state["language"]
                bot._save_chats()
            bot.chat(
                user_input,
                stream=True,
                model=state["model"],
                web_search=state["web_search"],
                reasoning_effort=state["reasoning_effort"],
                show_metrics=state["show_metrics"],
                stream_prefix=assistant_prefix_text(state["language"]),
            )
        except Exception as exc:
            error(
                tr(
                    state["language"],
                    "request_error",
                    error_type=type(exc).__name__,
                    error=exc,
                )
            )


if __name__ == "__main__":
    main()
