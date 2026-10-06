"""Fetch and select public Help Center articles from Zendesk."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import logging
import os
from typing import Any, Protocol, Sequence

import requests
from requests import Response, Session
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://support.optisigns.com"
DEFAULT_LOCALE = "en-us"
DEFAULT_MAX_ARTICLES = 35
REQUEST_TIMEOUT_SECONDS = 15
PER_PAGE = 100


@dataclass(frozen=True, slots=True)
class Article:
    """The Zendesk fields used by the ingestion pipeline."""

    id: int
    title: str
    body: str
    html_url: str
    locale: str
    draft: bool
    section_id: int | None
    vote_sum: int
    updated_at: str


class ArticleFetcher(Protocol):
    """A source that returns support articles."""

    def fetch_all(self) -> list[Article]:
        """Fetch all available articles from the source."""


def _is_retryable_error(error: BaseException) -> bool:
    return isinstance(error, requests.HTTPError) and error.response is not None and (
        error.response.status_code == 429 or 500 <= error.response.status_code < 600
    )


class ZendeskAPIFetcher:
    """Fetches public Zendesk Help Center articles through its REST API."""

    def __init__(
        self,
        session: Session | None = None,
        base_url: str = DEFAULT_BASE_URL,
        locale: str = DEFAULT_LOCALE,
        timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._session = session or requests.Session()
        self._base_url = base_url.rstrip("/")
        self._locale = locale
        self._timeout_seconds = timeout_seconds

    def fetch_all(self) -> list[Article]:
        """Follow Zendesk pagination until there are no more article pages."""
        url = f"{self._base_url}/api/v2/help_center/{self._locale}/articles.json"
        params: dict[str, Any] | None = {"per_page": PER_PAGE}
        articles: list[Article] = []
        page_number = 0

        while url:
            response = self._get_page(url, params)
            payload = response.json()
            page_articles = [self._to_article(raw) for raw in payload.get("articles", [])]
            articles.extend(page_articles)
            page_number += 1
            url = payload.get("next_page")
            params = None

            LOGGER.info(
                "page=%d fetched=%d total=%d has_next=%s",
                page_number,
                len(page_articles),
                len(articles),
                bool(url),
            )

        return articles

    @retry(
        retry=retry_if_exception(_is_retryable_error),
        wait=wait_exponential_jitter(initial=1, max=20),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _get_page(self, url: str, params: dict[str, Any] | None) -> Response:
        response = self._session.get(
            url,
            params=params,
            headers={"Accept": "application/json", "User-Agent": "signguide-ai/0.1"},
            timeout=self._timeout_seconds,
        )

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            LOGGER.warning("Zendesk rate limited the request; retry_after=%s", retry_after)

        response.raise_for_status()
        return response

    @staticmethod
    def _to_article(raw: dict[str, Any]) -> Article:
        return Article(
            id=int(raw["id"]),
            title=str(raw.get("title") or raw.get("name") or "Untitled article"),
            body=str(raw.get("body") or ""),
            html_url=str(raw.get("html_url") or ""),
            locale=str(raw.get("locale") or ""),
            draft=bool(raw.get("draft", False)),
            section_id=raw.get("section_id"),
            vote_sum=int(raw.get("vote_sum") or 0),
            updated_at=str(raw.get("updated_at") or ""),
        )


def select_articles(
    articles: list[Article],
    target: int = DEFAULT_MAX_ARTICLES,
    must_include_keywords: Sequence[str] = ("youtube",),
) -> list[Article]:
    """Choose a diverse article set while covering each required keyword."""
    if target < 1:
        raise ValueError("target must be at least 1")

    keywords = tuple(keyword.strip().lower() for keyword in must_include_keywords if keyword.strip())
    candidates = [
        article
        for article in articles
        if article.locale == DEFAULT_LOCALE and not article.draft and article.body.strip()
    ]
    selected: list[Article] = []
    selected_ids: set[int] = set()

    if keywords:
        required_articles: list[Article] = []
        required_ids: set[int] = set()
        for keyword in keywords:
            title_matches = [article for article in candidates if keyword in article.title.lower()]
            matches = title_matches or [
                article for article in candidates if keyword in article.body.lower()
            ]
            matches.sort(key=_quality_key, reverse=True)
            if not matches:
                raise ValueError(f'No published article found for keyword "{keyword}"')
            _add_article(required_articles, required_ids, matches[0])

        if len(required_articles) > target:
            raise ValueError("target is smaller than required keyword coverage")
        for article in required_articles:
            _add_article(selected, selected_ids, article)

    by_section: dict[int | None, deque[Article]] = defaultdict(deque)
    for article in sorted(candidates, key=_quality_key, reverse=True):
        by_section[article.section_id].append(article)

    while len(selected) < target:
        added_this_round = False
        for section_id in sorted(by_section, key=lambda value: str(value)):
            queue = by_section[section_id]
            while queue and queue[0].id in selected_ids:
                queue.popleft()
            if not queue:
                continue

            _add_article(selected, selected_ids, queue.popleft())
            added_this_round = True
            if len(selected) == target:
                break

        if not added_this_round:
            break

    if len(selected) < target:
        raise ValueError(f"Only {len(selected)} published English articles are available")

    LOGGER.info(
        "selected=%d candidates=%d required_keywords=%s sections=%d",
        len(selected),
        len(candidates),
        ",".join(keywords) or "none",
        len(by_section),
    )
    return selected


def _quality_key(article: Article) -> tuple[int, int, int]:
    """Prefer useful, substantial articles within each section."""
    return (article.vote_sum, len(article.body), article.id)


def _add_article(selected: list[Article], selected_ids: set[int], article: Article) -> None:
    if article.id not in selected_ids:
        selected.append(article)
        selected_ids.add(article.id)


def _read_max_articles() -> int:
    raw_value = os.getenv("MAX_ARTICLES", str(DEFAULT_MAX_ARTICLES))
    try:
        return int(raw_value)
    except ValueError as error:
        raise ValueError("MAX_ARTICLES must be an integer") from error


def _read_must_include_keywords() -> tuple[str, ...]:
    raw_value = os.getenv("MUST_INCLUDE_KEYWORDS", "youtube")
    return tuple(keyword.strip() for keyword in raw_value.split(",") if keyword.strip())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    fetcher = ZendeskAPIFetcher()
    articles = fetcher.fetch_all()
    selected = select_articles(
        articles,
        target=_read_max_articles(),
        must_include_keywords=_read_must_include_keywords(),
    )
    print(f"Fetched {len(articles)} articles; selected {len(selected)} articles.")
    for article in selected:
        print(f"- [{article.section_id}] {article.title}")


if __name__ == "__main__":
    main()
