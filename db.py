"""
SQLite database for storing per-session chat history.
Each user is identified by a session_id (from the frontend).
"""
import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.environ.get("CHAT_DB_PATH", "chat_history.db")


def get_connection():
    return sqlite3.connect(DB_PATH)


def init_db():
    """Create tables if they don't exist."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)"
        )


def get_history(session_id: str) -> list[dict[str, str]]:
    """Load full message history for a session (role + content)."""
    if not session_id or not session_id.strip():
        return []
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
            (session_id.strip(),),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def append_messages(session_id: str, messages: list[dict[str, str]]) -> None:
    """Append one or more messages to a session."""
    if not session_id or not session_id.strip() or not messages:
        return
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.executemany(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            [
                (session_id.strip(), m["role"], m.get("content", ""), now)
                for m in messages
            ],
        )
