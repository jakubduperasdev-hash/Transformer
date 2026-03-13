"""
Backend API for the romantic chatbot.
Production-ready: tenants, audit log, GDPR delete/export, rate limiting, health check.
"""
import os
from dotenv import load_dotenv
load_dotenv()  # load .env before db reads DATABASE_URL

import json
import re
import threading
import time
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi import APIRouter
from pydantic import BaseModel
import jwt
from passlib.context import CryptContext

import db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# --- Auth config ---
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = "HS256"
JWT_ACCESS_EXPIRY_MINUTES = int(os.environ.get("JWT_ACCESS_EXPIRY_MINUTES", "15"))
JWT_REFRESH_DAYS = int(os.environ.get("JWT_REFRESH_DAYS", "7"))
pwd_ctx = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
security = HTTPBearer(auto_error=False)

# --- Rate limit (Redis when REDIS_URL set, else in-memory) ---
RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", "120"))
RATE_LIMIT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", "60"))
REDIS_URL = os.environ.get("REDIS_URL")
# Per-tenant daily quotas (0 = no limit). Enforced before chat/stream.
TENANT_DAILY_TOKEN_LIMIT = int(os.environ.get("TENANT_DAILY_TOKEN_LIMIT", "0"))
TENANT_DAILY_REQUEST_LIMIT = int(os.environ.get("TENANT_DAILY_REQUEST_LIMIT", "0"))
_rate_store: dict = {}

_redis_client = None
def _get_redis():
    global _redis_client
    if _redis_client is None and REDIS_URL:
        try:
            import redis
            _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        except Exception:
            _redis_client = False
    return _redis_client if _redis_client else None


def _rate_limit_key(user_id: int) -> str:
    return f"rl:user:{user_id}"


def check_rate_limit(user_id: int) -> None:
    """Raise 429 if user exceeded rate limit."""
    r = _get_redis()
    key = _rate_limit_key(user_id)
    if r:
        try:
            n = r.incr(key)
            if n == 1:
                r.expire(key, RATE_LIMIT_WINDOW)
            if n > RATE_LIMIT_REQUESTS:
                raise HTTPException(status_code=429, detail="Too many requests; try again later.")
        except HTTPException:
            raise
        except Exception:
            pass
        return
    now = time.time()
    if key not in _rate_store:
        _rate_store[key] = (1, now)
        return
    count, start = _rate_store[key]
    if now - start >= RATE_LIMIT_WINDOW:
        _rate_store[key] = (1, now)
        return
    count += 1
    _rate_store[key] = (count, start)
    if count > RATE_LIMIT_REQUESTS:
        raise HTTPException(status_code=429, detail="Too many requests; try again later.")


def check_tenant_quota(tenant_id: int) -> None:
    """Raise 429 if tenant has exceeded daily token or request quota."""
    if TENANT_DAILY_TOKEN_LIMIT <= 0 and TENANT_DAILY_REQUEST_LIMIT <= 0:
        return
    req_count, token_count = db.get_tenant_daily_usage(tenant_id)
    if TENANT_DAILY_REQUEST_LIMIT > 0 and req_count >= TENANT_DAILY_REQUEST_LIMIT:
        raise HTTPException(status_code=429, detail="Daily request quota exceeded for your organization.")
    if TENANT_DAILY_TOKEN_LIMIT > 0 and token_count >= TENANT_DAILY_TOKEN_LIMIT:
        raise HTTPException(status_code=429, detail="Daily token quota exceeded for your organization.")


# --- Metrics (Prometheus) ---
_metrics_lock = threading.Lock()
_http_requests: dict[tuple[str, str, int], int] = {}  # (method, path, status) -> count
_http_duration_sum: dict[tuple[str, str], float] = {}  # (method, path) -> sum seconds
_http_duration_count: dict[tuple[str, str], int] = {}
_chat_tokens_total: int = 0
_chat_errors_total: int = 0


def _record_request(method: str, path: str, status: int, duration_sec: float) -> None:
    with _metrics_lock:
        key = (method, path, status)
        _http_requests[key] = _http_requests.get(key, 0) + 1
        key_d = (method, path)
        _http_duration_sum[key_d] = _http_duration_sum.get(key_d, 0) + duration_sec
        _http_duration_count[key_d] = _http_duration_count.get(key_d, 0) + 1


