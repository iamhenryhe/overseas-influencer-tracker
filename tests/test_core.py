import tempfile
import unittest
from pathlib import Path

from src.content import extract_symbols
from src.fetchers import parse_aichainmap_payload, parse_x_profile
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


if __name__ == "__main__":
    unittest.main()
