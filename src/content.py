from __future__ import annotations

import html
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .models import Tweet

CASHTAG_RE = re.compile(r"(?<![A-Za-z0-9_])\$([A-Za-z]{1,6})(?![A-Za-z0-9_])")
PAREN_CODE_RE = re.compile(r"[（(]\s*([0-9]{4})\s*[）)]")
STOP_CASHTAGS = {"USD", "US", "AI", "YOY", "QOQ", "EBITDA", "FCF", "TAM", "ASP", "H1", "H2"}


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


def concise_summary(tweet: Tweet, max_chars: int = 420) -> str:
    source = tweet.text_cn.strip() or tweet.text.strip()
    source = re.sub(r"\s+", " ", source)
    if len(source) <= max_chars:
        return source
    first_paragraph = re.split(r"\n\s*\n", tweet.text_cn.strip() or tweet.text.strip(), maxsplit=1)[0].strip()
    first_paragraph = re.sub(r"\s+", " ", first_paragraph)
    if first_paragraph and len(first_paragraph) <= max_chars:
        return first_paragraph
    return source[: max_chars - 1].rstrip() + "…"


def _times(tweet: Tweet) -> tuple[str, str]:
    try:
        value = datetime.fromisoformat(tweet.created_at.replace("Z", "+00:00"))
        et = value.astimezone(ZoneInfo("America/New_York"))
        cn = value.astimezone(ZoneInfo("Asia/Shanghai"))
        return et.strftime("%m-%d %H:%M ET"), cn.strftime("%m-%d %H:%M 北京")
    except (ValueError, TypeError):
        return tweet.created_at, tweet.created_at


def render_tweet_html(tweet: Tweet) -> tuple[str, str]:
    et, cn = _times(tweet)
    symbols = extract_symbols(tweet)
    title = f"{tweet.author} 新推 · {et}"
    kind = "回复" if tweet.is_reply else "引用" if tweet.is_quote else "原创"
    symbol_text = "、".join(symbols) if symbols else "未识别到明确代码"
    body = (
        f"<p><b>账号：</b>@{html.escape(tweet.author)}　<b>类型：</b>{kind}</p>"
        f"<p><b>时间：</b>{html.escape(et)} / {html.escape(cn)}</p>"
        f"<p><b>观点：</b>{html.escape(concise_summary(tweet)).replace(chr(10), '<br>')}</p>"
        f"<p><b>标的：</b>{html.escape(symbol_text)}</p>"
        f"<p><a href=\"{html.escape(tweet.url, quote=True)}\">在 X 打开原文</a></p>"
        f"<p><small>来源：{html.escape(', '.join(tweet.sources))} · NFA（非投资建议）</small></p>"
    )
    return title, body


def render_digest_html(tweets: list[Tweet]) -> tuple[str, str]:
    title = f"大V追踪摘要 · {len(tweets)} 条"
    items = []
    for tweet in tweets:
        symbols = "、".join(extract_symbols(tweet)) or "—"
        items.append(
            "<li>"
            f"<b>@{html.escape(tweet.author)}</b>　{html.escape(_times(tweet)[1])}　"
            f"<b>{html.escape(symbols)}</b>　{html.escape(concise_summary(tweet, 220))}　"
            f"<a href=\"{html.escape(tweet.url, quote=True)}\">原文</a>"
            "</li>"
        )
    body = "<p>检测到多条新信息，已合并推送：</p><ol>" + "".join(items) + "</ol><p><small>NFA（非投资建议）</small></p>"
    return title, body

