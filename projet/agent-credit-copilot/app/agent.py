"""Boucle agent du Credit Copilot : reason -> act -> observe sur MCP stdio.

Copie adaptée de projet/agent-detection-fraude/app/agent.py. Le backend spawn
app/credit_server.py en sous-processus et parle MCP sur son stdin/stdout. Le system
prompt est la skill skills/credit_review/SKILL.md (le SOP du conseiller crédit).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import anthropic
from mcp import ClientSession, StdioServerParameters

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent                    # projet/agent-credit-copilot/
REPO_ROOT = HERE.parents[2]              # racine du repo

SKILL_PATH = PROJECT / "skills" / "credit_review" / "SKILL.md"
DEFAULT_SERVER = HERE / "credit_server.py"

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 2048

SKILL = SKILL_PATH.read_text(encoding="utf-8")


def server_params() -> StdioServerParameters:
    """Ligne de lancement du serveur MCP : python + chemin absolu du serveur."""
    command = os.getenv("CREDIT_MCP_PYTHON", sys.executable)
    server = os.getenv("CREDIT_MCP_SERVER", str(DEFAULT_SERVER))
    return StdioServerParameters(command=command, args=[server])


class CreditAgent:
    """Une session MCP vivante + la boucle agent qui tourne dessus."""

    def __init__(self, session: ClientSession):
        self.session = session
        self.client = anthropic.Anthropic()
        self.tools: list[dict] = []

    async def discover_tools(self) -> None:
        listed = await self.session.list_tools()
        self.tools = [
            {"name": t.name, "description": t.description, "input_schema": t.inputSchema}
            for t in listed.tools
        ]

    async def stream(self, messages: list[dict], max_iters: int = 16, context: str = ""):
        """Boucle reason -> act -> observe en générateur : yield des ÉVÉNEMENTS au fil de l'eau.

        C'est la source de vérité de la boucle agent (run() n'en est qu'un wrapper). Elle permet
        au backend de streamer, EN TEMPS RÉEL, ce que l'agent fait (comme un terminal d'agent).

        Événements produits :
          {"type": "thought", "text"}                     — texte de raisonnement intermédiaire
          {"type": "tool_start", "tool", "input"}         — un tool va être appelé
          {"type": "tool_end",   "tool", "output"}        — sa sortie vient d'arriver
          {"type": "final", "reply", "trace"}             — réponse finale + trace complète

        `context` = infos sur le dossier ouvert à l'écran, injectées dans le system prompt.
        `max_iters` est le garde-fou anti-boucle infinie.
        """
        system = SKILL if not context else f"{SKILL}\n\n## Dossier actuellement ouvert par le conseiller\n{context}"
        convo = [{"role": m["role"], "content": m["content"]} for m in messages]
        trace: list[dict] = []
        for _ in range(max_iters):
            resp = await asyncio.to_thread(
                self.client.messages.create,
                model=MODEL, max_tokens=MAX_TOKENS,
                system=system, tools=self.tools, messages=convo,
            )
            if resp.stop_reason != "tool_use":
                text = "".join(b.text for b in resp.content if b.type == "text")
                yield {"type": "final", "reply": text, "trace": trace}
                return
            convo.append({"role": "assistant", "content": resp.content})
            # Pensée intermédiaire de l'agent (texte produit AVANT d'appeler les outils).
            thought = "".join(b.text for b in resp.content if b.type == "text").strip()
            if thought:
                trace.append({"tool": "_thought", "text": thought})
                yield {"type": "thought", "text": thought}
            results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                yield {"type": "tool_start", "tool": block.name, "input": block.input}
                out = await self.session.call_tool(block.name, block.input)
                output = "\n".join(c.text for c in out.content)
                trace.append({"tool": block.name, "input": block.input, "output": output})
                yield {"type": "tool_end", "tool": block.name, "output": output}
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
            convo.append({"role": "user", "content": results})
        yield {"type": "final",
               "reply": f"[stopped: max_iters={max_iters} atteint sans réponse finale]", "trace": trace}

    async def run(self, messages: list[dict], max_iters: int = 16, context: str = ""):
        """Wrapper non-streaming : draine stream() et renvoie (reply, trace).

        Conservé pour les appelants synchrones (bridge Streamlit, tests de fumée).
        `trace` = un item par tool call {"tool", "input", "output"}.
        """
        reply, trace = "", []
        async for ev in self.stream(messages, max_iters=max_iters, context=context):
            if ev["type"] == "final":
                reply, trace = ev["reply"], ev["trace"]
        return reply, trace