def record_chat_tokens(tokens: int) -> None:
    with _metrics_lock:
        global _chat_tokens_total
        _chat_tokens_total += tokens


def record_chat_error() -> None:
    with _metrics_lock:
        global _chat_errors_total
        _chat_errors_total += 1


# --- Request/Response models ---

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    tenant_id: int | None = None  # optional; if provided, user joins this tenant (must exist)
    consent_at: str | None = None  # optional; ISO timestamp when user gave consent (GDPR)
    lawful_basis: str | None = None  # optional; e.g. "consent", "contract", "legitimate_interest" (GDPR)


class LoginRequest(BaseModel):
    username: str  # or email
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    history: list[dict[str, str]]


# --- App ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield
    log.info("Shutting down gracefully...")
    import asyncio
    await asyncio.sleep(1)


app = FastAPI(
    title="Romantic Chatbot API",
    description="Sign up, log in, then chat. History is stored per user.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_and_log(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    _record_request(request.method, request.url.path, response.status_code, duration)
    log.info(
        json.dumps({
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round(duration * 1000),
        })
    )
    response.headers["X-Request-ID"] = request_id
    return response


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(
            credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM]
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = db.get_user_by_id(int(user_id))
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# --- Router with /api prefix (matches frontend and proxy) ---
api = APIRouter(prefix="/api", tags=["api"])


@api.get("/tenants")
def list_tenants():
    """Return all tenants (id, name). Use tenant_id in POST /register to assign user to a tenant."""
    return {"tenants": db.list_tenants()}


@api.post("/register")
def register(body: RegisterRequest):
    """Create a new user. Optionally pass tenant_id to join a specific tenant (from GET /tenants). Then use /login to get a token."""
    username = (body.username or "").strip()
    email = (body.email or "").strip().lower()
    password = body.password or ""
    tenant_id = body.tenant_id if body.tenant_id is not None else db.DEFAULT_TENANT_ID
    if not username or len(username) < 2:
        raise HTTPException(status_code=400, detail="Username must be at least 2 characters")
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email required")
    if not password or len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    tenant = db.get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=400, detail="Invalid tenant")
    if db.get_user_by_username(username, tenant_id=tenant_id):
        raise HTTPException(status_code=400, detail="Username already taken in this organization")
    if db.get_user_by_email(email):
        raise HTTPException(status_code=400, detail="Email already registered")
    try:
        password_hash = pwd_ctx.hash(password)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Password hashing failed")
    consent_at = (body.consent_at or "").strip() or None
    lawful_basis = (body.lawful_basis or "").strip() or None
    try:
        user_id = db.create_user(
            username, email, password_hash,
            tenant_id=tenant_id,
            consent_at=consent_at,
            lawful_basis=lawful_basis,
        )
    except Exception as e:
        err = str(e).lower()
        if "unique" in err or "duplicate" in err or "integrity" in err:
            raise HTTPException(status_code=400, detail="Username or email already taken")
        raise HTTPException(status_code=500, detail=str(e))
    return {"id": int(user_id), "username": username, "email": email}


def _make_access_token(user_id: int) -> tuple[str, int]:
    """Return (jwt_string, expires_in_seconds)."""
    from datetime import datetime, timezone, timedelta
    exp = datetime.now(timezone.utc) + timedelta(minutes=JWT_ACCESS_EXPIRY_MINUTES)
    payload = {"sub": str(user_id), "exp": exp}
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token, JWT_ACCESS_EXPIRY_MINUTES * 60


