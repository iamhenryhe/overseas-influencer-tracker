import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.content import extract_symbols, render_tweet_html
from src.fetchers import (
    fetch_sources,
    hydrate_x_details,
    parse_aichainmap_payload,
    parse_fxtwitter_payload,
    parse_x_profile,
)
from src.http_client import FetchError
from src.models import Tweet
from src.state import StateStore, empty_state


class TrackerTests(unittest.TestCase):
    def test_parse_aichainmap_payload_and_symbols(self):
        tweets = parse_aichainmap_payload(
            {
                "tweets": [
                    {
                        "id": "123",
                        "url": "https://x.com/aleabitoreddit/status/123",
                        "posted_at": "2026-08-12T08:00:00Z",
                        "text": "$SIVE and Taiyo Yuden (6976)",
                        "text_cn": "$SIVE 与太阳诱电（6976）",
                        "is_reply": False,
                        "media": [],
                    }
                ]
            },
            source="test",
        )
        self.assertEqual(len(tweets), 1)
        self.assertEqual(tweets[0].author, "aleabitoreddit")
        self.assertEqual(extract_symbols(tweets[0]), ["$SIVE", "6976"])


    def test_parse_x_schema_profile(self):
        page = """
        <ul><li><div data-href="/jukan05/status/456">
          <article itemType="https://schema.org/SocialMediaPosting">
            <meta itemProp="identifier" content="456"/>
            <meta itemProp="datePublished" content="2026-08-12T08:00:00.000Z"/>
            <meta itemProp="url" content="https://x.com/jukan05/status/456"/>
            <meta itemProp="articleBody" content="BY SHIPMENT VOLUME, YMTC SURPASSED MICRON."/>
            <div itemProp="author"><meta itemProp="alternateName" content="jukan05"/></div>
          </article>
        </div></li></ul>
        """
        tweets = parse_x_profile(page, "jukan05")
        self.assertEqual(len(tweets), 1)
        self.assertEqual(tweets[0].id, "456")
        self.assertTrue(tweets[0].text.startswith("BY SHIPMENT"))


    def test_state_bootstrap_candidates_and_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "state.json")
            state = empty_state()
            old = Tweet("1", "jukan05", "2026-08-12T07:00:00Z", "old", "https://x.com/jukan05/status/1")
            new = Tweet("2", "jukan05", "2026-08-12T08:00:00Z", "new", "https://x.com/jukan05/status/2")
            store.bootstrap(state, [old])
            candidates = store.candidates(state, [old, new])
            self.assertEqual([tweet.id for tweet in candidates], ["2"])
            store.claim(state, candidates, 1)
            self.assertEqual(store.candidates(state, [old, new]), [])
            self.assertTrue(store.can_push(state, 1, 200))
            store.record_push_attempt(state)
            self.assertEqual(store.push_count(state), 1)

    def test_x_full_text_and_quote_metadata(self):
        page = """
        <article itemType="https://schema.org/SocialMediaPosting">
          <meta itemProp="identifier" content="456"/>
          <meta itemProp="datePublished" content="Thu Aug 13 01:21:18 +0000 2026"/>
          <meta itemProp="url" content="https://x.com/jukan05/status/456"/>
          <meta itemProp="articleBody" content="Full display text https://t.co/example"/>
          <meta itemProp="text" content="Full display text"/>
          <meta itemProp="isBasedOn" content="https://x.com/source/status/789"/>
          <div itemProp="author"><meta itemProp="alternateName" content="jukan05"/></div>
        </article>
        """
        tweet = parse_x_profile(page, "jukan05")[0]
        self.assertEqual(tweet.published_at, "2026-08-13T01:21:18Z")
        self.assertEqual(tweet.text, "Full display text")
        self.assertTrue(tweet.is_quote)
        self.assertEqual(tweet.quote["url"], "https://x.com/source/status/789")

    def test_fxtwitter_detail_parser(self):
        tweet = parse_fxtwitter_payload(
            {
                "tweet": {
                    "id": "789",
                    "url": "https://x.com/aleabitoreddit/status/789",
                    "text": "A complete post",
                    "created_at": "Thu Aug 13 01:21:18 +0000 2026",
                    "replying_to": None,
                    "quote": None,
                    "media": {"all": []},
                }
            },
            author="aleabitoreddit",
        )
        self.assertIsNotNone(tweet)
        self.assertEqual(tweet.published_at, "2026-08-13T01:21:18Z")
        self.assertEqual(tweet.content_status, "complete")

    def test_long_anonymous_x_preview_is_hydrated_by_fxtwitter(self):
        preview = "P" * 277
        full_text = preview + " full Note Tweet text"
        page = f"""
        <article itemType="https://schema.org/SocialMediaPosting">
          <meta itemProp="identifier" content="long1"/>
          <meta itemProp="datePublished" content="2026-08-13T01:21:18Z"/>
          <meta itemProp="url" content="https://x.com/jukan05/status/long1"/>
          <meta itemProp="text" content="{preview}"/>
          <div itemProp="author"><meta itemProp="alternateName" content="jukan05"/></div>
        </article>
        """
        settings = self._source_settings()
        settings.accounts = ("jukan05",)
        settings.fetch_x_detail = True
        with patch("src.fetchers.get_text", return_value=page), patch("src.fetchers.get_json") as get_json:
            tweets, _ = fetch_sources(settings)
            get_json.assert_not_called()
            get_json.return_value = {
                "tweet": {
                    "id": "long1",
                    "url": "https://x.com/jukan05/status/long1",
                    "text": full_text,
                    "created_at": "Thu Aug 13 01:21:18 +0000 2026",
                    "replying_to": None,
                    "quote": None,
                    "media": {"all": []},
                }
            }
            self.assertEqual(tweets[0].content_status, "truncated")
            hydrated = hydrate_x_details(tweets, settings)

        self.assertEqual(hydrated[0].text, full_text)
        self.assertEqual(hydrated[0].content_status, "complete")
        self.assertIn("x_detail:fxtwitter", hydrated[0].sources)

    def test_push_message_format(self):
        tweet = Tweet(
            "123",
            "aleabitoreddit",
            "2026-08-12T23:08:56Z",
            "A new post",
            "https://x.com/aleabitoreddit/status/123",
            text_cn="一条新推文",
            is_reply=True,
            sources=["aichainmap_feed"],
        )
        title, body = render_tweet_html(tweet)
        self.assertEqual(title, "serenity 新推文")
        self.assertLess(body.index("总结"), body.index("账号"))
        self.assertIn("<b>账号：</b>serenity", body)
        self.assertIn("<b>发布时间：</b>2026-08-13 07:08:56", body)
        self.assertIn("<b>总结：</b>暂未生成", body)
        self.assertIn("font-size:20px", body)
        self.assertNotIn("类型", body)
        self.assertNotIn("来源", body)
        self.assertNotIn("标的", body)
        self.assertNotIn("ET", body)

    def test_push_message_contains_glm_summary(self):
        tweet = Tweet(
            "124",
            "jukan05",
            "2026-08-12T23:08:56Z",
            "A new post",
            "https://x.com/jukan05/status/124",
            summary_cn="核心观点是光模块需求仍然强劲。",
        )
        title, body = render_tweet_html(tweet)
        self.assertEqual(title, "jukan 新推文")
        self.assertLess(body.index("总结"), body.index("账号"))
        self.assertIn("<b>账号：</b>jukan", body)
        self.assertIn("<b>总结：</b>核心观点是光模块需求仍然强劲。", body)

    @staticmethod
    def _source_settings():
        return SimpleNamespace(
            accounts=("aleabitoreddit",),
            fetch_x_html=True,
            fetch_x_detail=False,
            fetch_aichainmap=True,
            x_profile_base_url="https://x.com",
            x_detail_base_url="https://api.fxtwitter.com/status",
            aichainmap_feed_url="https://serenity-webhook.pages.dev/feed",
            aichainmap_page_url="https://aichainmap.com/serenity/",
            user_agent="test",
            http_timeout=5,
            http_retries=0,
        )

    def test_x_primary_skips_aichainmap(self):
        page = """
        <article itemType="https://schema.org/SocialMediaPosting">
          <meta itemProp="identifier" content="x1"/>
          <meta itemProp="datePublished" content="2026-08-13T01:21:18Z"/>
          <meta itemProp="url" content="https://x.com/aleabitoreddit/status/x1"/>
          <meta itemProp="text" content="X primary post"/>
          <div itemProp="author"><meta itemProp="alternateName" content="aleabitoreddit"/></div>
        </article>
        """
        with patch("src.fetchers.get_text", return_value=page), patch("src.fetchers.get_json") as get_json:
            tweets, diagnostics = fetch_sources(self._source_settings())
        self.assertEqual([tweet.id for tweet in tweets], ["x1"])
        self.assertEqual(diagnostics["aichainmap"], "skipped:x_primary_ok")
        get_json.assert_not_called()

    def test_aichainmap_is_used_when_x_is_unavailable(self):
        payload = {
            "tweets": [
                {
                    "id": "backup1",
                    "url": "https://x.com/aleabitoreddit/status/backup1",
                    "posted_at": "2026-08-13T01:21:18Z",
                    "text": "Backup post",
                }
            ]
        }
        with patch("src.fetchers.get_text", side_effect=FetchError("X blocked")), patch(
            "src.fetchers.get_json", return_value=payload
        ):
            tweets, diagnostics = fetch_sources(self._source_settings())
        self.assertEqual([tweet.id for tweet in tweets], ["backup1"])
        self.assertTrue(diagnostics["aichainmap_feed"].startswith("fallback_ok:"))


if __name__ == "__main__":
    unittest.main()
