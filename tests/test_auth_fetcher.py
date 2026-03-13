from __future__ import annotations

import json
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
