# Agent Architecture (Full-Stack)

This project implements the **High-Level Full-Stack Agent Architecture**: User → API/Gateway → **Agent Orchestrator** → (Prompt Builder, Memory Manager, Tool Executor, Planning) → **LLM Core**.

LLMs are stateless; the orchestrator and its components manage **memory**, **context**, and **actions**.

## Components

| Component | Role | Location |
|-----------|------|----------|
| **API / Gateway** | Auth, rate limit, quota; routes to Orchestrator or legacy chat | `api.py` |
| **Agent Orchestrator** | Coordinates Memory, Prompt Builder, Tools, Planning; calls LLM Core | `agent/orchestrator.py` |
| **Prompt Builder** | Builds messages: system + preferences + RAG context + history + new user message | `agent/prompt_builder.py` |
| **Memory Manager** | Loads/saves conversation history (Structured DB); truncates with keep-first | `agent/memory.py` |
| **Tool Executor** | Runs tools (e.g. `get_current_time`, `simple_calc`) | `agent/tools.py` |
| **Planning** | Optional: decides if a tool is needed and injects result into context | `agent/planning.py` |
| **RAG** | Placeholder: retrieve relevant context from Vector DB (set `RAG_ENABLED=1` when implemented) | `agent/rag.py` |
| **LLM Core** | One-shot and stream completion; uses external inference or local model | `agent/llm_core.py` → `inference_client` / `romatic_chatbot` |

## Enabling the orchestrator

Set in `.env`:

```env
AGENT_ORCHESTRATOR_ENABLED=1
```

When enabled, `POST /api/chat` and `POST /api/chat/stream` go through the orchestrator. When disabled, the legacy path (direct history + LLM) is used.

## Flow (orchestrator enabled)

1. **Memory Manager** loads truncated history and optional preferences summary.
2. **RAG** (if enabled) retrieves relevant chunks for the user/query.
3. **Planning** may detect tool use (e.g. “what time is it” → `get_current_time`); **Tool Executor** runs the tool; result is injected into the user message.
4. **Prompt Builder** builds the message list: system + preferences + RAG + history + (possibly tool-augmented) user message.
5. **LLM Core** runs completion (internal or external inference).
6. **Memory Manager** appends the turn to the Structured DB.

## Extending

- **Tools**: Register in `agent/tools.py` with `@register_tool("name")` and add planning logic in `agent/planning.py` or use LLM-based function calling later.
- **RAG**: Implement `agent/rag.retrieve()` with a vector store (e.g. pgvector, Chroma) and set `RAG_ENABLED=1`.
- **Structured DB**: User data, tenants, and chat history remain in `db.py`; Memory Manager reads/writes via `db.get_history_by_user` and `db.append_messages_for_user`.
