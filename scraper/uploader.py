"""Upload Markdown articles to an OpenAI vector store."""

from __future__ import annotations

from pathlib import Path
import logging
import os
from typing import Any

from openai import NotFoundError, OpenAI

LOGGER = logging.getLogger(__name__)
VECTOR_STORE_NAME = "signguide-knowledge-base"
OPENAI_FILE_PURPOSE = "assistants"


class VectorStoreUploader:
    """Small adapter around the OpenAI Files and Vector Stores APIs."""

    def __init__(
        self,
        client: OpenAI,
        vector_store_id: str | None = None,
        vector_store_name: str = VECTOR_STORE_NAME,
    ) -> None:
        self._client = client
        self._vector_store_id = vector_store_id
        self._vector_store_name = vector_store_name

    @property
    def vector_store_id(self) -> str:
        """Return the configured store ID without creating remote state implicitly."""
        if self._vector_store_id is None:
            raise RuntimeError(
                "VECTOR_STORE_ID is required for sync mode. "
                "Create a vector store once, then configure its ID."
            )
        return self._vector_store_id

    def bootstrap_vector_store(self) -> str:
        """Create a store explicitly for one-time local bootstrap."""
        if self._vector_store_id is None:
            store = self._client.vector_stores.create(name=self._vector_store_name)
            self._vector_store_id = store.id
            LOGGER.info("created vector_store=%s", store.id)
        return self._vector_store_id

    def upload_and_attach(self, path: Path, article_id: int | None = None) -> str:
        """Upload one Markdown file, attach it, and wait for indexing."""
        with path.open("rb") as stream:
            uploaded = self._client.files.create(
                file=stream,
                purpose=OPENAI_FILE_PURPOSE,
            )

        attributes: dict[str, Any] = {"source_file": path.name}
        if article_id is not None:
            attributes["article_id"] = article_id

        indexed = self._client.vector_stores.files.create_and_poll(
            vector_store_id=self.vector_store_id,
            file_id=uploaded.id,
            attributes=attributes,
        )
        if indexed.status != "completed":
            last_error = getattr(indexed, "last_error", None)
            raise RuntimeError(
                f"Vector store indexing failed for {path.name}: "
                f"status={indexed.status}, last_error={last_error}"
            )

        LOGGER.info("indexed file=%s file_id=%s", path.name, uploaded.id)
        return uploaded.id

    def delete_file(self, file_id: str, delete_source: bool = True) -> None:
        """Idempotently detach a vector file and optionally delete its source."""
        try:
            self._client.vector_stores.files.delete(
                vector_store_id=self.vector_store_id,
                file_id=file_id,
            )
        except NotFoundError:
            LOGGER.warning("vector file already removed file_id=%s", file_id)

        if delete_source:
            try:
                self._client.files.delete(file_id)
            except NotFoundError:
                LOGGER.warning("source file already removed file_id=%s", file_id)

        LOGGER.info("deleted vector_file=%s", file_id)

    def file_counts(self) -> dict[str, int]:
        """Return the current vector store file counts for run logging."""
        store = self._client.vector_stores.retrieve(self.vector_store_id)
        counts = store.file_counts
        return {
            "in_progress": counts.in_progress,
            "completed": counts.completed,
            "failed": counts.failed,
            "cancelled": counts.cancelled,
            "total": counts.total,
        }


def create_uploader() -> VectorStoreUploader:
    """Build an uploader from environment configuration for the CLI entrypoint."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required")

    vector_store_id = os.getenv("VECTOR_STORE_ID")
    if not vector_store_id:
        raise ValueError(
            "VECTOR_STORE_ID is required for sync mode. "
            "Create a vector store once, then configure its ID."
        )

    return VectorStoreUploader(
        client=OpenAI(api_key=api_key),
        vector_store_id=vector_store_id,
    )


__all__ = ["VectorStoreUploader", "create_uploader"]
