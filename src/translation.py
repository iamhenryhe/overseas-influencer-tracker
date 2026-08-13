from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from .config import Settings
from .models import Tweet

LOG = logging.getLogger(__name__)
ZHIPU_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"


def _content_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "".join(parts).strip()
    return ""


def translate_one(text: str, settings: Settings) -> str:
    if not settings.zhipu_api_key or not text.strip():
        return ""
    payload = {
        "model": settings.zhipu_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是金融与科技领域的专业翻译。把用户给出的英文 X 帖子完整翻译成自然、准确的简体中文。"
                    "只输出译文，不要解释，不要总结，不要添加引号或前缀。保留股票代码、公司名、数字、"
                    "URL、换行和原文语气；不要臆测原文没有表达的观点。若原文以省略号结尾，保留省略号，"
                    "只翻译可见部分，不要试图补全不可见内容。"
                ),
            },
            {"role": "user", "content": text},
        ],
        "temperature": 0.2,
        "stream": False,
    }
    request = urllib.request.Request(
        ZHIPU_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.zhipu_api_key}",
            "Content-Type": "application/json",
            "User-Agent": "free-public-source-tracker/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.http_timeout) as response:
            result = json.loads(response.read().decode("utf-8", errors="replace"))
        choices = result.get("choices") if isinstance(result, dict) else None
        if not isinstance(choices, list) or not choices:
            LOG.warning("Zhipu returned no choices")
            return ""
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        translated = _content_text(message.get("content") if isinstance(message, dict) else "")
        return translated
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        LOG.warning("Zhipu translation failed: %s", exc)
        return ""


def translate_candidates(tweets: list[Tweet], settings: Settings) -> None:
    """Translate only notifications that will actually be sent, never the whole feed."""

    if not settings.translate_x or not settings.zhipu_api_key:
        return
    for tweet in tweets:
        if tweet.text_cn or not tweet.text.strip():
            continue
        translated = translate_one(tweet.text, settings)
        if translated:
            tweet.text_cn = translated
            tweet.translation_source = f"zhipu:{settings.zhipu_model}"
