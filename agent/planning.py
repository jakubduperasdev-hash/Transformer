"""
Planning / Reasoning: optional step to decide if we need tools and inject tool results into context.
Simple version: no multi-step loop; we only optionally run one tool when the user message matches.
"""
import re
from typing import Any


def should_use_tool(user_message: str) -> str | None:
    """
    Simple heuristic: if the user asks for time/date or simple math, return the tool name; else None.
    A full implementation would use an LLM call to decide (e.g. function calling).
    """
    msg = (user_message or "").strip().lower()
    if re.search(r"\b(time|date|today|now)\b", msg) and re.search(r"\bwhat|current|give\b", msg):
        return "get_current_time"
    if re.search(r"^\s*[\d\s+\-*/().]+\s*$", (user_message or "").strip()) and len((user_message or "").strip()) < 60:
        return "simple_calc"
    return None


def inject_tool_result_into_message(user_message: str, tool_name: str, result: str) -> str:
    """Prepend tool result so the LLM can use it in the reply."""
    return f"[Tool {tool_name} result: {result}]\n\nUser: {user_message}"
