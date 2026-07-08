"""Smoke test de la boucle agent — SANS Streamlit.

Lance exactement le même chemin de code que le chatbot : AgentBridge spawn le serveur MCP
(app/credit_server.py) en sous-processus, découvre les tools, puis fait tourner la boucle
Haiku sur une question. Affiche la réponse ET la trace des tool calls.

Prérequis : données + modèle + index générés, et ANTHROPIC_API_KEY dans un .env (projet ou racine).
Usage :  python scripts/smoke_test_agent.py [DEMANDE_ID]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # évite les crashs cp1252 sur les accents
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from app.bridge import AgentBridge  # noqa: E402

DEMANDE = sys.argv[1] if len(sys.argv) > 1 else "DOS0031"

QUESTIONS = [
    "Quel est le taux d'endettement maximal autorisé pour accorder un crédit ? Cite ta source.",
    f"Analyse le dossier {DEMANDE} : donne le score de risque, explique-le en une phrase, "
    f"et dis-moi si tu recommandes un accord au vu de la politique interne.",
]


def main() -> None:
    print(">>> Démarrage du bridge (spawn du serveur MCP)…")
    bridge = AgentBridge()
    print(f">>> Tools découverts : {bridge.tool_names}\n")

    for i, q in enumerate(QUESTIONS, 1):
        print(f"{'='*80}\n[Q{i}] {q}\n{'-'*80}")
        reply, trace = bridge.ask([{"role": "user", "content": q}])
        for t in trace:
            print(f"  🔧 {t['tool']}({t['input']})")
            print(f"     -> {t['output'][:200].strip()}…")
        print(f"\n[Réponse agent]\n{reply}\n")

    bridge.close()
    print(">>> OK — la boucle agent a tourné de bout en bout.")


if __name__ == "__main__":
    main()
