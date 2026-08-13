from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

LOG = logging.getLogger(__name__)
PUSH_URL = "https://www.pushplus.plus/send"


def send_one(token: str, title: str, content: str, *, topic: str = "", retries: int = 2) -> bool:
    payload = {
        "token": token,
        "title": title,
        "content": content,
        "template": "html",
        "channel": "wechat",
    }
    if topic:
        payload["topic"] = topic
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        PUSH_URL,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "free-public-source-tracker/0.1"},
        method="POST",
    )
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                result = json.loads(response.read().decode("utf-8", errors="replace"))
            ok = result.get("code") in (200, "200")
            if not ok:
                LOG.warning("PushPlus rejected message: code=%s msg=%s", result.get("code"), result.get("msg"))
            return ok
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            LOG.warning("PushPlus request failed (attempt %s/%s): %s", attempt + 1, retries + 1, exc)
            if attempt >= retries:
                return False
            time.sleep(1.5**attempt)
    return False


def send_to_all(tokens: tuple[str, ...], title: str, content: str, *, topic: str = "") -> dict[str, bool]:
    results: dict[str, bool] = {}
    for index, token in enumerate(tokens, start=1):
        recipient = f"recipient_{index}"
        results[recipient] = send_one(token, title, content, topic=topic)
        LOG.info("PushPlus %s: %s", recipient, "ok" if results[recipient] else "failed")
    return results

