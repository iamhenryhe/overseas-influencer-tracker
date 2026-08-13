from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Iterable

from .config import Settings
from .http_client import FetchError, get_json, get_text
from .models import Tweet

LOG = logging.getLogger(__name__)


def clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    for _ in range(3):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def normalize_timestamp(value: Any) -> str:
    raw = clean_text(value)
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _list_urls(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("url")
        if value and str(value) not in result:
            result.append(str(value))
    return result


def from_raw(raw: dict[str, Any], *, author: str, source: str) -> Tweet | None:
    tweet_id = clean_text(raw.get("id"))
    text = clean_text(raw.get("text") or raw.get("articleBody") or raw.get("text_cn"))
    url = clean_text(raw.get("url"))
    if not tweet_id or not text or not url:
        return None
    return Tweet(
        id=tweet_id,
        author=author.lower().lstrip("@"),
        created_at=normalize_timestamp(raw.get("posted_at") or raw.get("created_at") or raw.get("datePublished")),
        text=text,
        url=url,
        text_cn=clean_text(raw.get("text_cn")),
        media=_list_urls(raw.get("media")),
        is_reply=bool(raw.get("is_reply")),
        is_quote=bool(raw.get("is_quote")),
        is_retweet=bool(raw.get("is_retweet")),
        reply_to=raw.get("reply_to") if isinstance(raw.get("reply_to"), dict) else None,
        quote=raw.get("quote") if isinstance(raw.get("quote"), dict) else None,
        sources=[source],
    )


class _ArticleParser(HTMLParser):
    """Extract Schema.org SocialMediaPosting metadata from public X HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.article_stack: list[dict[str, list[str]] | None] = []
        self.contexts: list[dict[str, list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "article":
            item_type = attr.get("itemtype", "").lower()
            if "socialmediaposting" in item_type:
                self.article_stack.append({})
            else:
                self.article_stack.append(None)
            return
        if tag.lower() == "meta" and self.article_stack and self.article_stack[-1] is not None:
            prop = attr.get("itemprop", "").lower()
            content = attr.get("content", "")
            if prop:
                self.article_stack[-1].setdefault(prop, []).append(clean_text(content))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "article" and self.article_stack:
            context = self.article_stack.pop()
            if context is not None:
                self.contexts.append(context)


def _first(context: dict[str, list[str]], prop: str) -> str:
    values = context.get(prop, [])
    return values[0] if values else ""


def parse_x_profile(text: str, handle: str, *, source: str = "x_html") -> list[Tweet]:
    parser = _ArticleParser()
    parser.feed(text)
    target = handle.lower().lstrip("@")
    tweets: list[Tweet] = []
    for context in parser.contexts:
        tweet_url = _first(context, "url")
        author_names = {value.lower().lstrip("@") for value in context.get("alternatename", [])}
        if target not in author_names and f"/{target}/status/" not in tweet_url.lower():
            continue
        raw = {
            "id": _first(context, "identifier"),
            "created_at": _first(context, "datepublished") or _first(context, "datecreated"),
            "text": _first(context, "articlebody") or _first(context, "text"),
            "url": tweet_url,
            "media": [value for value in context.get("contenturl", []) if "pbs.twimg.com" in value],
        }
        tweet = from_raw(raw, author=target, source=source)
        if tweet:
            tweets.append(tweet)
    return _dedupe_tweets(tweets)


def _decode_live_array(page: str) -> list[dict[str, Any]]:
    marker = "window.__LIVE0__"
    start = page.find(marker)
    if start < 0:
        return []
    equals = page.find("=", start + len(marker))
    if equals < 0:
        return []
    payload = page[equals + 1 :].lstrip()
    try:
        value, _ = json.JSONDecoder().raw_decode(payload)
    except json.JSONDecodeError as exc:
        raise FetchError(f"aichainmap page live payload is invalid: {exc}") from exc
    return value if isinstance(value, list) else []


def parse_aichainmap_payload(payload: dict[str, Any], *, source: str) -> list[Tweet]:
    tweets: list[Tweet] = []
    for raw in payload.get("tweets", []):
        if not isinstance(raw, dict):
            continue
        tweet = from_raw(raw, author="aleabitoreddit", source=source)
        if tweet:
            tweets.append(tweet)
    return _dedupe_tweets(tweets)


def parse_aichainmap_page(page: str, *, source: str = "aichainmap_page") -> list[Tweet]:
    tweets: list[Tweet] = []
    for raw in _decode_live_array(page):
        if isinstance(raw, dict):
            tweet = from_raw(raw, author="aleabitoreddit", source=source)
            if tweet:
                tweets.append(tweet)
    return _dedupe_tweets(tweets)


def _dedupe_tweets(tweets: Iterable[Tweet]) -> list[Tweet]:
    result: dict[str, Tweet] = {}
    for tweet in tweets:
        existing = result.get(tweet.key)
        if existing is None:
            result[tweet.key] = tweet
            continue
        existing.sources = sorted(set(existing.sources + tweet.sources))
        if not existing.text_cn and tweet.text_cn:
            existing.text_cn = tweet.text_cn
        existing.media = list(dict.fromkeys(existing.media + tweet.media))
    return sorted(result.values(), key=lambda item: (item.created_at, item.id), reverse=True)


def merge_tweets(tweets: Iterable[Tweet]) -> list[Tweet]:
    return _dedupe_tweets(tweets)


def fetch_sources(settings: Settings) -> tuple[list[Tweet], dict[str, str]]:
    all_tweets: list[Tweet] = []
    diagnostics: dict[str, str] = {}

    if settings.fetch_aichainmap and "aleabitoreddit" in settings.accounts:
        try:
            payload = get_json(
                settings.aichainmap_feed_url,
                user_agent=settings.user_agent,
                timeout=settings.http_timeout,
                retries=settings.http_retries,
            )
            feed_tweets = parse_aichainmap_payload(payload, source="aichainmap_feed")
            all_tweets.extend(feed_tweets)
            diagnostics["aichainmap_feed"] = f"ok:{len(feed_tweets)}"
        except FetchError as exc:
            diagnostics["aichainmap_feed"] = f"error:{exc}"
            LOG.warning("aichainmap feed unavailable: %s", exc)
            try:
                page = get_text(
                    settings.aichainmap_page_url,
                    user_agent=settings.user_agent,
                    timeout=settings.http_timeout,
                    retries=settings.http_retries,
                )
                page_tweets = parse_aichainmap_page(page)
                all_tweets.extend(page_tweets)
                diagnostics["aichainmap_page"] = f"ok:{len(page_tweets)}"
            except FetchError as page_exc:
                diagnostics["aichainmap_page"] = f"error:{page_exc}"
                LOG.warning("aichainmap page fallback unavailable: %s", page_exc)

    if settings.fetch_x_html:
        for account in settings.accounts:
            url = f"{settings.x_profile_base_url.rstrip('/')}/{account}?lang=en"
            try:
                page = get_text(
                    url,
                    user_agent=settings.user_agent,
                    timeout=settings.http_timeout,
                    retries=settings.http_retries,
                )
                account_tweets = parse_x_profile(page, account)
                all_tweets.extend(account_tweets)
                diagnostics[f"x_html:{account}"] = f"ok:{len(account_tweets)}"
            except FetchError as exc:
                diagnostics[f"x_html:{account}"] = f"error:{exc}"
                LOG.warning("X public profile unavailable for %s: %s", account, exc)

    merged = merge_tweets(all_tweets)
    if not merged and diagnostics:
        raise FetchError(f"all enabled sources returned no tweets: {diagnostics}")
    return merged, diagnostics

