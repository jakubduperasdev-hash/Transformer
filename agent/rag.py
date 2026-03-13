"""
RAG (Retrieval Augmented Generation): Vector DB placeholder.
When implemented, retrieve relevant chunks to inject into the Prompt Builder context.
"""
from typing import Any


def retrieve(user_id: int, query: str, k: int = 3) -> list[str]:
    """
    Retrieve relevant context for the user/query. Default: no Vector DB, return empty.
    To enable: set RAG_ENABLED=1 and configure a vector store (e.g. pgvector, Chroma).
    """
    import os
    if not os.environ.get("RAG_ENABLED", "").strip().lower() in ("1", "true", "yes"):
        return []
    # Placeholder: could call a vector store here, e.g.:
    # return vector_store.search(user_id=user_id, query=query, top_k=k)
    return []
