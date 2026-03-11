import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { getToken, authHeaders, clearToken } from "./auth";

const API_BASE = "/api";

export default function Chat() {
  const [input, setInput] = useState("");
  const [history, setHistory] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [user, setUser] = useState(null);
  const messagesEndRef = useRef(null);
  const navigate = useNavigate();

  const messages = history
    ? history.filter((m) => m.role !== "system")
    : [];

  useEffect(() => {
    const token = getToken();
    if (!token) {
      navigate("/login", { replace: true });
      return;
    }
    fetch(`${API_BASE}/me`, { headers: authHeaders() })
      .then((res) => {
        if (res.status === 401) {
          clearToken();
          navigate("/login", { replace: true });
          return null;
        }
        return res.json();
      })
      .then((data) => {
        if (data) setUser(data);
      })
      .catch(() => navigate("/login", { replace: true }));
  }, [navigate]);

  useEffect(() => {
    if (!user) return;
    fetch(`${API_BASE}/history`, { headers: authHeaders() })
      .then((res) => res.json())
      .then((data) => {
        if (data.history && data.history.length > 0) {
          setHistory(data.history);
        }
      })
      .catch(() => {});
  }, [user]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, loading]);

  async function handleSend() {
    const text = input.trim();
    if (!text || loading) return;

    setLoading(true);
    setError(null);
    setInput("");

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ message: text }),
      });

      if (res.status === 401) {
        clearToken();
        navigate("/login", { replace: true });
        return;
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "Request failed");
      }

      const data = await res.json();
      setHistory(data.history);
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

  function handleLogout() {
    clearToken();
    navigate("/login", { replace: true });
  }

  if (!user) {
    return (
      <div className="app">
        <p className="placeholder">Loading…</p>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="header">
        <h1>Romantic Chatbot</h1>
        <div className="header-user">
          <span className="header-username">{user.username}</span>
          <button type="button" className="logout-btn" onClick={handleLogout}>
            Log out
          </button>
        </div>
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
