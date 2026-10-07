"""Manifest persistence and deterministic article delta classification."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import logging
from pathlib import Path
import os
import re
import tempfile
from typing import Iterable, Mapping

LOGGER = logging.getLogger(__name__)
MANIFEST_VERSION = 2
_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class ArticleState:
    """Remote state tracked for one successfully indexed article."""

    article_id: int
    slug: str
    url: str
    content_hash: str
    file_id: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ArticleDelta:
    """An article and its cleaned content hash for classification."""

    slug: str
    article_id: int
    url: str
    content_hash: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class Delta:
    added: tuple[ArticleDelta, ...]
    updated: tuple[ArticleDelta, ...]
    skipped: tuple[ArticleDelta, ...]


class ManifestStore:
    """Read and atomically persist the local article-to-file mapping."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._articles: dict[str, ArticleState] = {}

    @property
    def path(self) -> Path:
        return self._path

    @property
    def articles(self) -> Mapping[str, ArticleState]:
        return self._articles

    def load(self) -> dict[str, ArticleState]:
        """Load a manifest, treating a missing file as an empty first run."""
        if not self._path.exists():
            self._articles = {}
            return self._articles

        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if payload.get("version") != MANIFEST_VERSION:
                raise ValueError("unsupported manifest version")
            raw_articles = payload.get("articles", {})
            if not isinstance(raw_articles, dict):
                raise ValueError("manifest articles must be an object")
            self._articles = {
                str(article_id): _state_from_dict(str(article_id), raw_state)
                for article_id, raw_state in raw_articles.items()
            }
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            LOGGER.warning("invalid manifest path=%s; rebuilding: %s", self._path, error)
            self._articles = {}

        return self._articles

    def save(self) -> None:
        """Persist the manifest atomically so an interrupted write keeps old state."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": MANIFEST_VERSION,
            "articles": {
                str(article_id): asdict(state)
                for article_id, state in sorted(self._articles.items())
            },
        }
        content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f"{self._path.name}.",
            suffix=".tmp",
            dir=self._path.parent,
            text=True,
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_name, self._path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    def get(self, article_id: int) -> ArticleState | None:
        return self._articles.get(str(article_id))

    def set(self, article_id: int, state: ArticleState) -> None:
        self._articles[str(article_id)] = state

    def remove(self, article_id: int) -> None:
        self._articles.pop(str(article_id), None)


def sanitize_slug(value: str) -> str:
    """Convert an external slug into a stable manifest key."""
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    return slug or "article"


def content_hash(content: str) -> str:
    """Return a stable SHA-256 digest for cleaned Markdown."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def classify_articles(
    articles: Iterable[ArticleDelta],
    manifest: Mapping[str, ArticleState],
) -> Delta:
    """Classify articles using the manifest as a dictionary index."""
    added: list[ArticleDelta] = []
    updated: list[ArticleDelta] = []
    skipped: list[ArticleDelta] = []

    for article in articles:
        previous = manifest.get(str(article.article_id))
        if previous is None:
            added.append(article)
        elif previous.content_hash == article.content_hash:
            skipped.append(article)
        else:
            updated.append(article)

    return Delta(tuple(added), tuple(updated), tuple(skipped))


def _state_from_dict(article_id: str, raw_state: object) -> ArticleState:
    if not isinstance(raw_state, dict):
        raise ValueError(f"manifest state for article {article_id!r} must be an object")

    required = {"article_id", "slug", "url", "content_hash", "file_id", "updated_at"}
    if not required.issubset(raw_state):
        raise ValueError(f"manifest state for article {article_id!r} is missing fields")

    return ArticleState(
        article_id=int(raw_state["article_id"]),
        slug=sanitize_slug(str(raw_state["slug"])),
        url=str(raw_state["url"]),
        content_hash=str(raw_state["content_hash"]),
        file_id=str(raw_state["file_id"]),
        updated_at=str(raw_state["updated_at"]),
    )


__all__ = [
    "ArticleDelta",
    "ArticleState",
    "Delta",
    "ManifestStore",
    "classify_articles",
    "content_hash",
    "sanitize_slug",
]
