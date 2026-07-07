"""Copilote fraude — backend FastAPI.

Un seul processus sert l'API chat (`POST /api/chat`) et le front Vue statique (`/`).
Au démarrage : une session MCP stdio longue durée vers fraud_server.py (spawné en
sous-processus) + découverte des tools ; chaque requête /chat fait tourner la boucle
agent sur cette session et renvoie { reply, trace } — la trace des tool calls.
"""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from mcp import ClientSession
from mcp.client.stdio import stdio_client
from pydantic import BaseModel

from .agent import PROJECT, REPO_ROOT, FraudAgent, server_params

HERE = Path(__file__).resolve().parent
WEB_DIR = HERE.parent / "web"

# Pas de clé dans le code : ANTHROPIC_API_KEY via .env (projet d'abord, puis racine du repo).
load_dotenv(PROJECT / ".env")
load_dotenv(REPO_ROOT / ".env")

state: dict = {"agent": None, "lock": asyncio.Lock()}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        read, write = await stack.enter_async_context(stdio_client(server_params()))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        agent = FraudAgent(session)
        await agent.discover_tools()
        state["agent"] = agent
        yield


app = FastAPI(title="Copilote Fraude", lifespan=lifespan)


class ChatRequest(BaseModel):
    messages: list[dict]
    max_iters: int = 16


@app.get("/api/tools")
async def tools():
    return {"tools": [t["name"] for t in state["agent"].tools]}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    agent = state["agent"]
    async with state["lock"]:  # une seule session MCP partagée -> tours sérialisés
        reply, trace = await agent.run(req.messages, max_iters=req.max_iters)
    return {"reply": reply, "trace": trace}


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