@api.post("/login")
def login(body: LoginRequest):
    """Return short-lived access token, refresh token, and user info. Use access token in Authorization: Bearer <token>."""
    identifier = (body.username or "").strip()
    password = body.password or ""
    if not identifier or not password:
        raise HTTPException(status_code=400, detail="Username and password required")
    try:
        user = db.get_user_by_username(identifier) or db.get_user_by_email(identifier)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not pwd_ctx.verify(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    try:
        access_token, expires_in = _make_access_token(int(user["id"]))
        from datetime import datetime, timezone, timedelta
        refresh_expires = (datetime.now(timezone.utc) + timedelta(days=JWT_REFRESH_DAYS)).isoformat()
        refresh_token = db.create_refresh_token(int(user["id"]), refresh_expires)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Token creation failed")
    tenant_id = user.get("tenant_id") or db.DEFAULT_TENANT_ID
    db.audit_log(tenant_id, int(user["id"]), "login", None)
    return {
        "token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "user": {"id": int(user["id"]), "username": str(user["username"]), "email": str(user["email"])},
    }


@api.post("/refresh")
def refresh(body: RefreshRequest):
    """Exchange a valid refresh_token for a new access token. Optional: pass refresh_token in body to rotate."""
    plain = (body.refresh_token or "").strip()
    if not plain:
        raise HTTPException(status_code=400, detail="refresh_token required")
    user = db.get_user_by_refresh_token(plain)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    try:
        access_token, expires_in = _make_access_token(int(user["id"]))
        # Optional rotation: issue new refresh token and revoke old (uncomment to enable)
        # new_refresh = db.create_refresh_token(int(user["id"]), (datetime.now(timezone.utc) + timedelta(days=JWT_REFRESH_DAYS)).isoformat())
        # db.revoke_refresh_token(plain)
        # return {"token": access_token, "refresh_token": new_refresh, "expires_in": expires_in}
        return {"token": access_token, "expires_in": expires_in}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Token creation failed")


@api.get("/me")
def me(current_user: dict = Depends(get_current_user)):
    """Return current user info (requires valid token)."""
    return {"id": int(current_user["id"]), "username": str(current_user["username"]), "email": str(current_user["email"])}


@api.delete("/users/me")
def delete_me(current_user: dict = Depends(get_current_user)):
    """GDPR: Delete my account and all my data (right to erasure)."""
    user = db.delete_user_data(int(current_user["id"]))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "Account and all associated data have been deleted."}


@api.get("/users/me/export")
def export_me(current_user: dict = Depends(get_current_user)):
    """GDPR: Export all my data (data portability)."""
    data = db.export_user_data(int(current_user["id"]))
    if not data:
        raise HTTPException(status_code=404, detail="User not found")
    tenant_id = current_user.get("tenant_id") or db.DEFAULT_TENANT_ID
    db.audit_log(tenant_id, int(current_user["id"]), "export_data", None)
    return data


@api.get("/health")
def health():
    """Liveness/readiness: DB required; inference optional when external."""
    if not db.check_connection():
        return JSONResponse(status_code=503, content={"status": "unhealthy", "db": "down"})
    payload = {"status": "ok", "db": "up"}
    try:
        from inference_client import use_external, check_inference
        if use_external():
            if not check_inference():
                return JSONResponse(status_code=503, content={"status": "unhealthy", "db": "up", "inference": "down"})
            payload["inference"] = "up"
        else:
            payload["inference"] = "local"
    except Exception:
        payload["inference"] = "local"
    return payload


@api.get("/history")
def get_history(
    current_user: dict = Depends(get_current_user),
    limit: int = 20,
    before_id: int | None = None,
):
    """Return chat history for the logged-in user. Paginated: initial load gets recent messages; use before_id to load older (e.g. on scroll up)."""
    check_rate_limit(int(current_user["id"]))
    limit = min(max(1, limit), 100)
    history, has_more = db.get_history_paginated(int(current_user["id"]), limit=limit, before_id=before_id)
    return {"history": history, "has_more": has_more}


def _strip_incomplete_list_item(text: str) -> str:
    """Remove a trailing incomplete list marker (e.g. bare '6' or '6.') so it is not shown."""
    if not text or not text.strip():
        return text
    # Trailing newline(s) + optional space + digits + optional . or ) + optional space
    return re.sub(r"\n\s*\d+[.)]?\s*$", "", text).rstrip()


# Cap history length to reduce latency for long conversations (0 = no limit). Applies to internal and external inference.
CHAT_MAX_HISTORY_MESSAGES = int(os.environ.get("CHAT_MAX_HISTORY_MESSAGES", "0"))
# When truncating, keep this many messages from the start (so user preferences / "how I like to chat" are not dropped).
CHAT_KEEP_FIRST_MESSAGES = int(os.environ.get("CHAT_KEEP_FIRST_MESSAGES", "4"))


