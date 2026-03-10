"""
Backend API for the romantic chatbot.
Frontend sends chat content; API returns the bot's reply.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from romatic_chatbot import chat


# --- Request/Response models ---

class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] | None = None


class ChatResponse(BaseModel):
    reply: str
    history: list[dict[str, str]]


# --- App ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Model is loaded on first import of romatic_chatbot; nothing else to do here
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


@app.post("/chat", response_model=ChatResponse)
def post_chat(body: ChatRequest):
    """Receive the user's message (and optional history), return the bot's reply and updated history."""
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="message must be non-empty")
    try:
        history, reply = chat(body.message.strip(), history=body.history)
        return ChatResponse(reply=reply, history=history)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
