from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def _accounts() -> tuple[str, ...]:
    raw = os.getenv("TARGET_ACCOUNTS") or os.getenv("TARGET_ACCOUNT") or "jukan05,aleabitoreddit"
    accounts = tuple(dict.fromkeys(part.strip().lstrip("@").lower() for part in raw.split(",") if part.strip()))
    if not accounts:
        raise ValueError("TARGET_ACCOUNTS cannot be empty")
    return accounts


def _tokens() -> tuple[str, ...]:
    raw = os.getenv("PUSHPLUS_TOKENS") or os.getenv("PUSHPLUS_TOKEN") or ""
    return tuple(dict.fromkeys(token.strip() for token in raw.split(",") if token.strip()))


@dataclass(frozen=True)
class Settings:
    accounts: tuple[str, ...]
    state_file: Path
    aichainmap_feed_url: str
    aichainmap_page_url: str
    x_profile_base_url: str
    x_detail_base_url: str
    pushplus_tokens: tuple[str, ...]
    pushplus_topic: str
    zhipu_api_key: str
    zhipu_api_url: str
    zhipu_model: str
    fetch_x_html: bool
    fetch_x_detail: bool
    fetch_aichainmap: bool
    translate_x: bool
    summarize_x: bool
    require_ai_enrichment: bool
    require_x_full_text: bool
    include_replies: bool
    max_push_per_day: int
    max_digest_items: int
    bootstrap_mode: str
    http_timeout: int
    http_retries: int
    user_agent: str
    dry_run: bool

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            accounts=_accounts(),
            state_file=Path(os.getenv("STATE_FILE", "state.json")),
            aichainmap_feed_url=os.getenv(
                "AICHAINMAP_FEED_URL", "https://serenity-webhook.pages.dev/feed"
            ),
            aichainmap_page_url=os.getenv("AICHAINMAP_PAGE_URL", "https://aichainmap.com/serenity/"),
            x_profile_base_url=os.getenv("X_PROFILE_BASE_URL", "https://x.com"),
            x_detail_base_url=os.getenv("X_DETAIL_BASE_URL", "https://api.fxtwitter.com/status").rstrip("/"),
            pushplus_tokens=_tokens(),
            pushplus_topic=os.getenv("PUSHPLUS_TOPIC", "").strip(),
            zhipu_api_key=os.getenv("ZHIPU_API_KEY", "").strip(),
            zhipu_api_url=os.getenv(
                "ZHIPU_API_URL",
                "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions",
            ).strip(),
            zhipu_model=os.getenv("ZHIPU_MODEL", "glm-5.2").strip() or "glm-5.2",
            fetch_x_html=_bool("FETCH_X_HTML", True),
            fetch_x_detail=_bool("FETCH_X_DETAIL", True),
            fetch_aichainmap=_bool("FETCH_AICHAINMAP", True),
            translate_x=_bool("TRANSLATE_X", True),
            summarize_x=_bool("SUMMARIZE_X", True),
            require_ai_enrichment=_bool("REQUIRE_AI_ENRICHMENT", False),
            require_x_full_text=_bool("REQUIRE_X_FULL_TEXT", False),
            include_replies=_bool("INCLUDE_REPLIES", True),
            max_push_per_day=max(1, _int("MAX_PUSH_PER_DAY", 200)),
            max_digest_items=max(1, _int("MAX_DIGEST_ITEMS", 20)),
            bootstrap_mode=os.getenv("BOOTSTRAP_MODE", "latest").strip().lower() or "latest",
            http_timeout=max(5, _int("HTTP_TIMEOUT", 20)),
            http_retries=max(0, _int("HTTP_RETRIES", 2)),
            user_agent=os.getenv(
                "TRACKER_USER_AGENT",
                "free-public-source-tracker/0.1 (+https://x.com/; no-login-read-only)",
            ),
            dry_run=_bool("DRY_RUN", False),
        )
