# webchat-openai-cli

English version. Russian version: [README.ru.md](README.ru.md)

Minimal ChatGPT-style CLI for `chatgpt.com` that works on your own account.

The project is split into two practical parts:

- `main.py` - the standalone CLI chat with history, streaming, metrics, image prompts, and localization.
- `auth_fetcher.py` - browser-based `auth_data.json` capture for a real ChatGPT web session.

## Features

- streaming replies in the terminal
- latency metrics: `first_token`, `last_token`, `total`
- single local state file: `webchat_state.json`
- image prompts through `/img`
- `auto` and `wait` auth capture modes
- English and Russian CLI localization
- `main.py` runs without extra Python packages

## Requirements

- Windows
- Python 3.13+
- system `curl` available in `PATH`
- Chrome or Chromium for `auth_fetcher.py`

## Installation

Create and activate a virtual environment in `cmd.exe`:

```cmd
python -m venv venv
venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`main.py` itself does not require external Python packages, but `auth_fetcher.py` uses `g4f` and `nodriver`.

## Get `auth_data.json`

Fast mode for an already logged-in browser session:

```cmd
venv\Scripts\python.exe auth_fetcher.py --mode auto
```

Wait mode if you need time to log in or register first:

```cmd
venv\Scripts\python.exe auth_fetcher.py --mode wait
```

Short alias for wait mode:

```cmd
venv\Scripts\python.exe auth_fetcher_wait.py
```

After a successful capture, `auth_data.json` will appear in the project directory.

## Run the CLI

```cmd
python main.py
```

Or from the virtual environment:

```cmd
venv\Scripts\python.exe main.py
```

## Useful Commands

- `/help`
- `/models`
- `/new`
- `/list`
- `/use <chat_id>`
- `/reset`
- `/img <path_or_url> :: <prompt>`
- `/settings`
- `/model <name>`
- `/lang <en|ru>`
- `/ws <true|false>`
- `/effort <standard|extended|off>`
- `/metrics <true|false>`

## Important Files

- `auth_data.json` - local auth data, do not commit it
- `webchat_state.json` - local chat history and runtime settings, do not commit it

## Notes

- `auth_data.json` is the primary auth source.
- `.env` is optional. If present, `accessToken` is used only as a fallback.
- Do not mix `cookies` and `api_key/accessToken` from different accounts.
- If `main.py` says that `curl` is missing, install system `curl.exe` and check `curl --version`.

## Status

This repository is considered `v1`: compact, practical, and user-oriented. The app is intentionally kept simple for end users, even though some internals could be split into modules later.
