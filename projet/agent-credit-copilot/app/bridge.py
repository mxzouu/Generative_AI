"""Pont async -> sync entre Streamlit (synchrone) et la session MCP (asynchrone).

Streamlit rerun le script à chaque interaction ; on ne peut pas y garder une boucle asyncio
ouverte naïvement. `AgentBridge` possède SON PROPRE event loop dans un thread de fond, garde
la session MCP stdio ouverte pour toute la durée de vie de l'app, et expose une méthode SYNC
`ask(messages)`. On l'instancie une seule fois via @st.cache_resource (voir streamlit_app.py).

Détail important (anyio) : les contextes async de MCP (stdio_client / ClientSession) utilisent
des cancel scopes qui DOIVENT être ouverts et fermés dans la MÊME tâche asyncio. On les tient
donc dans une unique tâche « serveur » (`_serve`) qui les ouvre, signale qu'elle est prête, puis
attend un événement d'arrêt — et les referme proprement dans cette même tâche à la fermeture.
"""
from __future__ import annotations

import asyncio
import threading
from contextlib import AsyncExitStack

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.stdio import stdio_client

from .agent import PROJECT, REPO_ROOT, CreditAgent, server_params

load_dotenv(PROJECT / ".env")
load_dotenv(REPO_ROOT / ".env")


class AgentBridge:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self.agent: CreditAgent | None = None
        self.tool_names: list[str] = []
        self._boot_error: Exception | None = None
        # démarre la tâche serveur et attend qu'elle soit prête (ou remonte son erreur)
        self._submit(self._boot()).result()
        if self._boot_error is not None:
            raise self._boot_error

    def _submit(self, coro):
        """Soumet une coroutine au loop de fond (thread-safe) et renvoie le Future concurrent."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def _boot(self) -> None:
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._serve_task = self._loop.create_task(self._serve())
        await self._ready.wait()

    async def _serve(self) -> None:
        """Tâche unique qui possède les contextes MCP pour toute la vie du bridge."""
        try:
            async with AsyncExitStack() as stack:
                read, write = await stack.enter_async_context(stdio_client(server_params()))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                self.agent = CreditAgent(session)
                await self.agent.discover_tools()
                self.tool_names = [t["name"] for t in self.agent.tools]
                self._ready.set()          # le bridge est prêt à répondre
                await self._stop.wait()    # garde les contextes ouverts jusqu'à close()
        except Exception as e:             # échec au démarrage -> débloque __init__ avec l'erreur
            self._boot_error = e
            self._ready.set()

    def ask(self, messages: list[dict], max_iters: int = 16, context: str = ""):
        """Fait tourner la boucle agent sur un historique de messages. Renvoie (reply, trace).

        `context` = description du dossier ouvert à l'écran (injectée dans le system prompt).
        """
        return self._submit(self.agent.run(messages, max_iters=max_iters, context=context)).result()

    def close(self) -> None:
        async def _shutdown():
            self._stop.set()
            await self._serve_task   # referme les contextes dans LEUR tâche (pas de RuntimeError)
        try:
            self._submit(_shutdown()).result()
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
