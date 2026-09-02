from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import struct_time
from urllib.parse import quote

import feedparser

from config import NEWS_MAX_AGE_HOURS, NEWS_PER_FEED, RSS_TOPIC_FEEDS, WATCHLIST


@dataclass
class NewsItem:
    topic: str
    title: str
    link: str
    published: str

    def format_line(self) -> str:
        return f"- [{self.topic}] {self.title} ({self.published}) <{self.link}>"


def _build_watchlist_feeds() -> list[dict[str, str]]:
    feeds = []
    for item in WATCHLIST:
        query = quote(item["name"])
        feeds.append(
            {
                "topic": item["name"],
                "url": (
                    "https://news.google.com/rss/search?"
                    f"q={query}&hl=ko&gl=KR&ceid=KR:ko"
                ),
            }
        )
    return feeds


def _parse_published(entry: feedparser.FeedParserDict) -> datetime | None:
    published_parsed: struct_time | None = getattr(entry, "published_parsed", None)
    if published_parsed is None:
        return None

    return datetime(*published_parsed[:6], tzinfo=timezone.utc)


def _is_recent(published_at: datetime | None) -> bool:
    if published_at is None:
        return True

    cutoff = datetime.now(timezone.utc) - timedelta(hours=NEWS_MAX_AGE_HOURS)
    return published_at >= cutoff


def _normalize_title(title: str) -> str:
    return " ".join(title.split()).lower()


def fetch_news_items() -> list[NewsItem]:
    all_feeds = RSS_TOPIC_FEEDS + _build_watchlist_feeds()
    items: list[NewsItem] = []
    seen_titles: set[str] = set()

    for feed_info in all_feeds:
        feed = feedparser.parse(feed_info["url"])
        if feed.bozo:
            print(f"RSS 파싱 경고 ({feed_info['topic']}): {feed.bozo_exception}")

        count = 0
        for entry in feed.entries:
            if count >= NEWS_PER_FEED:
                break

            title = getattr(entry, "title", "").strip()
            if not title:
                continue

            normalized = _normalize_title(title)
            if normalized in seen_titles:
                continue

            published_at = _parse_published(entry)
            if not _is_recent(published_at):
                continue

            published_label = (
                published_at.astimezone().strftime("%Y-%m-%d %H:%M")
                if published_at
                else "날짜 미상"
            )

            items.append(
                NewsItem(
                    topic=feed_info["topic"],
                    title=title,
                    link=getattr(entry, "link", ""),
                    published=published_label,
                )
            )
            seen_titles.add(normalized)
            count += 1

    return items


def format_news_data(items: list[NewsItem]) -> str:
    if not items:
        return "수집된 뉴스가 없습니다."

    return "\n".join(item.format_line() for item in items)
