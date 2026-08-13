from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

from .config import Settings
from .models import Tweet

LOG = logging.getLogger(__name__)


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


def _error_body(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace").strip()
    except OSError:
        return ""
    if not body:
        return ""
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        return body[:500]
    if isinstance(value, dict):
        error = value.get("error")
        if isinstance(error, dict):
            code = error.get("code", "")
            message = error.get("message", "")
            return f"code={code} message={message}".strip()
        message = value.get("message")
        if message:
            return str(message)[:500]
    return body[:500]


def _chat(
    messages: list[dict[str, str]],
    settings: Settings,
    *,
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> str:
    if not settings.zhipu_api_key:
        LOG.error("Zhipu API key is missing")
        return ""
    payload = {
        "model": settings.zhipu_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    request = urllib.request.Request(
        settings.zhipu_api_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.zhipu_api_key}",
            "Content-Type": "application/json",
            "User-Agent": "free-public-source-tracker/0.1",
        },
        method="POST",
    )
    attempts = max(1, settings.http_retries + 1)
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=settings.http_timeout) as response:
                result = json.loads(response.read().decode("utf-8", errors="replace"))
            if not isinstance(result, dict):
                LOG.error("Zhipu returned an unexpected response type: %s", type(result).__name__)
                return ""
            if isinstance(result.get("error"), dict):
                error = result["error"]
                LOG.warning(
                    "Zhipu API returned an error: code=%s message=%s",
                    error.get("code", ""),
                    error.get("message", ""),
                )
                return ""
            choices = result.get("choices")
            if not isinstance(choices, list) or not choices:
                LOG.warning("Zhipu returned no choices: request_id=%s", result.get("request_id", ""))
                return ""
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            content = _content_text(message.get("content") if isinstance(message, dict) else "")
            if not content:
                LOG.warning(
                    "Zhipu returned empty content: request_id=%s finish_reason=%s",
                    result.get("request_id", ""),
                    choices[0].get("finish_reason", "") if isinstance(choices[0], dict) else "",
                )
            return content
        except urllib.error.HTTPError as exc:
            detail = _error_body(exc)
            retryable = exc.code == 429 or 500 <= exc.code < 600
            LOG.warning(
                "Zhipu HTTP error status=%s retryable=%s attempt=%s/%s detail=%s",
                exc.code,
                retryable,
                attempt,
                attempts,
                detail or str(exc),
            )
            if not retryable or attempt >= attempts:
                return ""
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            LOG.warning("Zhipu request failed attempt=%s/%s: %s", attempt, attempts, exc)
            if attempt >= attempts:
                return ""
        time.sleep(min(8, 1.5 ** (attempt - 1)))
    return ""


def translate_one(text: str, settings: Settings) -> str:
    if not text.strip():
        return ""
    return _chat(
        [
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
        settings,
        max_tokens=2048,
    )


def summarize_one(text: str, settings: Settings) -> str:
    if not text.strip():
        return ""
    return _chat(
        [
            {
                "role": "system",
                "content": (
                    "你是 AI、半导体和股票研究助理。请把这条 X 帖子概括成简洁的中文总结，面向投资者阅读。"
                    "只输出 1 到 3 句总结，不要使用‘总结：’前缀，不要评价或添加原文没有的信息。"
                    "优先保留核心主题、关键事实或观点，以及涉及的公司名和股票代码；如果是回复，说明回答了什么问题。"
                ),
            },
            {"role": "user", "content": text},
        ],
        settings,
        max_tokens=512,
    )


def translate_candidates(tweets: list[Tweet], settings: Settings) -> bool:
    """Translate only notifications that will actually be sent, never the whole feed."""

    if not settings.translate_x:
        return True
    if not settings.zhipu_api_key:
        LOG.error("Translation is enabled but Zhipu API key is missing")
        return False
    success = True
    for tweet in tweets:
        if tweet.text_cn or not tweet.text.strip():
            continue
        translated = translate_one(tweet.text, settings)
        if translated:
            tweet.text_cn = translated
            tweet.translation_source = f"zhipu:{settings.zhipu_model}"
        else:
            LOG.error("Translation failed for %s; it will not be sent yet", tweet.key)
            success = False
    return success


def summarize_candidates(tweets: list[Tweet], settings: Settings) -> bool:
    """Generate summaries only for notifications that will actually be sent."""

    if not settings.summarize_x:
        return True
    if not settings.zhipu_api_key:
        LOG.error("Summarization is enabled but Zhipu API key is missing")
        return False
    success = True
    for tweet in tweets:
        if tweet.summary_cn:
            continue
        source = tweet.text_cn.strip() or tweet.text.strip()
        summary = summarize_one(source, settings)
        if summary:
            tweet.summary_cn = summary
        else:
            LOG.error("Summarization failed for %s; it will not be sent yet", tweet.key)
            success = False
    return success


def enrich_candidates(tweets: list[Tweet], settings: Settings) -> bool:
    """Translate missing X text, then summarize each outgoing notification."""

    translated = translate_candidates(tweets, settings)
    summarized = summarize_candidates(tweets, settings)
    return translated and summarized
