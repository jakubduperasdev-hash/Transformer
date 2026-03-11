"""
SQLite database: users (auth) and per-user chat history.
"""
import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.environ.get("CHAT_DB_PATH", "chat_history.db")


def get_connection():
    return sqlite3.connect(DB_PATH)


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert sqlite3.Row to dict (safe across Python versions)."""
    return dict(zip(row.keys(), row))


def init_db():
    """Create tables if they don't exist."""
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_messages_user ON user_messages(user_id)"
        )
        conn.commit()
    finally:
        conn.close()


# --- Users (auth) ---

def create_user(username: str, email: str, password_hash: str) -> int:
    """Insert a new user; return user id. Raises on duplicate username/email."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (username.strip(), email.strip().lower(), password_hash, now),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_user_by_username(username: str) -> dict | None:
    """Return user row as dict or None."""
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, username, email, password_hash FROM users WHERE username = ?",
            (username.strip(),),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def get_user_by_email(email: str) -> dict | None:
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, username, email, password_hash FROM users WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> dict | None:
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, username, email FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


# --- Per-user chat history ---

def get_history_by_user(user_id: int) -> list[dict[str, str]]:
    """Load full message history for a user (role + content)."""
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT role, content FROM user_messages WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]
    finally:
        conn.close()


def append_messages_for_user(user_id: int, messages: list[dict[str, str]]) -> None:
    """Append messages to a user's history."""
    if not messages:
        return
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.executemany(
            "INSERT INTO user_messages (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            [(user_id, m["role"], m.get("content", ""), now) for m in messages],
        )
        conn.commit()
    finally:
        conn.close()
