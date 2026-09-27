# repo2demo

**Your GitHub repo deserves more than a README.**

Connect a repository. The agent clones it, maps the stack/architecture/UI/API,
plans a guided tour, and generates an interactive demo anyone can click through —
with a **Why?** mode that answers questions straight from the code, and an optional
**Run app** mode that boots the actual project in a live iframe.

## What it does

```
GitHub URL ──► clone ──► analyze ──► plan ──► interactive demo
                    │          │         │
              stack, routes,  LLM writes  shareable link
              DB, UI, features  a tour    + Why mode
```

- **Guided demo** — a clickable tour (5–9 steps) with narration per step, real code
  with syntax highlighting + line numbers, and a progress rail.
- **Why mode** — viewers ask "why is Redis here?" and the agent answers grounded in
  the actual code, with file references and line numbers.
- **Audience-aware** — one click re-plans the demo for investors / developers / general.
- **Run app** — installs deps, starts the project, and shows it live in an iframe
  (streamlit, flask, fastapi, express, vite, django, go, rust, docker…).
- **Shareable** — `#/demo/{id}` hash URLs, iframe embed snippet, JSON export.
- **Honest** — the plan includes a "what to skip" list (weak spots, missing features).

## Run

```
run.bat            # Windows one-click (or: python main.py)
```

Serves on **http://127.0.0.1:8766**

LLM config via env (defaults to relay-ai, falls back to `RELAYAI_API_KEY`):
- `R2D_API_KEY` / `R2D_BASE_URL` (default https://relay-ai.cc/v1)
- `R2D_FAST_MODEL` (default deepseek-v4-flash) — Why mode, small calls
- `R2D_BIG_MODEL` (default deepseek-v4-pro) — demo planning

## API

| Endpoint | Description |
|---|---|
| `POST /api/build` | `{repo_url, description?, audience?, run_app?}` → `{job_id}` (rate-limited 5/10min) |
| `GET /api/jobs/{id}` | progress + demo when done |
| `GET /api/demo/{id}` | full demo JSON (restored from disk on restart) |
| `POST /api/replan/{id}` | `{audience}` — regenerate plan for a different audience |
| `POST /api/why/{id}` | `{question}` — grounded answer + code refs (keeps conversation history) |
| `GET /api/code/{file}?jid=` | raw file contents (path-traversal guarded) |
| `POST /api/run/{id}` | start the app (async) |
| `GET /api/run/{id}/status` | running / starting / error + run log |
| `GET /api/proxy/{id}/{path}` | reverse-proxy to the running app for the iframe |
| `GET /api/stats` | demos generated, uptime |

## Architecture

```
backend/
  analyzer.py   clone + static analysis (stack, entrypoints, routes, DB, UI, features, README)
  planner.py    LLM demo-plan generation (audience-aware) + validation
  why.py        code-grounded Q&A with excerpt retrieval + line numbers
  runner.py     dep detection/install, start-command discovery, health checks, auto-fix
  server.py     FastAPI: jobs, cache, restore, rate limit, proxy, static
  llm.py        OpenAI-compatible chat client (relay-ai)
frontend/
  index.html    single-file dark GUI: landing → pipeline → player + Why + Run app
```

## Notes

- Public repos only (private repos need auth — the clone fails cleanly).
- Native-module builds (node-gyp, e.g. better-sqlite3) may fail without build tools.
- Jobs are pruned after 6h; analysis is cached per-repo.
