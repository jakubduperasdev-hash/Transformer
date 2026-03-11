"""
Backend API for the romantic chatbot.
Chat history is stored per user (session_id) in SQLite.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import db


# --- Request/Response models ---

class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] | None = None
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    history: list[dict[str, str]]
    session_id: str


# --- App ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(
    title="Romantic Chatbot API",
    description="Send a message, get a romantic AI reply.",
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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/history")
def get_history(session_id: str = ""):
    """Return chat history for the given session_id (for restoring after refresh)."""
    if not session_id or not session_id.strip():
        return {"history": []}
    return {"history": db.get_history(session_id.strip())}


@app.post("/chat", response_model=ChatResponse)
def post_chat(body: ChatRequest):
    """Receive the user's message and session_id; load/save history in DB; return reply."""
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="message must be non-empty")
    session_id = (body.session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    try:
        from romatic_chatbot import chat
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Chat model not available. Install torch and transformers.",
        )
    # Load history from DB (ignore body.history so DB is source of truth)
    history = db.get_history(session_id)
    if not history:
        history = None  # let chatbot set system prompt
    try:
        history, reply = chat(body.message.strip(), history=history)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    # Persist user message and assistant reply
    db.append_messages(
        session_id,
        [
            {"role": "user", "content": body.message.strip()},
            {"role": "assistant", "content": reply},
        ],
    )
    return ChatResponse(reply=reply, history=history, session_id=session_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
