import { useState } from "react";

const API_BASE = "/api";

export default function App() {
  const [input, setInput] = useState("");
  const [history, setHistory] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const messages = history
    ? history.filter((m) => m.role !== "system")
    : [];

  async function handleSend() {
    const text = input.trim();
    if (!text || loading) return;

    setLoading(true);
    setError(null);
    setInput("");

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history }),
      });

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