def _truncate_history(history: list | None) -> list | None:
    """Cap to CHAT_MAX_HISTORY_MESSAGES but keep the first CHAT_KEEP_FIRST_MESSAGES so preferences aren't lost. Full history still in DB."""
    if not history or CHAT_MAX_HISTORY_MESSAGES <= 0:
        return history
    if history[0].get("role") == "system":
        system_part = [history[0]]
        rest = history[1:]
    else:
        system_part = []
        rest = history
    if len(rest) <= CHAT_MAX_HISTORY_MESSAGES:
        return history
    keep_first = min(CHAT_KEEP_FIRST_MESSAGES, CHAT_MAX_HISTORY_MESSAGES)
    tail_size = CHAT_MAX_HISTORY_MESSAGES - keep_first
    if tail_size <= 0:
        return system_part + rest[:CHAT_MAX_HISTORY_MESSAGES]
    # First K messages (preferences / early context) + last (N - K) messages (recent context).
    return system_part + rest[:keep_first] + rest[-tail_size:]


def _run_chat(user_message: str, history: list | None) -> tuple[list, str]:
    """Use external inference if INFERENCE_API_URL set, else local model."""
    try:
        from inference_client import use_external, chat as chat_ext, chat_stream as chat_stream_ext
    except ImportError:
        use_external = lambda: False
    if use_external():
        return chat_ext(user_message, history)
    from romatic_chatbot import chat
    return chat(user_message, history)


def _orchestrator():
    """Lazy singleton for Agent Orchestrator (Prompt Builder, Memory, Tools, Planning -> LLM Core)."""
    try:
        from agent import AgentOrchestrator
        return AgentOrchestrator()
    except ImportError:
        return None


AGENT_ORCHESTRATOR_ENABLED = os.environ.get("AGENT_ORCHESTRATOR_ENABLED", "").strip().lower() in ("1", "true", "yes")


@api.post("/chat", response_model=ChatResponse)
def post_chat(body: ChatRequest, current_user: dict = Depends(get_current_user)):
    """Send a message and get a reply. Uses Agent Orchestrator when AGENT_ORCHESTRATOR_ENABLED=1."""
    check_rate_limit(int(current_user["id"]))
    tenant_id = current_user.get("tenant_id") or db.DEFAULT_TENANT_ID
    check_tenant_quota(tenant_id)
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="message must be non-empty")
    user_id = current_user["id"]
    msg = body.message.strip()
    try:
        if AGENT_ORCHESTRATOR_ENABLED:
            orch = _orchestrator()
            if orch:
                history, reply = orch.chat(user_id, msg)
            else:
                history = _truncate_history(db.get_history_by_user(user_id))
                history, reply = _run_chat(msg, history=history)
                reply = _strip_incomplete_list_item(reply)
                if history:
                    history = history[:-1] + [{"role": "assistant", "content": reply}]
                db.append_messages_for_user(user_id, [{"role": "user", "content": msg}, {"role": "assistant", "content": reply}])
        else:
            history = _truncate_history(db.get_history_by_user(user_id))
            if not history:
                history = None
            history, reply = _run_chat(msg, history=history)
            reply = _strip_incomplete_list_item(reply)
            if history:
                history = history[:-1] + [{"role": "assistant", "content": reply}]
            db.append_messages_for_user(user_id, [{"role": "user", "content": msg}, {"role": "assistant", "content": reply}])
    except ImportError:
        record_chat_error()
        raise HTTPException(status_code=503, detail="Chat not available. Set INFERENCE_API_URL or install torch and transformers.")
    except Exception as e:
        record_chat_error()
        raise HTTPException(status_code=500, detail=str(e))
    approx_tokens = (len(msg) + len(reply)) // 4
    db.record_usage(tenant_id, request_delta=1, token_delta=approx_tokens)
    record_chat_tokens(approx_tokens)
    return ChatResponse(reply=reply, history=history)


def _run_chat_stream(user_message: str, history: list | None):
    """Stream from external inference or local model."""
    try:
        from inference_client import use_external, chat_stream as chat_stream_ext
    except ImportError:
        use_external = lambda: False
    if use_external():
        return chat_stream_ext(user_message, history)
    from romatic_chatbot import chat_stream
    return chat_stream(user_message, history)


