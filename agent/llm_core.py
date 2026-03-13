"""
LLM Core: single entry point for completion (internal or external inference).
"""
from typing import Any


def use_external() -> bool:
    try:
        from inference_client import use_external as ext
        return ext()
    except ImportError:
        return False


def complete(messages: list[dict[str, str]]) -> str:
    """One-shot completion. Returns assistant reply text."""
    if not messages or messages[-1].get("role") != "user":
        raise ValueError("messages must end with a user message")
    user_message = messages[-1].get("content", "")
    history = messages[:-1] if len(messages) > 1 else None
    if use_external():
        from inference_client import chat
        _, reply = chat(user_message, history)
        return reply
    from romatic_chatbot import chat
    _, reply = chat(user_message, history=history)
    return reply


def complete_stream(messages: list[dict[str, str]]):
    """Stream completion. Yields text chunks, then (full_history, full_reply) at end."""
    if not messages or messages[-1].get("role") != "user":
        raise ValueError("messages must end with a user message")
    user_message = messages[-1].get("content", "")
    history = messages[:-1] if len(messages) > 1 else None
    if use_external():
        from inference_client import chat_stream
        yield from chat_stream(user_message, history)
        return
    from romatic_chatbot import chat_stream
    yield from chat_stream(user_message, history=history)
