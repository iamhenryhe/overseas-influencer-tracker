from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

LOG = logging.getLogger(__name__)


class FetchError(RuntimeError):
    """A public source could not be read or parsed."""


def get_bytes(url: str, *, user_agent: str, timeout: int, retries: int) -> bytes:
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.8,zh-CN;q=0.6",
        "Accept-Encoding": "identity",
        "Cache-Control": "no-cache",
    }
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", 200)
                body = response.read()
                if status >= 400:
                    raise FetchError(f"GET {url} returned HTTP {status}")
                return body
        except urllib.error.HTTPError as exc:
            last_error = exc
            retryable = exc.code == 429 or 500 <= exc.code < 600
            LOG.warning("GET %s failed with HTTP %s (attempt %s/%s)", url, exc.code, attempt + 1, retries + 1)
            if not retryable or attempt >= retries:
                break
        except (urllib.error.URLError, TimeoutError, OSError, FetchError) as exc:
            last_error = exc
            LOG.warning("GET %s failed: %s (attempt %s/%s)", url, exc, attempt + 1, retries + 1)
            if attempt >= retries:
                break
        time.sleep(min(8, 1.5**attempt))
    raise FetchError(f"GET {url} failed after {retries + 1} attempts: {last_error}")


def get_text(url: str, *, user_agent: str, timeout: int, retries: int) -> str:
    body = get_bytes(url, user_agent=user_agent, timeout=timeout, retries=retries)
    return body.decode("utf-8", errors="replace")


def get_json(url: str, *, user_agent: str, timeout: int, retries: int) -> dict[str, Any]:
    text = get_text(url, user_agent=user_agent, timeout=timeout, retries=retries)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FetchError(f"GET {url} did not return valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise FetchError(f"GET {url} returned {type(value).__name__}, expected object")
    return value