@api.post("/chat/stream")
def post_chat_stream(body: ChatRequest, current_user: dict = Depends(get_current_user)):
    """Stream the reply token-by-token (NDJSON: each line is {"chunk": "..."} or {"done": true, "history": [...]}). Uses Agent Orchestrator when AGENT_ORCHESTRATOR_ENABLED=1."""
    check_rate_limit(int(current_user["id"]))
    tenant_id = current_user.get("tenant_id") or db.DEFAULT_TENANT_ID
    check_tenant_quota(tenant_id)
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="message must be non-empty")
    user_id = current_user["id"]
    msg = body.message.strip()

    def generate():
        try:
            if AGENT_ORCHESTRATOR_ENABLED:
                orch = _orchestrator()
                if orch:
                    for value in orch.chat_stream(user_id, msg):
                        if isinstance(value, tuple):
                            full_history, full_reply = value
                            full_reply = _strip_incomplete_list_item(full_reply)
                            if full_history:
                                full_history = full_history[:-1] + [{"role": "assistant", "content": full_reply}]
                            approx_tokens = (len(msg) + len(full_reply)) // 4
                            db.record_usage(tenant_id, request_delta=1, token_delta=approx_tokens)
                            record_chat_tokens(approx_tokens)
                            yield json.dumps({"done": True, "history": full_history}) + "\n"
                        else:
                            yield json.dumps({"chunk": value}) + "\n"
                    return
            history = _truncate_history(db.get_history_by_user(user_id))
            if not history:
                history = None
            for value in _run_chat_stream(msg, history=history):
                if isinstance(value, tuple):
                    full_history, full_reply = value
                    full_reply = _strip_incomplete_list_item(full_reply)
                    if full_history:
                        full_history = full_history[:-1] + [{"role": "assistant", "content": full_reply}]
                    db.append_messages_for_user(user_id, [{"role": "user", "content": msg}, {"role": "assistant", "content": full_reply}])
                    approx_tokens = (len(msg) + len(full_reply)) // 4
                    db.record_usage(tenant_id, request_delta=1, token_delta=approx_tokens)
                    record_chat_tokens(approx_tokens)
                    yield json.dumps({"done": True, "history": full_history}) + "\n"
                else:
                    yield json.dumps({"chunk": value}) + "\n"
        except ImportError:
            record_chat_error()
            yield json.dumps({"error": "Chat not available. Set INFERENCE_API_URL or install torch and transformers."}) + "\n"
        except Exception as e:
            record_chat_error()
            yield json.dumps({"error": str(e)}) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app.include_router(api)


@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    """Prometheus metrics for latency, request counts, and chat tokens."""
    with _metrics_lock:
        lines = [
            "# HELP http_requests_total Total HTTP requests by method, path, status.",
            "# TYPE http_requests_total counter",
        ]
        for (method, path, status), count in sorted(_http_requests.items()):
            m, p, s = method.replace('"', '\\"'), path.replace('"', '\\"'), status
            lines.append(f'http_requests_total{{method="{m}",path="{p}",status="{s}"}} {count}')
        lines.extend([
            "# HELP http_request_duration_seconds_sum Sum of request durations by method, path.",
            "# TYPE http_request_duration_seconds_sum counter",
        ])
        for (method, path), s in sorted(_http_duration_sum.items()):
            m, p = method.replace('"', '\\"'), path.replace('"', '\\"')
            lines.append(f'http_request_duration_seconds_sum{{method="{m}",path="{p}"}} {s:.6f}')
        lines.extend([
            "# HELP http_request_duration_seconds_count Request count by method, path.",
            "# TYPE http_request_duration_seconds_count counter",
        ])
        for (method, path), c in sorted(_http_duration_count.items()):
            m, p = method.replace('"', '\\"'), path.replace('"', '\\"')
            lines.append(f'http_request_duration_seconds_count{{method="{m}",path="{p}"}} {c}')
        lines.extend([
            "# HELP chat_tokens_total Total tokens used in chat (approximate).",
            "# TYPE chat_tokens_total counter",
            f"chat_tokens_total {_chat_tokens_total}",
            "# HELP chat_errors_total Total chat request errors.",
            "# TYPE chat_errors_total counter",
            f"chat_errors_total {_chat_errors_total}",
        ])
    return "\n".join(lines) + "\n"


@app.exception_handler(Exception)
def unhandled_exception_handler(request: Request, exc: Exception):
    """Return 500 with error detail for unhandled exceptions."""
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    log.exception("Unhandled exception")
    return JSONResponse(status_code=500, content={"detail": str(exc)})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
