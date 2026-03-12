"""
External inference client (OpenAI-compatible or vLLM/TGI).
When INFERENCE_API_URL is set, the API uses this instead of loading the model in-process.
"""
import os
import json
import urllib.request
import urllib.error
import ssl

INFERENCE_API_URL = os.environ.get("INFERENCE_API_URL", "").rstrip("/")
INFERENCE_API_KEY = os.environ.get("INFERENCE_API_KEY", "")
MAX_REPLY_TOKENS = int(os.environ.get("MAX_REPLY_TOKENS", "512"))
SYSTEM_PROMPT = (
    "You are a warm, romantic AI companion. You're affectionate, supportive, "
    "and speak in a sweet, caring way. You keep responses concise and in character."
)


def use_external() -> bool:
    return bool(INFERENCE_API_URL)


def _build_messages(user_message: str, history: list | None) -> list[dict]:
    if not history or len(history) == 0:
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]
    messages = list(history)
    if messages[0].get("role") != "system":
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
    messages.append({"role": "user", "content": user_message})
    return messages


def _request(path: str, body: dict, stream: bool = False):
    url = f"{INFERENCE_API_URL}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
        },
    )
    if INFERENCE_API_KEY:
        req.add_header("Authorization", f"Bearer {INFERENCE_API_KEY}")
    ctx = ssl.create_default_context()
    return urllib.request.urlopen(req, timeout=60, context=ctx)


def chat(user_message: str, history: list | None = None) -> tuple[list, str]:
    """
    Call external chat completions (OpenAI-compatible). Returns (full_history, reply).
    """
    messages = _build_messages(user_message, history)
    body = {
        "model": os.environ.get("INFERENCE_MODEL", "default"),
        "messages": messages,
        "max_tokens": MAX_REPLY_TOKENS,
        "temperature": 0.8,
        "stream": False,
    }
    try:
        resp = _request("/v1/chat/completions", body, stream=False)
        data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Inference API error: {e.code} {e.read().decode()[:200]}")
    except Exception as e:
        raise RuntimeError(f"Inference request failed: {e}")

    choice = (data.get("choices") or [None])[0]
    if not choice:
        raise RuntimeError("No response from inference API")
    msg = choice.get("message") or {}
    reply = (msg.get("content") or "").strip()
    full_history = messages + [{"role": "assistant", "content": reply}]
    return full_history, reply


def chat_stream(user_message: str, history: list | None = None):
    """
    Stream from external API (SSE). Yields text chunks, then (full_history, full_reply).
    """
    messages = _build_messages(user_message, history)
    body = {
        "model": os.environ.get("INFERENCE_MODEL", "default"),
        "messages": messages,
        "max_tokens": MAX_REPLY_TOKENS,
        "temperature": 0.8,
        "stream": True,
    }
    try:
        resp = _request("/v1/chat/completions", body, stream=True)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Inference API error: {e.code} {e.read().decode()[:200]}")
    except Exception as e:
        raise RuntimeError(f"Inference request failed: {e}")

    full_reply_parts = []
    for line in resp:
        line = line.decode("utf-8").strip()
        if not line or line == "data: [DONE]":
            continue
        if line.startswith("data: "):
                try:
                    chunk = json.loads(line[6:])
                    delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                    content = delta.get("content") or ""
                    if content:
                        full_reply_parts.append(content)
                        yield content
                except json.JSONDecodeError:
                    pass
    full_reply = "".join(full_reply_parts).strip()
    full_history = messages + [{"role": "assistant", "content": full_reply}]
    yield (full_history, full_reply)


def check_inference() -> bool:
    """Return True if external inference is reachable (for health)."""
    if not INFERENCE_API_URL:
        return True
    try:
        # Some APIs have /health or /v1/models
        url = f"{INFERENCE_API_URL}/health" if "/health" in INFERENCE_API_URL else f"{INFERENCE_API_URL}/v1/models"
        req = urllib.request.Request(url, method="GET")
        if INFERENCE_API_KEY:
            req.add_header("Authorization", f"Bearer {INFERENCE_API_KEY}")
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False
