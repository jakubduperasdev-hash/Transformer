"""
Tool Executor: run tools the agent can use (e.g. current time, simple calc).
Tools are registered by name; the orchestrator or planning step can invoke them.
"""
import re
from datetime import datetime, timezone
from typing import Any, Callable


TOOLS: dict[str, Callable[..., str]] = {}


def register_tool(name: str):
    def decorator(f: Callable[..., str]):
        TOOLS[name] = f
        return f
    return decorator


@register_tool("get_current_time")
def get_current_time() -> str:
    """Return current UTC time. Use when the user asks for the time or date."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


@register_tool("simple_calc")
def simple_calc(expression: str) -> str:
    """Evaluate a simple math expression (numbers and + - * /). Use for simple arithmetic."""
    expression = re.sub(r"[^\d+\-*/().\s]", "", expression.strip())[:80]
    if not expression:
        return "Invalid expression"
    try:
        return str(eval(expression))
    except Exception:
        return "Could not evaluate"


class ToolExecutor:
    """Executes registered tools by name and returns a string result."""

    def __init__(self, tools: dict[str, Callable[..., str]] | None = None):
        self.tools = tools if tools is not None else dict(TOOLS)

    def list_tools(self) -> list[str]:
        return list(self.tools.keys())

    def run(self, tool_name: str, **kwargs: Any) -> str:
        if tool_name not in self.tools:
            return f"Unknown tool: {tool_name}. Available: {', '.join(self.list_tools())}"
        try:
            return self.tools[tool_name](**kwargs)
        except Exception as e:
            return f"Tool error: {e}"
