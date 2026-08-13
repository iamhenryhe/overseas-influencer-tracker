from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - GitHub's runner and VPS are Unix-like.
    fcntl = None

from .models import Tweet

LOG = logging.getLogger(__name__)
MAX_SEEN = 5000
MAX_CLAIMS = 5000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def empty_state() -> dict[str, Any]:
    return {
        "version": 2,
        "initialized": False,
        "seen_ids": [],
        "claims": {},
        "last_seen": {},
        "daily_push": {},
    }


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock_path = path.with_name(f".{path.name}.lock")
        self._lock_handle = None

    @contextmanager
    def lock(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+")
        self._lock_handle = handle
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
            self._lock_handle = None

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return empty_state()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"cannot read state file {self.path}: {exc}") from exc
        state = empty_state()
        if isinstance(value, dict):
            state.update(value)
        state.setdefault("seen_ids", [])
        state.setdefault("claims", {})
        state.setdefault("last_seen", {})
        state.setdefault("daily_push", {})
        return state

    def save(self, state: dict[str, Any]) -> None:
        state["updated_at"] = utc_now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    @staticmethod
    def _add_seen(state: dict[str, Any], key: str) -> None:
        seen = state.setdefault("seen_ids", [])
        if key not in seen:
            seen.append(key)
        if len(seen) > MAX_SEEN:
            del seen[:-MAX_SEEN]

    def bootstrap(self, state: dict[str, Any], tweets: list[Tweet]) -> None:
        for tweet in tweets:
            self._add_seen(state, tweet.key)
            previous = state.setdefault("last_seen", {}).get(tweet.author, "")
            if tweet.created_at > previous:
                state["last_seen"][tweet.author] = tweet.created_at
        state["initialized"] = True

    def candidates(self, state: dict[str, Any], tweets: list[Tweet], *, include_old: bool = False) -> list[Tweet]:
        seen = set(state.get("seen_ids", []))
        claims = state.get("claims", {})
        watermarks = state.get("last_seen", {})
        result = []
        for tweet in tweets:
            if tweet.key in seen or tweet.key in claims:
                continue
            if not include_old and watermarks.get(tweet.author) and tweet.created_at <= watermarks[tweet.author]:
                continue
            result.append(tweet)
        return sorted(result, key=lambda item: (item.created_at, item.id))

    def claim(self, state: dict[str, Any], tweets: list[Tweet], recipient_count: int) -> None:
        claims = state.setdefault("claims", {})
        recipient_ids = [f"recipient_{index + 1}" for index in range(recipient_count)]
        for tweet in tweets:
            claims[tweet.key] = {
                "claimed_at": utc_now(),
                "status": "claimed_before_delivery",
                "recipients": {recipient: "pending" for recipient in recipient_ids},
                "sources": tweet.sources,
            }
            self._add_seen(state, tweet.key)
            previous = state.setdefault("last_seen", {}).get(tweet.author, "")
            if tweet.created_at > previous:
                state["last_seen"][tweet.author] = tweet.created_at
        if len(claims) > MAX_CLAIMS:
            oldest = sorted(claims, key=lambda key: claims[key].get("claimed_at", ""))
            for key in oldest[:-MAX_CLAIMS]:
                del claims[key]

    def record_delivery(self, state: dict[str, Any], tweets: list[Tweet], results: dict[str, bool]) -> None:
        for tweet in tweets:
            claim = state.setdefault("claims", {}).setdefault(tweet.key, {})
            claim["status"] = "delivered" if all(results.values()) else "partial_or_failed"
            claim["delivered_at"] = utc_now()
            claim["results"] = results

    @staticmethod
    def push_count(state: dict[str, Any]) -> int:
        daily = state.get("daily_push") or {}
        if daily.get("date") != utc_date():
            return 0
        try:
            return max(0, int(daily.get("count", 0)))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def can_push(cls, state: dict[str, Any], requested: int, limit: int) -> bool:
        return requested > 0 and cls.push_count(state) + requested <= limit

    @staticmethod
    def record_push_attempt(state: dict[str, Any], count: int = 1) -> None:
        daily = state.setdefault("daily_push", {})
        today = utc_date()
        if daily.get("date") != today:
            daily.clear()
            daily["date"] = today
            daily["count"] = 0
        daily["count"] = int(daily.get("count", 0)) + max(0, count)
