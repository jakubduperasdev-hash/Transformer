"""
Database: users (with tenant_id), tenants, user_messages, audit_log.
Supports SQLite (default) and PostgreSQL when DATABASE_URL is set.
"""
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

DATABASE_URL = os.environ.get("DATABASE_URL")  # e.g. postgresql://user:pass@host/db
DB_PATH = os.environ.get("CHAT_DB_PATH", "chat_history.db")

# Default tenant for single-tenant or first tenant
DEFAULT_TENANT_ID = 1


try:
    import psycopg2
    import psycopg2.extras
    from psycopg2.pool import ThreadedConnectionPool
except ImportError:
    psycopg2 = None
    ThreadedConnectionPool = None

_PG_POOL = None
PG_POOL_MIN = int(os.environ.get("PG_POOL_MIN", "2"))
PG_POOL_MAX = int(os.environ.get("PG_POOL_MAX", "20"))


def _get_pg_pool():
    global _PG_POOL
    if _PG_POOL is None and DATABASE_URL and DATABASE_URL.startswith("postgresql") and psycopg2 and ThreadedConnectionPool:
        _PG_POOL = ThreadedConnectionPool(PG_POOL_MIN, PG_POOL_MAX, DATABASE_URL)
    return _PG_POOL


def get_connection():
    if DATABASE_URL and DATABASE_URL.startswith("postgresql") and psycopg2:
        pool = _get_pg_pool()
        if pool:
            conn = pool.getconn()
            conn.autocommit = False
            return _PGConnection(conn, pool)
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return _PGConnection(conn, None)
    return _SQLiteConnection(sqlite3.connect(DB_PATH))


class _SQLiteConnection:
    def __init__(self, conn):
        self._conn = conn
        self._param = "?"

    def execute(self, sql: str, params: tuple = ()):
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def lastrowid(self, cur) -> int:
        return cur.lastrowid


class _PGConnection:
    def __init__(self, conn, pool=None):
        self._conn = conn
        self._pool = pool
        self._param = "%s"

    def execute(self, sql: str, params: tuple = ()):
        sql = sql.replace("?", "%s")
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        if self._pool:
            try:
                self._conn.rollback()
            except Exception:
                pass
            self._pool.putconn(self._conn)
        else:
            self._conn.close()

    def lastrowid(self, cur) -> int:
        return cur.fetchone() or cur.lastrowid


def _is_pg() -> bool:
    return bool(DATABASE_URL and DATABASE_URL.startswith("postgresql") and psycopg2)


def _row_to_dict(row) -> dict:
    if row is None:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    return dict(zip(row.keys(), row))


def check_connection() -> bool:
    """Return True if DB is reachable (for health check)."""
    try:
        conn_impl = get_connection()
        try:
            if _is_pg():
                cur = conn_impl.execute("SELECT 1", ())
                cur.fetchone()
            else:
                conn_impl.execute("SELECT 1", ())
        finally:
            conn_impl.close()
        return True
    except Exception:
        return False


def init_db():
    """Create tables. Supports SQLite and PostgreSQL."""
    conn_impl = get_connection()
    try:
        if _is_pg():
            _init_pg(conn_impl)
        else:
            _init_sqlite(conn_impl)
    finally:
        conn_impl.close()


