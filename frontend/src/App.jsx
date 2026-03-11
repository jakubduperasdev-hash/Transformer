import { useState, useRef, useEffect } from "react";

const API_BASE = "/api";
const SESSION_KEY = "romantic_chat_session_id";

function getOrCreateSessionId() {
  let id = localStorage.getItem(SESSION_KEY);
  if (!id && typeof crypto !== "undefined" && crypto.randomUUID) {
    id = crypto.randomUUID();
    localStorage.setItem(SESSION_KEY, id);
  }
  if (!id) {
    id = "session-" + Date.now() + "-" + Math.random().toString(36).slice(2);
    localStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

export default function App() {
  const [input, setInput] = useState("");
  const [history, setHistory] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const messagesEndRef = useRef(null);

  const messages = history
    ? history.filter((m) => m.role !== "system")
    : [];

  useEffect(() => {
    setSessionId(getOrCreateSessionId());
  }, []);

  useEffect(() => {
    if (!sessionId) return;
    fetch(`${API_BASE}/history?session_id=${encodeURIComponent(sessionId)}`)
      .then((res) => res.json())
      .then((data) => {
        if (data.history && data.history.length > 0) {
          setHistory(data.history);
        }
      })
      .catch(() => {});
  }, [sessionId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, loading]);

  async function handleSend() {
    const text = input.trim();
    if (!text || loading) return;

    setLoading(true);
    setError(null);
    setInput("");

    if (!sessionId) {
      setError("Session not ready. Please wait.");
      setInput(text);
      setLoading(false);
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "Request failed");
      }

      const data = await res.json();
      setHistory(data.history);
      if (data.session_id) setSessionId(data.session_id);
    } catch (e) {
      setError(e.message);
      setInput(text);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="app">
      <header className="header">
        <h1>Romantic Chatbot</h1>
      </header>

      <div className="messages">
        {messages.length === 0 && (
          <p className="placeholder">Say something to start the conversation.</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`message message--${m.role}`}>
            <span className="message-role">{m.role === "user" ? "You" : "Bot"}</span>
            <p className="message-content">{m.content}</p>
          </div>
        ))}
        {loading && (
          <div className="message message--assistant">
            <span className="message-role">Bot</span>
            <p className="message-content typing">...</p>
          </div>
        )}
        <div ref={messagesEndRef} aria-hidden="true" />
      </div>

      {error && <p className="error">{error}</p>}

      <div className="input-row">
        <input
          type="text"
          className="input"
          placeholder="Type your message..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading}
        />
        <button
          type="button"
          className="send-btn"
          onClick={handleSend}
          disabled={loading || !input.trim()}
        >
          Send
        </button>
      </div>
    </div>
  );
}
