"""
Agent Orchestrator: coordinates Prompt Builder, Memory Manager, Tool Executor, Planning, and LLM Core.
"""
from typing import Any

from .memory import MemoryManager
from .prompt_builder import PromptBuilder
from .tools import ToolExecutor
from .planning import should_use_tool, inject_tool_result_into_message
from .rag import retrieve
from . import llm_core


class AgentOrchestrator:
    """
    Full-stack agent: User -> API/Gateway -> Orchestrator -> (Prompt Builder, Memory, Tools, Planning) -> LLM Core.
    """

    def __init__(
        self,
        memory: MemoryManager | None = None,
        prompt_builder: PromptBuilder | None = None,
        tool_executor: ToolExecutor | None = None,
        use_tools: bool = True,
        use_rag: bool = True,
    ):
        self.memory = memory or MemoryManager()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.tool_executor = tool_executor or ToolExecutor()
        self.use_tools = use_tools
        self.use_rag = use_rag

    def chat(self, user_id: int, user_message: str) -> tuple[list[dict[str, str]], str]:
        """
        Run one turn: get context, optionally run a tool, build prompt, call LLM, persist to memory.
        Returns (full_history_for_response, reply).
        """
        user_message = (user_message or "").strip()
        if not user_message:
            return self.memory.get_context(user_id), ""

        # 1) Memory Manager: get context
        history = self.memory.get_context(user_id)
        preferences = self.memory.get_preferences_summary(user_id) if self.use_rag else None
        rag_context = retrieve(user_id, user_message, k=3) if self.use_rag else None

        # 2) Planning: optional tool use
        final_user_message = user_message
        if self.use_tools:
            tool_name = should_use_tool(user_message)
            if tool_name == "get_current_time":
                result = self.tool_executor.run("get_current_time")
                final_user_message = inject_tool_result_into_message(user_message, tool_name, result)
            elif tool_name == "simple_calc":
                result = self.tool_executor.run("simple_calc", expression=user_message.strip())
                final_user_message = inject_tool_result_into_message(user_message, tool_name, result)

        # 3) Prompt Builder
        messages = self.prompt_builder.build(
            final_user_message,
            history,
            rag_context=rag_context,
            preferences_summary=preferences,
        )

        # 4) LLM Core
        reply = llm_core.complete(messages)

        # 5) Memory Manager: persist (original user message + reply)
        self.memory.append(user_id, user_message, reply)

        # Build full history for response (context + new turn)
        full_history = list(history) if history else []
        if full_history and full_history[0].get("role") == "system":
            full_history = full_history[1:]
        full_history.append({"role": "user", "content": user_message})
        full_history.append({"role": "assistant", "content": reply})
        return full_history, reply

    def chat_stream(self, user_id: int, user_message: str):
        """Stream one turn. Yields text chunks, then (full_history, full_reply)."""
        user_message = (user_message or "").strip()
        if not user_message:
            yield self.memory.get_context(user_id), ""
            return

        history = self.memory.get_context(user_id)
        preferences = self.memory.get_preferences_summary(user_id) if self.use_rag else None
        rag_context = retrieve(user_id, user_message, k=3) if self.use_rag else None

        final_user_message = user_message
        if self.use_tools:
            tool_name = should_use_tool(user_message)
            if tool_name == "get_current_time":
                result = self.tool_executor.run("get_current_time")
                final_user_message = inject_tool_result_into_message(user_message, tool_name, result)
            elif tool_name == "simple_calc":
                result = self.tool_executor.run("simple_calc", expression=user_message.strip())
                final_user_message = inject_tool_result_into_message(user_message, tool_name, result)

        messages = self.prompt_builder.build(
            final_user_message,
            history,
            rag_context=rag_context,
            preferences_summary=preferences,
        )

        full_reply_parts = []
        for value in llm_core.complete_stream(messages):
            if isinstance(value, tuple):
                _, full_reply = value
                self.memory.append(user_id, user_message, full_reply)
                full_history = list(history) if history else []
                if full_history and full_history[0].get("role") == "system":
                    full_history = full_history[1:]
                full_history.append({"role": "user", "content": user_message})
                full_history.append({"role": "assistant", "content": full_reply})
                yield full_history, full_reply
                return
            full_reply_parts.append(value)
            yield value
        full_reply = "".join(full_reply_parts).strip()
        self.memory.append(user_id, user_message, full_reply)
        full_history = list(history) if history else []
        if full_history and full_history[0].get("role") == "system":
            full_history = full_history[1:]
        full_history.append({"role": "user", "content": user_message})
        full_history.append({"role": "assistant", "content": full_reply})
        yield full_history, full_reply
