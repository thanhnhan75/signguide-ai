"""Clean Zendesk article HTML and write it as Markdown."""

from __future__ import annotations

import html
from pathlib import Path
import re
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from markdownify import markdownify

from .fetch import Article

DATA_DIR = Path("data")
_SLUG_SEPARATOR_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Create a safe, stable filename component from an article title."""
    slug = _SLUG_SEPARATOR_RE.sub("-", value.lower()).strip("-")
    return slug or "article"


def _clean_html(raw_html: str, article_url: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")

    for tag in soup.find_all(["script", "style", "noscript", "iframe"]):
        tag.decompose()

    for tag in soup.find_all(True):
        for attribute in list(tag.attrs):
            if attribute.lower().startswith("on"):
                del tag.attrs[attribute]

        if tag.name == "a":
            href = tag.get("href")
            if not isinstance(href, str):
                continue
            if href.strip().lower().startswith(("javascript:", "data:")):
                tag.unwrap()
            else:
                tag["href"] = urljoin(article_url, href)

    return str(soup)


def html_to_markdown(raw_html: str, article_url: str, title: str) -> str:
    """Convert trusted article structure while treating body HTML as untrusted input."""
    cleaned_html = _clean_html(raw_html, article_url)
    body = markdownify(
        cleaned_html,
        heading_style="ATX",
        bullets="-",
        strip=["script", "style", "noscript", "iframe"],
    )
    body = _normalise_markdown(body)
    return f"# {title.strip()}\n\nArticle URL: {article_url}\n\n{body}".strip() + "\n"


def _normalise_markdown(value: str) -> str:
    value = html.unescape(value).replace("\r\n", "\n")
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def write_article(article: Article, output_dir: Path = DATA_DIR) -> Path:
    """Write one cleaned article and verify the path remains inside output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{slugify(article.title)}.md"
    output_path = (output_dir / filename).resolve()
    resolved_dir = output_dir.resolve()
    if output_path.parent != resolved_dir:
        raise ValueError(f"Unsafe output path for article {article.id}")

    content = html_to_markdown(article.body, article.html_url, article.title)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def write_articles(articles: Iterable[Article], output_dir: Path = DATA_DIR) -> list[Path]:
    """Write a collection of articles and return their paths."""
    return [write_article(article, output_dir) for article in articles]


__all__ = [
    "DATA_DIR",
    "html_to_markdown",
    "slugify",
    "write_article",
    "write_articles",
]
