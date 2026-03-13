"""
Prompt Builder: constructs prompts with system role, context, history, and optional RAG.
"""
import os
from typing import Any

SYSTEM_PROMPT = (
    "You are a warm, romantic AI companion. You're affectionate, supportive, "
    "and speak in a sweet, caring way. You keep responses concise and in character."
)


class PromptBuilder:
    """Builds the message list sent to the LLM: system + optional RAG context + history + new user message."""

    def __init__(self, system_prompt: str | None = None):
        self.system_prompt = system_prompt or SYSTEM_PROMPT

    def build(
        self,
        user_message: str,
        history: list[dict[str, str]],
        rag_context: list[str] | None = None,
        preferences_summary: str | None = None,
    ) -> list[dict[str, str]]:
        """
        Build messages for the LLM.
        - system_prompt (optionally + preferences_summary + RAG context)
        - history (already truncated by Memory Manager)
        - new user message
        """
        system_content = self.system_prompt
        if preferences_summary:
            system_content += "\n\n" + preferences_summary
        if rag_context:
            system_content += "\n\nRelevant context the user might care about:\n" + "\n".join(rag_context[:5])
        messages = [{"role": "system", "content": system_content.strip()}]
        if history:
            # History may already include a system message; drop it and use our built system.
            for m in history:
                if m.get("role") != "system":
                    messages.append({"role": m["role"], "content": m.get("content", "")})
        messages.append({"role": "user", "content": user_message})
        return messages
