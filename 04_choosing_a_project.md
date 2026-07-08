# Choosing a project (must be agentic)

## The litmus test
> *"Can you answer correctly in one shot, from the model's own knowledge, without looking anything up or changing anything?"*
> **Yes → it's NOT an agentic project** (just an LLM call). **No → a good candidate.**

## ✅ A good subject — green flags
- The model **decides its next action** based on what it observes.
- It **calls tools** (search / API / database) **and/or acts** (create, write, send).
- The **number/order of steps varies** with the input (not a fixed pipeline).
- A **constraint is satisfied by iteration** (budget, availability, completeness…).
- You can **point to the loop** in a 5-minute demo.

## ❌ A bad subject — red flags
- **No tools**: text in → text out (summary, translation, rewriting, generating copy/poem/image).
- **A single step**: the model is called once, and it's done.
- **RAG alone** = a Q&A chatbot over a PDF with no decision or action → that's **TD3**, not an agent.
- **Classification only** (sentiment, category) → that's **TD2**.
- It **fetches nothing** fresh and **changes nothing**.

## Clearest of all: same domains, good vs bad

| Domain | ❌ Bad (LLM call) | ✅ Good (agentic) |
|---|---|---|
| Cooking | "Generate a recipe" | Fridge agent: reads the inventory, finds real recipes, reacts to what's missing, writes the shopping list |
| Support | "Summarize this ticket" | Triage: classifies it, searches the KB (RAG), drafts a reply, **decides** to escalate |
| Docs | Q&A chatbot over 1 PDF (RAG alone) | Research agent: decides what to search, reads, **launches follow-up** searches, synthesizes with sources |
| Travel | "What to do in Lisbon?" | Planner: searches flights/hotels, **iterates** to hit the budget, plans around the weather |
| Dev | "Explain this code" | Repo agent: greps/reads the files, runs the tests, **iterates** to answer/fix |

## Scope pitfall (a good subject, badly sized)
- **Too ambitious**: a multi-agent production system, auth/payment/scale → won't finish in 1.5 days.
- **Too thin**: a single tool called once → no real loop.
- **The right size**: 1 goal, **2–4 tools**, a visible loop, a simple UI, and **mock** the external data/APIs (allowed).

## 6 validation questions at kickoff
To approve an idea, ask the group:
1. What **goal** does the agent pursue?
2. What **tools** does it call? (need ≥1–2 real ones)
3. Where is the **loop** — it decides what, based on which result?
4. **Why isn't a single LLM call enough?**
5. Can you **demo the key flow in 5 min**?
6. Is it **scoped for 1.5 days** (the rest mocked)?
