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
- атомарная запись локального state и `auth_data.json`
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

Сам `main.py` не требует внешних Python-зависимостей, но `auth_fetcher.py` использует `g4f`, `zendriver` и `platformdirs`.

## Получение `auth_data.json`

Быстрый режим для уже авторизованной браузерной сессии:

```cmd
venv\Scripts\python.exe auth_fetcher.py --mode auto
```

Режим ожидания, если нужно сначала войти или зарегистрироваться:

```cmd
venv\Scripts\python.exe auth_fetcher.py --mode wait
```

Опционально можно переопределить одноразовый probe-message, который отправляется для захвата авторизации:

```cmd
venv\Scripts\python.exe auth_fetcher.py --mode auto --probe-prompt "Ping"
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
- `.env` не обязателен. Если он есть, `accessToken` используется как запасной fallback даже при отсутствии `auth_data.json`, но полный `auth_data.json` остаётся самым совместимым вариантом.
- `auth_fetcher.py` отправляет одно probe-сообщение для запуска захвата. По умолчанию это `"Hello"`, но текст можно заменить через `--probe-prompt`.
- Не смешивайте `cookies` и `api_key/accessToken` от разных аккаунтов.
- Локальный state и auth-файлы записываются атомарно, чтобы снизить риск битого JSON при прерывании процесса.
- Если `main.py` сообщает, что не найден `curl`, установите системный `curl.exe` и проверьте `curl --version`.

## Устранение проблем

- Не найден `curl`
  Установите системный `curl.exe` и проверьте, что команда `curl --version` работает в `cmd.exe`.
- Отсутствует `auth_data.json`
  Запустите `venv\Scripts\python.exe auth_fetcher.py --mode wait` и завершите вход в браузере.
- В `auth_fetcher` открывается не тот аккаунт
  В используемом браузерном профиле уже сохранена другая сессия. Выйдите из неё или используйте wait-режим и войдите в нужный аккаунт.
- Сначала всё работало, а потом запросы перестали проходить
  Скорее всего истекли cookies сессии или `api_key`. Сгенерируйте `auth_data.json` заново.
- `main.py` запускается, но не отвечает
  Проверьте, что `auth_data.json` существует, `curl` установлен, а сохранённая браузерная сессия относится к нужному аккаунту.

## Статус

Этот репозиторий теперь можно считать `stable v1`: компактным, практичным и ориентированным на конечного пользователя.

Его scope остаётся прежним: CLI для пользователя и browser auth capture. Дальнейший reusable transport или adapter-слой лучше развивать уже в отдельном репозитории, например `webchat-adapter`, чтобы этот проект не разрастался и оставался простым в поддержке.
