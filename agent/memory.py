"""
Memory Manager: conversation history and user preferences.
LLMs are stateless; this module stores and retrieves context from Structured DB.
"""
import os
from typing import Any

# Optional: use db from parent
def _get_db():
    try:
        import db
        return db
    except ImportError:
        return None


def _truncate(history: list[dict], max_messages: int, keep_first: int) -> list[dict]:
    if not history or max_messages <= 0:
        return history or []
    if history[0].get("role") == "system":
        system_part = [history[0]]
        rest = history[1:]
    else:
        system_part = []
        rest = history
    if len(rest) <= max_messages:
        return history
    keep_first = min(keep_first, max_messages)
    tail_size = max_messages - keep_first
    if tail_size <= 0:
        return system_part + rest[:max_messages]
    return system_part + rest[:keep_first] + rest[-tail_size:]


class MemoryManager:
    """Stores and retrieves conversation history and user context (Structured DB)."""

    def __init__(
        self,
        max_history_messages: int | None = None,
        keep_first_messages: int | None = None,
    ):
        self.max_history = int(os.environ.get("CHAT_MAX_HISTORY_MESSAGES", "0")) if max_history_messages is None else max_history_messages
        self.keep_first = int(os.environ.get("CHAT_KEEP_FIRST_MESSAGES", "4")) if keep_first_messages is None else keep_first_messages

    def get_context(self, user_id: int) -> list[dict[str, str]]:
        """Return conversation context for the user (optionally truncated). Full history lives in DB."""
        db = _get_db()
        if not db:
            return []
        raw = db.get_history_by_user(user_id)
        if not raw:
            return []
        return _truncate(raw, self.max_history, self.keep_first)

    def append(self, user_id: int, user_message: str, assistant_message: str) -> None:
        """Persist one user turn and one assistant reply."""
        db = _get_db()
        if not db:
            return
        db.append_messages_for_user(
            user_id,
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message},
            ],
        )

    def get_preferences_summary(self, user_id: int) -> str | None:
        """Optional: return a short summary of user preferences (e.g. from first messages). Used by Prompt Builder."""
        db = _get_db()
        if not db:
            return None
        raw = db.get_history_by_user(user_id)
        if not raw or len(raw) < 2:
            return None
        # First few user/assistant pairs often contain preferences; could be replaced by a dedicated user_preferences field later.
        parts = []
        for m in raw[: min(6, len(raw))]:
            if m.get("role") == "user" and m.get("content"):
                parts.append(m["content"][:200])
        if not parts:
            return None
        return " (User has said: " + "; ".join(parts)[:500] + ")" if parts else None
