import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { getToken, authHeaders, clearToken } from "./auth";

const API_BASE = "/api";
const HISTORY_PAGE_SIZE = 20;

function mergeHistoryWithIds(prev, next) {
  if (!prev || prev.length === 0) return next || [];
  if (!next || next.length === 0) return prev || [];
  const used = new Set();
  return next.map((m) => {
    const fromPrev = prev.find((p, i) => p.role === m.role && p.content === m.content && !used.has(i));
    if (fromPrev && fromPrev.id != null) {
      used.add(prev.indexOf(fromPrev));
      return { ...m, id: fromPrev.id };
    }
    return m;
  });
}

export default function Chat() {
  const [input, setInput] = useState("");
  const [history, setHistory] = useState(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [streamingReply, setStreamingReply] = useState("");
  const [error, setError] = useState(null);
  const [user, setUser] = useState(null);
  const messagesEndRef = useRef(null);
  const messagesContainerRef = useRef(null);
  const scrollRestoreRef = useRef(null);
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
    fetch(`${API_BASE}/history?limit=${HISTORY_PAGE_SIZE}`, { headers: authHeaders() })
      .then((res) => res.json())
      .then((data) => {
        if (data.history && data.history.length > 0) {
          setHistory(data.history);
        } else {
          setHistory([]);
        }
        setHasMore(data.has_more === true);
      })
      .catch(() => setHistory([]));
  }, [user]);

  function loadMore() {
    if (!user || loadingMore || !hasMore) return;
    const oldest = history && history.length > 0 ? history[0] : null;
    const beforeId = oldest && oldest.id != null ? oldest.id : null;
    if (beforeId == null) return;
    const el = messagesContainerRef.current;
    if (el) scrollRestoreRef.current = { scrollHeight: el.scrollHeight, scrollTop: el.scrollTop };
    setLoadingMore(true);
    fetch(`${API_BASE}/history?limit=${HISTORY_PAGE_SIZE}&before_id=${beforeId}`, { headers: authHeaders() })
      .then((res) => res.json())
      .then((data) => {
        if (data.history && data.history.length > 0) {
          setHistory((prev) => (prev ? [...data.history, ...prev] : data.history));
        }
        setHasMore(data.has_more === true);
      })
      .catch(() => {})
      .finally(() => setLoadingMore(false));
  }

  useEffect(() => {
    if (scrollRestoreRef.current && messagesContainerRef.current) {
      const el = messagesContainerRef.current;
      const { scrollHeight: oldHeight, scrollTop: oldTop } = scrollRestoreRef.current;
      scrollRestoreRef.current = null;
      requestAnimationFrame(() => {
        if (el && el.scrollHeight > oldHeight) {
          el.scrollTop = el.scrollHeight - oldHeight + oldTop;
        }
      });
    }
  }, [history]);

  const SCROLL_LOAD_THRESHOLD = 80;
  function handleMessagesScroll() {
    const el = messagesContainerRef.current;
    if (!el || loadingMore || !hasMore) return;
    const oldest = history && history.length > 0 ? history[0] : null;
    if (!oldest || oldest.id == null) return;
    if (el.scrollTop <= SCROLL_LOAD_THRESHOLD) loadMore();
  }

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, loading, streamingReply]);

  async function handleSend() {
    const text = input.trim();
    if (!text || loading) return;

    setLoading(true);
    setError(null);
    setStreamingReply("");
    setInput("");
    // Show user message immediately
    setHistory((prev) => [
      ...(prev || []).filter((m) => m.role !== "system"),
      { role: "user", content: text },
    ]);

    try {
      const res = await fetch(`${API_BASE}/chat/stream`, {
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

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const data = JSON.parse(line);
            if (data.error) throw new Error(data.error);
            if (data.chunk !== undefined) setStreamingReply((s) => s + data.chunk);
            if (data.done && data.history) setHistory((prev) => mergeHistoryWithIds(prev, data.history));
          } catch (e) {
            if (e instanceof SyntaxError) continue;
            throw e;
          }
        }
      }
      if (buffer.trim()) {
        try {
          const data = JSON.parse(buffer);
          if (data.error) throw new Error(data.error);
          if (data.chunk !== undefined) setStreamingReply((s) => s + data.chunk);
          if (data.done && data.history) setHistory((prev) => mergeHistoryWithIds(prev, data.history));
        } catch (e) {
          if (!(e instanceof SyntaxError)) throw e;
        }
      }
    } catch (e) {
      setError(e.message);
      setHistory((prev) => prev && prev.length > 0 ? prev.slice(0, -1) : prev);
    } finally {
      setLoading(false);
      setStreamingReply("");
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

      <div
        ref={messagesContainerRef}
        className="messages"
        onScroll={handleMessagesScroll}
      >
        {loadingMore && (
          <p className="placeholder load-more-placeholder">Loading older messages…</p>
        )}
        {messages.length === 0 && !hasMore && !loadingMore && (
          <p className="placeholder">Say something to start the conversation.</p>
        )}
        {messages.map((m, i) => (
          <div key={m.id != null ? m.id : `msg-${i}`} className={`message message--${m.role}`}>
            <span className="message-role">{m.role === "user" ? "You" : "Bot"}</span>
            <p className="message-content">{m.content}</p>
          </div>
        ))}
        {loading && (
          <div className="message message--assistant">
            <span className="message-role">Bot</span>
            <p className="message-content">
              {streamingReply || <span className="typing">...</span>}
            </p>
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
