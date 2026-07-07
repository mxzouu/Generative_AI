"""La boucle agent du copilote fraude : reason -> act -> observe sur MCP stdio.

Copie adaptée de notebooks/TD5_agent/mini_project/app/agent.py : le backend spawn
app/fraud_server.py en sous-processus et parle MCP sur son stdin/stdout. Le system
prompt est la skill skills/triage_claims/SKILL.md (le SOP du conseiller).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import anthropic
from mcp import ClientSession, StdioServerParameters

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent                    # projet/agent-detection-fraude/
REPO_ROOT = HERE.parents[2]              # racine du repo

SKILL_PATH = PROJECT / "skills" / "triage_claims" / "SKILL.md"
DEFAULT_SERVER = HERE / "fraud_server.py"

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 2048

SKILL = SKILL_PATH.read_text(encoding="utf-8")


def server_params() -> StdioServerParameters:
    """Ligne de lancement du serveur MCP fraude : python + chemin absolu du serveur.

    Par défaut : l'interpréteur qui exécute ce backend (donc le venv du repo).
    Surchargeable via FRAUD_MCP_PYTHON / FRAUD_MCP_SERVER.
    """
    command = os.getenv("FRAUD_MCP_PYTHON", sys.executable)
    server = os.getenv("FRAUD_MCP_SERVER", str(DEFAULT_SERVER))
    return StdioServerParameters(command=command, args=[server])


class FraudAgent:
    """Une session MCP vivante + la boucle agent qui tourne dessus."""

    def __init__(self, session: ClientSession):
        self.session = session
        self.client = anthropic.Anthropic()
        self.tools: list[dict] = []

    async def discover_tools(self) -> None:
        """Catalogue MCP découvert -> format tools= d'Anthropic (le mapping 1:1 de TD4)."""
        listed = await self.session.list_tools()
        self.tools = [
            {"name": t.name, "description": t.description, "input_schema": t.inputSchema}
            for t in listed.tools
        ]

    async def run(self, messages: list[dict], max_iters: int = 16):
        """Boucle reason -> act -> observe ; renvoie (reply, trace).

        `trace` = un item par tool call de ce tour {"tool", "input", "output"} — c'est
        ce que le front affiche pour montrer le raisonnement de l'agent en direct.
        `max_iters` est le garde-fou anti-boucle infinie (README §8).
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
