from __future__ import annotations

import html
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .models import Tweet

CASHTAG_RE = re.compile(r"(?<![A-Za-z0-9_])\$([A-Za-z]{1,6})(?![A-Za-z0-9_])")
PAREN_CODE_RE = re.compile(r"[（(]\s*([0-9]{4})\s*[）)]")
STOP_CASHTAGS = {"USD", "US", "AI", "YOY", "QOQ", "EBITDA", "FCF", "TAM", "ASP", "H1", "H2"}
DISPLAY_AUTHORS = {
    "aleabitoreddit": "serenity",
    "jukan05": "jukan",
}


def extract_symbols(tweet: Tweet) -> list[str]:
    text = f"{tweet.text}\n{tweet.text_cn}"
    symbols: list[str] = []
    for match in CASHTAG_RE.finditer(text):
        symbol = f"${match.group(1).upper()}"
        if symbol[1:] not in STOP_CASHTAGS and symbol not in symbols:
            symbols.append(symbol)
    for match in PAREN_CODE_RE.finditer(text):
        code = match.group(1)
        if not code.startswith(("19", "20")) and code not in symbols:
            symbols.append(code)
    return symbols


def concise_summary(tweet: Tweet, max_chars: int | None = None) -> str:
    """Return the full available text; max_chars remains for API compatibility."""
    source = tweet.text_cn.strip() or tweet.text.strip()
    source = re.sub(r"\s+", " ", source)
    return source


def _times(tweet: Tweet) -> tuple[str, str]:
    try:
        value = datetime.fromisoformat(tweet.published_at.replace("Z", "+00:00"))
        et = value.astimezone(ZoneInfo("America/New_York"))
        cn = value.astimezone(ZoneInfo("Asia/Shanghai"))
        return et.strftime("%m-%d %H:%M ET"), cn.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return tweet.published_at, tweet.published_at


def display_author(author: str) -> str:
    return DISPLAY_AUTHORS.get(author.lower().lstrip("@"), author.lower().lstrip("@"))


def render_tweet_html(tweet: Tweet) -> tuple[str, str]:
    _, cn = _times(tweet)
    account = display_author(tweet.author)
    title = f"{account} 新推文"
    status = ""
    if tweet.content_status != "complete":
        status = (
            f"<p><b>正文状态：</b>公开页面只返回了截断预览（{html.escape(tweet.truncation_reason or '未知原因')}）；"
            "请点击原文查看完整内容。</p>"
        )
    translation = ""
    if tweet.text_cn:
        label = "中文翻译（截断预览）" if tweet.content_status != "complete" else "中文翻译"
        translation = f"<p><b>{label}：</b>{html.escape(tweet.text_cn).replace(chr(10), '<br>')}</p>"
    summary = (
        '<div style="font-size:20px;line-height:1.8;margin:0 0 18px;">'
        f"<b>总结：</b>{html.escape(tweet.summary_cn or '暂未生成')}"
        "</div>"
    )
    body = (
        f"{summary}"
        f"<p><b>账号：</b>{html.escape(account)}</p>"
        f"<p><b>发布时间：</b>{html.escape(cn)}</p>"
        f"<p><b>原文：</b>{html.escape(tweet.text).replace(chr(10), '<br>')}</p>"
        f"{translation}"
        f"{status}"
        f"<p><a href=\"{html.escape(tweet.url, quote=True)}\">在 X 打开原文</a></p>"
    )
    return title, body


def render_digest_html(tweets: list[Tweet]) -> tuple[str, str]:
    title = f"大V追踪摘要 · {len(tweets)} 条"
    items = []
    for tweet in tweets:
        items.append(
            "<li>"
            f"<div style=\"font-size:20px;line-height:1.8;\"><b>总结：</b>{html.escape(tweet.summary_cn or '暂未生成')}</div>"
            f"<b>{html.escape(display_author(tweet.author))}</b>　{html.escape(_times(tweet)[1])}　"
            f"{html.escape(concise_summary(tweet, 220))}　"
            f"<a href=\"{html.escape(tweet.url, quote=True)}\">原文</a>"
            "</li>"
        )
    body = "<p>检测到多条新信息，已合并推送：</p><ol>" + "".join(items) + "</ol><p><small>NFA（非投资建议）</small></p>"
    return title, body