def _init_sqlite(conn_impl):
    conn = conn_impl._conn
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tenants (id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO tenants (id, name, created_at) VALUES (1, 'Default', ?)",
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id),
            username TEXT NOT NULL,
            email TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(tenant_id, username),
            UNIQUE(email)
        )
        """
    )
    _ensure_column_sqlite(conn, "users", "tenant_id", "INTEGER DEFAULT 1")
    _ensure_column_sqlite(conn, "users", "consent_at", "TEXT")
    _ensure_column_sqlite(conn, "users", "lawful_basis", "TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_messages_user ON user_messages(user_id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            user_id INTEGER,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_daily_usage (
            tenant_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            request_count INTEGER NOT NULL DEFAULT 0,
            token_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (tenant_id, date),
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens(token_hash)")
    conn.commit()


def _ensure_column_sqlite(conn, table: str, column: str, col_type: str):
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except sqlite3.OperationalError:
        pass


def _ensure_column_pg(conn, cur, table: str, column: str, col_type: str):
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except Exception as e:
        if getattr(e, "pgcode", None) == "42701":  # duplicate_column
            conn.rollback()
        else:
            raise


def _init_pg(conn_impl):
    conn = conn_impl._conn
    cur = conn.cursor()
    try:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS tenants (id SERIAL PRIMARY KEY, name TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL)"
        )
        cur.execute(
            "INSERT INTO tenants (id, name, created_at) VALUES (1, 'Default', %s) ON CONFLICT (id) DO NOTHING",
            (datetime.now(timezone.utc).isoformat(),),
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id),
                username TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                UNIQUE(tenant_id, username)
            )
            """
        )
        _ensure_column_pg(conn, cur, "users", "consent_at", "TIMESTAMPTZ")
        _ensure_column_pg(conn, cur, "users", "lawful_basis", "TEXT")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_messages (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_messages_user ON user_messages(user_id)")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER,
                action TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tenant_daily_usage (
                tenant_id INTEGER NOT NULL REFERENCES tenants(id),
                date DATE NOT NULL,
                request_count INTEGER NOT NULL DEFAULT 0,
                token_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (tenant_id, date)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens(token_hash)")
    finally:
        cur.close()
    conn_impl.commit()


# --- Refresh tokens ---

def _hash_refresh_token(plain: str) -> str:
    import hashlib
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def create_refresh_token(user_id: int, expires_at: str) -> str:
    """Create a refresh token for user; store hash. Returns plain token (store in client)."""
    import secrets
    plain = secrets.token_urlsafe(32)
    token_hash = _hash_refresh_token(plain)
    conn_impl = get_connection()
    try:
        if _is_pg():
            conn_impl.execute(
                "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
                (user_id, token_hash, expires_at),
            )
        else:
            conn_impl.execute(
                "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
                (user_id, token_hash, expires_at),
            )
        conn_impl.commit()
        return plain
    finally:
        conn_impl.close()


def get_user_by_refresh_token(plain_token: str) -> dict | None:
    """Return user dict if valid refresh token and not expired; else None. Does not consume token."""
    token_hash = _hash_refresh_token(plain_token)
    now = datetime.now(timezone.utc).isoformat()
    conn_impl = get_connection()
    try:
        if _is_pg():
            cur = conn_impl.execute(
                "SELECT u.id, u.tenant_id, u.username, u.email FROM users u "
                "JOIN refresh_tokens r ON r.user_id = u.id WHERE r.token_hash = %s AND r.expires_at > %s",
                (token_hash, now),
            )
        else:
            conn_impl._conn.row_factory = sqlite3.Row
            cur = conn_impl.execute(
                "SELECT u.id, u.tenant_id, u.username, u.email FROM users u "
                "JOIN refresh_tokens r ON r.user_id = u.id WHERE r.token_hash = ? AND r.expires_at > ?",
                (token_hash, now),
            )
        row = cur.fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn_impl.close()


def revoke_refresh_token(plain_token: str) -> None:
    """Remove refresh token (e.g. on logout or rotation)."""
    token_hash = _hash_refresh_token(plain_token)
    conn_impl = get_connection()
    try:
        if _is_pg():
            conn_impl.execute("DELETE FROM refresh_tokens WHERE token_hash = %s", (token_hash,))
        else:
            conn_impl.execute("DELETE FROM refresh_tokens WHERE token_hash = ?", (token_hash,))
        conn_impl.commit()
    finally:
        conn_impl.close()


# --- Tenants ---

def get_tenant_by_id(tenant_id: int) -> dict | None:
    """Return tenant row if it exists."""
    conn_impl = get_connection()
    try:
        if _is_pg():
            cur = conn_impl.execute(
                "SELECT id, name, created_at FROM tenants WHERE id = %s",
                (tenant_id,),
            )
        else:
            conn_impl._conn.row_factory = sqlite3.Row
            cur = conn_impl.execute("SELECT id, name, created_at FROM tenants WHERE id = ?", (tenant_id,))
        row = cur.fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn_impl.close()


def list_tenants() -> list[dict]:
    """Return all tenants (id, name) for signup/UI."""
    conn_impl = get_connection()
    try:
        if _is_pg():
            cur = conn_impl.execute("SELECT id, name FROM tenants ORDER BY id")
        else:
            conn_impl._conn.row_factory = sqlite3.Row
            cur = conn_impl.execute("SELECT id, name FROM tenants ORDER BY id")
        rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn_impl.close()


# --- Audit ---

def audit_log(tenant_id: int, user_id: int | None, action: str, details: str | None = None):
    now = datetime.now(timezone.utc).isoformat()
    conn_impl = get_connection()
    try:
        if _is_pg():
            conn_impl.execute(
                "INSERT INTO audit_log (tenant_id, user_id, action, details, created_at) VALUES (%s, %s, %s, %s, %s)",
                (tenant_id, user_id, action, details, now),
            )
        else:
            conn_impl.execute(
                "INSERT INTO audit_log (tenant_id, user_id, action, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (tenant_id, user_id, action, details, now),
            )
        conn_impl.commit()
    finally:
        conn_impl.close()


# --- Users ---

def create_user(
    username: str,
    email: str,
    password_hash: str,
    tenant_id: int = DEFAULT_TENANT_ID,
    consent_at: str | None = None,
    lawful_basis: str | None = None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    conn_impl = get_connection()
    try:
        if _is_pg():
            cur = conn_impl.execute(
                "INSERT INTO users (tenant_id, username, email, password_hash, created_at, consent_at, lawful_basis) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (tenant_id, username.strip(), email.strip().lower(), password_hash, now, consent_at, lawful_basis),
            )
            row = cur.fetchone()
            conn_impl.commit()
            return int(row["id"]) if row else None
        else:
            cur = conn_impl.execute(
                "INSERT INTO users (tenant_id, username, email, password_hash, created_at, consent_at, lawful_basis) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (tenant_id, username.strip(), email.strip().lower(), password_hash, now, consent_at, lawful_basis),
            )
            conn_impl.commit()
            return cur.lastrowid
    finally:
        conn_impl.close()


def get_user_by_username(username: str, tenant_id: int | None = None) -> dict | None:
    conn_impl = get_connection()
    try:
        if _is_pg():
            if tenant_id is not None:
                cur = conn_impl.execute(
                    "SELECT id, tenant_id, username, email, password_hash FROM users WHERE username = %s AND tenant_id = %s",
                    (username.strip(), tenant_id),
                )
            else:
                cur = conn_impl.execute(
                    "SELECT id, tenant_id, username, email, password_hash FROM users WHERE username = %s",
                    (username.strip(),),
                )
            row = cur.fetchone()
            return dict(row) if row else None
        else:
            conn_impl._conn.row_factory = sqlite3.Row
            if tenant_id is not None:
                cur = conn_impl.execute(
                    "SELECT id, tenant_id, username, email, password_hash FROM users WHERE username = ? AND tenant_id = ?",
                    (username.strip(), tenant_id),
                )
            else:
                cur = conn_impl.execute(
                    "SELECT id, tenant_id, username, email, password_hash FROM users WHERE username = ?",
                    (username.strip(),),
                )
            row = cur.fetchone()
            return _row_to_dict(row) if row else None
    finally:
        conn_impl.close()


def get_user_by_email(email: str) -> dict | None:
    conn_impl = get_connection()
    try:
        email = email.strip().lower()
        if _is_pg():
            cur = conn_impl.execute(
                "SELECT id, tenant_id, username, email, password_hash FROM users WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        else:
            conn_impl._conn.row_factory = sqlite3.Row
            cur = conn_impl.execute(
                "SELECT id, tenant_id, username, email, password_hash FROM users WHERE email = ?",
                (email,),
            )
            row = cur.fetchone()
            return _row_to_dict(row) if row else None
    finally:
        conn_impl.close()


def get_user_by_id(user_id: int) -> dict | None:
    conn_impl = get_connection()
    try:
        if _is_pg():
            cur = conn_impl.execute(
                "SELECT id, tenant_id, username, email, consent_at, lawful_basis FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        else:
            conn_impl._conn.row_factory = sqlite3.Row
            cur = conn_impl.execute(
                "SELECT id, tenant_id, username, email, consent_at, lawful_basis FROM users WHERE id = ?",
                (user_id,),
            )
            row = cur.fetchone()
            return _row_to_dict(row) if row else None
    finally:
        conn_impl.close()


# --- GDPR: delete and export ---

def delete_user_data(user_id: int) -> dict | None:
    """Delete user and all their messages. Returns user row before delete for audit."""
    user = get_user_by_id(user_id)
    if not user:
        return None
    tenant_id = user.get("tenant_id", DEFAULT_TENANT_ID)
    conn_impl = get_connection()
    try:
        if _is_pg():
            conn_impl.execute("DELETE FROM user_messages WHERE user_id = %s", (user_id,))
            conn_impl.execute("DELETE FROM users WHERE id = %s", (user_id,))
        else:
            conn_impl.execute("DELETE FROM user_messages WHERE user_id = ?", (user_id,))
            conn_impl.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn_impl.commit()
        audit_log(tenant_id, user_id, "user_deleted", f"username={user.get('username')}")
        return user
    finally:
        conn_impl.close()


def export_user_data(user_id: int) -> dict | None:
    """Export all user data (profile + messages) for GDPR portability."""
    user = get_user_by_id(user_id)
    if not user:
        return None
    user_export = {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "consent_at": user.get("consent_at"),
        "lawful_basis": user.get("lawful_basis"),
    }
    history = get_history_by_user(user_id)
    return {"user": user_export, "messages": history, "exported_at": datetime.now(timezone.utc).isoformat()}


# --- Per-tenant usage (billing) ---

def get_tenant_daily_usage(tenant_id: int) -> tuple[int, int]:
    """Return (request_count, token_count) for the tenant today. (0, 0) if no row."""
    from datetime import date
    today = date.today().isoformat()
    conn_impl = get_connection()
    try:
        if _is_pg():
            cur = conn_impl.execute(
                "SELECT request_count, token_count FROM tenant_daily_usage WHERE tenant_id = %s AND date = %s",
                (tenant_id, today),
            )
        else:
            conn_impl._conn.row_factory = sqlite3.Row
            cur = conn_impl.execute(
                "SELECT request_count, token_count FROM tenant_daily_usage WHERE tenant_id = ? AND date = ?",
                (tenant_id, today),
            )
        row = cur.fetchone()
        if not row:
            return 0, 0
        r = _row_to_dict(row) if row is not None else {}
        req = r.get("request_count", 0) if isinstance(r, dict) else (row[0] if len(row) > 0 else 0)
        tok = r.get("token_count", 0) if isinstance(r, dict) else (row[1] if len(row) > 1 else 0)
        return int(req or 0), int(tok or 0)
    finally:
        conn_impl.close()


def record_usage(tenant_id: int, request_delta: int = 1, token_delta: int = 0) -> None:
    """Increment tenant daily usage for billing. Call after each chat."""
    from datetime import date
    today = date.today().isoformat()
    conn_impl = get_connection()
    try:
        if _is_pg():
            cur = conn_impl._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO tenant_daily_usage (tenant_id, date, request_count, token_count)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (tenant_id, date) DO UPDATE SET
                        request_count = tenant_daily_usage.request_count + EXCLUDED.request_count,
                        token_count = tenant_daily_usage.token_count + EXCLUDED.token_count
                    """,
                    (tenant_id, today, request_delta, token_delta),
                )
            finally:
                cur.close()
        else:
            conn_impl._conn.execute(
                """
                INSERT INTO tenant_daily_usage (tenant_id, date, request_count, token_count)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tenant_id, date) DO UPDATE SET
                    request_count = request_count + ?,
                    token_count = token_count + ?
                """,
                (tenant_id, today, request_delta, token_delta, request_delta, token_delta),
            )
        conn_impl.commit()
    finally:
        conn_impl.close()


# --- Chat history ---

def get_history_by_user(user_id: int) -> list[dict[str, str]]:
    conn_impl = get_connection()
    try:
        if _is_pg():
            cur = conn_impl.execute(
                "SELECT role, content FROM user_messages WHERE user_id = %s ORDER BY id",
                (user_id,),
            )
            rows = cur.fetchall()
        else:
            conn_impl._conn.row_factory = sqlite3.Row
            cur = conn_impl.execute(
                "SELECT role, content FROM user_messages WHERE user_id = ? ORDER BY id",
                (user_id,),
            )
            rows = cur.fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]
    finally:
        conn_impl.close()


def get_history_paginated(
    user_id: int,
    limit: int = 10,
    before_id: int | None = None,
) -> tuple[list[dict], bool]:
    """
    Return (messages, has_more). Messages are chronological (oldest first).
    - before_id=None: return the most recent `limit` messages (so initial load is fast).
    - before_id set: return up to `limit` messages older than that id (for "load more" on scroll up).
    Each message has id, role, content.
    """
    conn_impl = get_connection()
    try:
        if _is_pg():
            if before_id is None:
                cur = conn_impl.execute(
                    "SELECT id, role, content FROM user_messages WHERE user_id = %s ORDER BY id DESC LIMIT %s",
                    (user_id, limit + 1),
                )
            else:
                cur = conn_impl.execute(
                    "SELECT id, role, content FROM user_messages WHERE user_id = %s AND id < %s ORDER BY id DESC LIMIT %s",
                    (user_id, before_id, limit + 1),
                )
            rows = cur.fetchall()
        else:
            conn_impl._conn.row_factory = sqlite3.Row
            if before_id is None:
                cur = conn_impl.execute(
                    "SELECT id, role, content FROM user_messages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                    (user_id, limit + 1),
                )
            else:
                cur = conn_impl.execute(
                    "SELECT id, role, content FROM user_messages WHERE user_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
                    (user_id, before_id, limit + 1),
                )
            rows = cur.fetchall()
        items = [_row_to_dict(r) for r in rows]
        has_more = len(items) > limit
        if has_more:
            items = items[:limit]
        # Reverse so chronological (oldest first) for display
        items = list(reversed(items))
        return items, has_more
    finally:
        conn_impl.close()


def append_messages_for_user(user_id: int, messages: list[dict[str, str]]) -> None:
    if not messages:
        return
    now = datetime.now(timezone.utc).isoformat()
    conn_impl = get_connection()
    try:
        if _is_pg():
            cur = conn_impl._conn.cursor()
            try:
                for m in messages:
                    cur.execute(
                        "INSERT INTO user_messages (user_id, role, content, created_at) VALUES (%s, %s, %s, %s)",
                        (user_id, m["role"], m.get("content", ""), now),
                    )
            finally:
                cur.close()
        else:
            conn_impl._conn.executemany(
                "INSERT INTO user_messages (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                [(user_id, m["role"], m.get("content", ""), now) for m in messages],
            )
        conn_impl.commit()
    finally:
        conn_impl.close()
