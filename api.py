"""
Backend API for the romantic chatbot.
Users must sign up and log in; chat history is stored per user in SQLite.
"""
import os
import sqlite3
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi import APIRouter
from pydantic import BaseModel
import jwt
from passlib.context import CryptContext

import db

# --- Auth config ---
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = "HS256"
pwd_ctx = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
security = HTTPBearer(auto_error=False)

# --- Request/Response models ---

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class LoginRequest(BaseModel):
    username: str  # or email
    password: str


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


@api.post("/register")
def register(body: RegisterRequest):
    """Create a new user. Then use /login to get a token."""
    username = (body.username or "").strip()
    email = (body.email or "").strip().lower()
    password = body.password or ""
    if not username or len(username) < 2:
        raise HTTPException(status_code=400, detail="Username must be at least 2 characters")
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email required")
    if not password or len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if db.get_user_by_username(username):
        raise HTTPException(status_code=400, detail="Username already taken")
    if db.get_user_by_email(email):
        raise HTTPException(status_code=400, detail="Email already registered")
    try:
        password_hash = pwd_ctx.hash(password)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Password hashing failed")
    try:
        user_id = db.create_user(username, email, password_hash)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Username or email already taken")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"id": int(user_id), "username": username, "email": email}


@api.post("/login")
def login(body: LoginRequest):
    """Return a JWT and user info. Use the token in Authorization: Bearer <token>."""
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
        token = jwt.encode(
            {"sub": str(user["id"])},
            JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Token creation failed")
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return {
        "token": token,
        "user": {"id": int(user["id"]), "username": str(user["username"]), "email": str(user["email"])},
    }


@api.get("/me")
def me(current_user: dict = Depends(get_current_user)):
    """Return current user info (requires valid token)."""
    return {"id": int(current_user["id"]), "username": str(current_user["username"]), "email": str(current_user["email"])}


@api.get("/health")
def health():
    return {"status": "ok"}


@api.get("/history")
def get_history(current_user: dict = Depends(get_current_user)):
    """Return chat history for the logged-in user."""
    history = db.get_history_by_user(current_user["id"])
    return {"history": history}


@api.post("/chat", response_model=ChatResponse)
def post_chat(body: ChatRequest, current_user: dict = Depends(get_current_user)):
    """Send a message and get a reply. History is loaded/saved for the logged-in user."""
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="message must be non-empty")
    try:
        from romatic_chatbot import chat
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Chat model not available. Install torch and transformers.",
        )
    user_id = current_user["id"]
    history = db.get_history_by_user(user_id)
    if not history:
        history = None
    try:
        history, reply = chat(body.message.strip(), history=history)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    db.append_messages_for_user(
        user_id,
        [
            {"role": "user", "content": body.message.strip()},
            {"role": "assistant", "content": reply},
        ],
    )
    return ChatResponse(reply=reply, history=history)


app.include_router(api)


@app.exception_handler(Exception)
def unhandled_exception_handler(request, exc):
    """Return 500 with error detail for unhandled exceptions."""
    from fastapi.responses import JSONResponse
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return JSONResponse(status_code=500, content={"detail": str(exc)})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
