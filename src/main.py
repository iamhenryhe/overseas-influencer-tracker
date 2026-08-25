from __future__ import annotations

import argparse
import logging
import sys

from .config import Settings
from .content import render_digest_html, render_tweet_html
from .fetchers import fetch_sources, hydrate_x_details
from .http_client import FetchError
from .push import send_to_all
from .state import StateStore
from .translation import enrich_candidates

LOG = logging.getLogger("tracker")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Track public posts from Jukan05 and Serenity for free")
    parser.add_argument("--dry-run", action="store_true", help="print new items without sending or changing state")
    parser.add_argument(
        "--bootstrap-mode",
        choices=("latest", "push_latest", "backfill"),
        default=None,
        help="first run behavior: baseline silently, push one latest post per account, or push fetched history",
    )
    parser.add_argument("--limit", type=int, default=0, help="limit candidate count; useful for a first test")
    parser.add_argument("--include-old", action="store_true", help="allow candidates older than the watermark")
    return parser


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _print_diagnostics(diagnostics: dict[str, str], total: int) -> None:
    LOG.info("sources=%s merged_tweets=%s", diagnostics, total)


def run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    dry_run = args.dry_run or settings.dry_run
    if not dry_run and not settings.pushplus_tokens:
        LOG.error("PUSHPLUS_TOKEN(S) is missing. Use --dry-run for a local fetch test.")
        return 2

    try:
        tweets, diagnostics = fetch_sources(settings)
    except FetchError as exc:
        LOG.error("fetch failed: %s", exc)
        return 1
    _print_diagnostics(diagnostics, len(tweets))
    store = StateStore(settings.state_file)
    bootstrap_mode = args.bootstrap_mode or settings.bootstrap_mode
    if bootstrap_mode not in {"latest", "push_latest", "backfill"}:
        LOG.error("BOOTSTRAP_MODE must be latest, push_latest, or backfill; got %r", bootstrap_mode)
        return 2

    with store.lock():
        state = store.load()
        if not state.get("initialized"):
            if bootstrap_mode == "latest" and not dry_run:
                store.bootstrap(state, tweets)
                store.save(state)
                LOG.info("first run baseline created: %s tweets; no notification sent", len(tweets))
                return 0
            if bootstrap_mode == "push_latest":
                latest: list = []
                for account in settings.accounts:
                    account_tweets = [tweet for tweet in tweets if tweet.author == account]
                    if account_tweets:
                        latest.append(account_tweets[0])
                if not dry_run:
                    store.bootstrap(state, tweets)
                    for tweet in latest:
                        key = tweet.key
                        state["seen_ids"] = [item for item in state["seen_ids"] if item != key]
                candidates = latest
            else:
                candidates = store.candidates(state, tweets, include_old=True)
        else:
            candidates = store.candidates(state, tweets, include_old=args.include_old)

        if args.limit > 0:
            candidates = candidates[: args.limit]
        if not candidates:
            if dry_run:
                LOG.info("dry run: no candidate notifications")
            else:
                LOG.info("no new tweets")
            return 0

        if dry_run:
            candidates = hydrate_x_details(candidates, settings)

        for tweet in candidates:
            LOG.info(
                "candidate @%s %s %s text=%s",
                tweet.author,
                tweet.published_at,
                tweet.url,
                tweet.text[:120].replace("\n", " "),
            )

        if dry_run:
            enrich_candidates(candidates, settings)
            for tweet in candidates:
                title, content = render_tweet_html(tweet)
                print(f"\n=== {title} ===\n{content}")
            return 0

        if bootstrap_mode == "backfill" and not state.get("initialized"):
            state["initialized"] = True

        # A burst is sent as one digest so the free PushPlus daily quota is not exhausted.
        available = settings.max_push_per_day - store.push_count(state)
        if available <= 0:
            LOG.warning(
                "daily PushPlus budget exhausted: %s/%s logical notifications used",
                store.push_count(state),
                settings.max_push_per_day,
            )
            return 0

        send_as_digest = len(candidates) > settings.max_digest_items
        if send_as_digest:
            selected = candidates[: settings.max_digest_items]
            push_units = 1
        else:
            selected = candidates[:available]
            push_units = len(selected)

        if not store.can_push(state, push_units, settings.max_push_per_day):
            LOG.warning("not enough daily PushPlus budget for the next notification")
            return 0

        selected = hydrate_x_details(selected, settings)
        incomplete_x = [
            tweet
            for tweet in selected
            if tweet.content_status != "complete" and _has_x_html_source(tweet)
        ]
        if settings.require_x_full_text and incomplete_x:
            LOG.error(
                "X full text is unavailable for %s candidate(s); leaving them unclaimed for retry: %s",
                len(incomplete_x),
                [tweet.key for tweet in incomplete_x],
            )
            return 1

        # Translate only posts that will actually be delivered.
        enrichment_ok = enrich_candidates(selected, settings)
        if settings.require_ai_enrichment and not enrichment_ok:
            LOG.error(
                "AI enrichment is incomplete; leaving %s candidate(s) unclaimed so the next poll can retry",
                len(selected),
            )
            return 1

        # Claim before sending. This deliberately favors no duplicate notifications over
        # automatic re-delivery after an ambiguous network failure.
        store.claim(state, selected, len(settings.pushplus_tokens))
        store.save(state)

        if send_as_digest:
            title, content = render_digest_html(selected)
            results = send_to_all(settings.pushplus_tokens, title, content, topic=settings.pushplus_topic)
            store.record_delivery(state, selected, results)
            LOG.info("sent digest items=%s results=%s", len(selected), results)
        else:
            for tweet in selected:
                title, content = render_tweet_html(tweet)
                results = send_to_all(settings.pushplus_tokens, title, content, topic=settings.pushplus_topic)
                store.record_delivery(state, [tweet], results)
        store.record_push_attempt(state, push_units)
        store.save(state)
    return 0


def _has_x_html_source(tweet) -> bool:
    return any(source == "x_html" or source.startswith("x_html:") for source in tweet.sources)


def main() -> int:
    _configure_logging()
    args = _parser().parse_args()
    try:
        return run(args)
    except KeyboardInterrupt:
        LOG.warning("interrupted")
        return 130
    except Exception:
        LOG.exception("unexpected tracker failure")
        return 1


if __name__ == "__main__":
    sys.exit(main())
