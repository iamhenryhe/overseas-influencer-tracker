from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Tweet:
    id: str
    author: str
    created_at: str
    text: str
    url: str
    text_cn: str = ""
    media: list[str] = field(default_factory=list)
    is_reply: bool = False
    is_quote: bool = False
    is_retweet: bool = False
    reply_to: dict[str, Any] | None = None
    quote: dict[str, Any] | None = None
    sources: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.author}:{self.id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "author": self.author,
            "created_at": self.created_at,
            "text": self.text,
            "url": self.url,
            "text_cn": self.text_cn,
            "media": self.media,
            "is_reply": self.is_reply,
            "is_quote": self.is_quote,
            "is_retweet": self.is_retweet,
            "reply_to": self.reply_to,
            "quote": self.quote,
            "sources": self.sources,
        }

