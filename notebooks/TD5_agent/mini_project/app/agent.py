"""The PIM Copilot agent: the TD5 reason -> act -> observe loop, but over MCP **stdio**.

Instead of the notebook's in-memory transport, this opens a stdio client that spawns the
TD4 mini-project server (`pim_server.py`) as a subprocess and speaks MCP over its stdin/stdout.
`list_tools()` / `call_tool()` behave exactly as in the notebook -- only the transport changed.
The TD4 server persists to a ChromaDB store on disk, so products the agent creates are written
to the same index the Light PIM viewer reads.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import anthropic
from mcp import ClientSession, StdioServerParameters

HERE = Path(__file__).resolve().parent
NOTEBOOKS = HERE.parents[2]              # notebooks/
REPO_ROOT = NOTEBOOKS.parent            # repo root

SKILL_PATH = NOTEBOOKS / "data" / "skills" / "add_product" / "SKILL.md"
DEFAULT_SERVER = NOTEBOOKS / "TD4_mcp" / "mini_project" / "pim_server.py"

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 1024

SKILL = SKILL_PATH.read_text(encoding="utf-8")


def server_params() -> StdioServerParameters:
    """The launch line for the TD4 server: a python + the absolute path to pim_server.py.

    Defaults to the interpreter running this backend (so launching from your venv reuses the
    same environment, deps included). Override with PIM_MCP_PYTHON / PIM_MCP_SERVER.
    """
    command = os.getenv("PIM_MCP_PYTHON", sys.executable)
    server = os.getenv("PIM_MCP_SERVER", str(DEFAULT_SERVER))
    return StdioServerParameters(command=command, args=[server])


class PimAgent:
    """Wraps one live MCP session and runs the agent loop against it."""

    def __init__(self, session: ClientSession):
        self.session = session
        self.client = anthropic.Anthropic()
        self.tools: list[dict] = []

    async def discover_tools(self) -> None:
        """Translate the discovered MCP catalog into Anthropic's tools= format (the TD4 1:1 map)."""
        listed = await self.session.list_tools()
        self.tools = [
            {"name": t.name, "description": t.description, "input_schema": t.inputSchema}
            for t in listed.tools
        ]

    async def run(self, messages: list[dict], max_iters: int = 12):
        """Run the reason -> act -> observe loop over the conversation; return (reply, trace).

        `messages` is the chat history [{role, content}]. `trace` is one entry per tool call
        made during this turn: {"tool", "input", "output"} -- the live tool-call trace the UI shows.
        """
        convo = [{"role": m["role"], "content": m["content"]} for m in messages]
        trace: list[dict] = []
        for _ in range(max_iters):
            resp = await asyncio.to_thread(
                self.client.messages.create,
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SKILL,
                tools=self.tools,
                messages=convo,
            )
            if resp.stop_reason != "tool_use":
                text = "".join(b.text for b in resp.content if b.type == "text")
                return text, trace
            convo.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                out = await self.session.call_tool(block.name, block.input)
                output = "\n".join(c.text for c in out.content)
                trace.append({"tool": block.name, "input": block.input, "output": output})
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
            convo.append({"role": "user", "content": results})
        return f"[stopped: reached max_iters={max_iters} without a final answer]", trace
