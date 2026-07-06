"""PIM Copilot -- FastAPI backend.

One process serves the chat API (`POST /api/chat`) and the static Vue UI (`/`). On startup it
opens a single long-lived MCP stdio session to the TD4 server (spawned as a subprocess) and
discovers its tools; every /chat request runs the agent loop against that session.
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

from .agent import NOTEBOOKS, PimAgent, server_params

HERE = Path(__file__).resolve().parent
WEB_DIR = HERE.parent / "web"

# No API key in code: read ANTHROPIC_API_KEY from a .env (mini_project first, then repo root).
load_dotenv(HERE.parent / ".env")
load_dotenv(NOTEBOOKS.parent / ".env")

state: dict = {"agent": None, "lock": asyncio.Lock()}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        read, write = await stack.enter_async_context(stdio_client(server_params()))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        agent = PimAgent(session)
        await agent.discover_tools()
        state["agent"] = agent
        yield


app = FastAPI(title="PIM Copilot", lifespan=lifespan)


class ChatRequest(BaseModel):
    messages: list[dict]
    max_iters: int = 12


@app.get("/api/tools")
async def tools():
    return {"tools": [t["name"] for t in state["agent"].tools]}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    agent = state["agent"]
    async with state["lock"]:  # one shared session -> serialize turns
        reply, trace = await agent.run(req.messages, max_iters=req.max_iters)
    return {"reply": reply, "trace": trace}


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
