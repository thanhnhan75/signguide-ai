"""Daily knowledge-base sync entrypoint."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
from typing import Iterable

from dotenv import load_dotenv
from openai import OpenAI

from scraper.clean import DATA_DIR, html_to_markdown, write_article
from scraper.fetch import Article, ZendeskAPIFetcher, select_articles
from scraper.store import (
    ArticleDelta,
    ArticleState,
    ManifestStore,
    classify_articles,
    content_hash,
    sanitize_slug,
)
from scraper.uploader import VectorStoreUploader

LOGGER = logging.getLogger(__name__)
MANIFEST_PATH = Path("state") / "manifest.json"
DEFAULT_KEYWORDS = ("youtube",)


def _read_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        return int(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error


def _read_keywords(name: str, default: Iterable[str] = DEFAULT_KEYWORDS) -> tuple[str, ...]:
    raw_value = os.getenv(name, ",".join(default))
    return tuple(keyword.strip() for keyword in raw_value.split(",") if keyword.strip())


def _article_delta(article: Article, markdown: str) -> ArticleDelta:
    return ArticleDelta(
        slug=sanitize_slug(article.title),
        article_id=article.id,
        url=article.html_url,
        content_hash=content_hash(markdown),
        updated_at=article.updated_at,
    )


def _process_delta(
    delta: ArticleDelta,
    article: Article,
    markdown: str,
    previous_state: ArticleState | None,
    uploader: VectorStoreUploader,
    store: ManifestStore,
    data_dir: Path,
) -> None:
    """Upload a changed article after removing its old remote representation."""
    if previous_state is not None:
        uploader.delete_file(previous_state.file_id)

    path = write_article(article, data_dir)
    file_id = uploader.upload_and_attach(path, article.id)
    store.set(
        article.id,
        ArticleState(
            article_id=article.id,
            slug=delta.slug,
            url=delta.url,
            content_hash=delta.content_hash,
            file_id=file_id,
            updated_at=delta.updated_at,
        ),
    )


def run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    vector_store_id = os.getenv("VECTOR_STORE_ID")
    if not api_key:
        LOGGER.error("OPENAI_API_KEY is required")
        return 1
    if not vector_store_id:
        LOGGER.error(
            "VECTOR_STORE_ID is required for sync mode. "
            "Create a vector store once, then configure its ID."
        )
        return 1

    store = ManifestStore(MANIFEST_PATH)
    manifest = store.load()

    fetcher = ZendeskAPIFetcher()
    uploader = VectorStoreUploader(
        client=OpenAI(api_key=api_key),
        vector_store_id=vector_store_id,
    )

    all_articles = fetcher.fetch_all()
    selected_articles = select_articles(
        all_articles,
        target=_read_int("MAX_ARTICLES", 35),
        must_include_keywords=_read_keywords("MUST_INCLUDE_KEYWORDS"),
    )

    prepared: list[tuple[Article, ArticleDelta, str]] = []
    for article in selected_articles:
        markdown = html_to_markdown(article.body, article.html_url, article.title)
        prepared.append((article, _article_delta(article, markdown), markdown))

    deltas = [delta for _, delta, _ in prepared]
    delta = classify_articles(deltas, manifest)

    previous_by_id = {
        state.article_id: state
        for state in manifest.values()
    }
    articles_by_id = {
        article.id: article
        for article in selected_articles
    }
    markdown_by_id = {
        article.id: markdown
        for article, _, markdown in prepared
    }

    failures = 0
    for item in delta.added:
        try:
            _process_delta(
                item,
                articles_by_id[item.article_id],
                markdown_by_id[item.article_id],
                None,
                uploader,
                store,
                DATA_DIR,
            )
        except Exception as error:
            failures += 1
            LOGGER.error("failed added article_id=%s: %s", item.article_id, error)

    for item in delta.updated:
        try:
            _process_delta(
                item,
                articles_by_id[item.article_id],
                markdown_by_id[item.article_id],
                previous_by_id.get(item.article_id),
                uploader,
                store,
                DATA_DIR,
            )
        except Exception as error:
            failures += 1
            LOGGER.error("failed updated article_id=%s: %s", item.article_id, error)

    store.save()

    LOGGER.info(
        "Discovered:%d Selected:%d Added:%d Updated:%d Skipped:%d Failed:%d",
        len(all_articles),
        len(selected_articles),
        len(delta.added),
        len(delta.updated),
        len(delta.skipped),
        failures,
    )
    LOGGER.info("VectorStore:%s", uploader.vector_store_id)
    LOGGER.info("FileCounts:%s", uploader.file_counts())

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
