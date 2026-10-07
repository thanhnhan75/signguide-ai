"""Create the OpenAI Vector Store used by the daily sync job."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from openai import OpenAI

VECTOR_STORE_NAME = "signguide-knowledge-base"


def main() -> None:
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is required")

    existing_id = os.getenv("VECTOR_STORE_ID")
    if existing_id:
        print(f"VECTOR_STORE_ID is already configured: {existing_id}")
        print("No new vector store was created.")
        return

    store = OpenAI(api_key=api_key).vector_stores.create(name=VECTOR_STORE_NAME)
    print(f"Created vector store: {store.id}")
    print("Add this value to .env and the GitHub Actions secret VECTOR_STORE_ID.")
    print(f"VECTOR_STORE_ID={store.id}")


if __name__ == "__main__":
    main()
