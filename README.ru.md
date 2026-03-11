# webchat-openai-cli

Русская версия. English version: [README.md](README.md)

Минималистичный CLI в стиле ChatGPT для `chatgpt.com`, который работает на вашем собственном аккаунте.

Проект состоит из двух практических частей:

- `main.py` - самостоятельный CLI-чат с историей, стримингом, метриками, поддержкой изображений и локализацией.
- `auth_fetcher.py` - получение `auth_data.json` через реальную браузерную сессию ChatGPT.

## Возможности

- потоковый вывод ответа в терминал
- метрики задержки: `first_token`, `last_token`, `total`
- единый локальный state-файл: `webchat_state.json`
- запросы с изображениями через `/img`
- режимы авторизации `auto` и `wait`
- локализация CLI на английский и русский
- `main.py` запускается без внешних Python-библиотек

## Требования

- Windows
- Python 3.13+
- системный `curl` в `PATH`
- Chrome или Chromium для `auth_fetcher.py`

## Установка

Создать и активировать виртуальное окружение в `cmd.exe`:

```cmd
python -m venv venv
venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Сам `main.py` не требует внешних Python-зависимостей, но `auth_fetcher.py` использует `g4f` и `nodriver`.

## Получение `auth_data.json`

Быстрый режим для уже авторизованной браузерной сессии:

```cmd
venv\Scripts\python.exe auth_fetcher.py --mode auto
```

Режим ожидания, если нужно сначала войти или зарегистрироваться:

```cmd
venv\Scripts\python.exe auth_fetcher.py --mode wait
```

Короткий запуск wait-режима:

```cmd
venv\Scripts\python.exe auth_fetcher_wait.py
```

После успешного захвата рядом появится `auth_data.json`.

## Запуск CLI

```cmd
python main.py
```

Или через виртуальное окружение:

```cmd
venv\Scripts\python.exe main.py
```

## Полезные команды

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

## Важные файлы

- `auth_data.json` - локальные данные авторизации, не коммитить
- `webchat_state.json` - локальная история чатов и runtime-настройки, не коммитить

## Замечания

- `auth_data.json` является основным источником авторизации.
- `.env` не обязателен. Если он есть, `accessToken` используется только как запасной fallback.
- Не смешивайте `cookies` и `api_key/accessToken` от разных аккаунтов.
- Если `main.py` сообщает, что не найден `curl`, установите системный `curl.exe` и проверьте `curl --version`.

## Статус

Этот репозиторий уже можно считать `v1`: компактным, практичным и ориентированным на конечного пользователя. Внутренности при желании позже можно разнести по модулям, не меняя внешний UX.
