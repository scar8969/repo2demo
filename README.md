<p align="center">
  <img src="https://img.shields.io/badge/tests-21_passed-green" alt="tests">
  <img src="https://img.shields.io/badge/python-3.11+-blue" alt="python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="license">
  <img src="https://img.shields.io/badge/stack-FastAPI_%2B_vanilla_JS-red" alt="stack">
</p>

<h1 align="center">
  Your GitHub repo deserves more than a README.<br>
  <span style="background:linear-gradient(90deg,#ff4444,#ff8844,#ffcc44);-webkit-background-clip:text;-webkit-text-fill-color:transparent">Connect it. Get a demo.</span>
</h1>

<p align="center">
  <b>repo2demo</b> is an AI agent that takes any public GitHub repo, clones it,<br>
  maps the stack / architecture / API routes / UI / features, plans a guided<br>
  tour, and generates an <b>interactive demo</b> anyone can click through — with<br>
  a <b>Why?</b> mode that answers questions straight from the code.
</p>

<p align="center">
  <img src="docs/landing.png" alt="repo2demo landing page" width="800">
</p>

---

## What you get

| Metric | Value |
|--------|-------|
| **Build time** | ~20–30s (clone → analyze → plan → demo) |
| **Files analyzed** | up to 600 per repo (3MB cap) |
| **Demo health score** | 0–100 (file hits × 60% + valid targets × 40%) |
| **Stack detection** | 28 filename patterns + 18 content keywords |
| **Supported runtimes** | Python (pip/uvicorn/streamlit), Node (npm/vite/next), Go, Rust, PHP, Ruby, Docker |
| **Unit tests** | 21 (analyzer, planner, why, runner) |
| **Concurrent builds** | 2 workers |
| **Rate limit** | 5 builds / 10 minutes per IP |
| **Job TTL** | 6 hours (auto-pruned) |
| **Clone size cap** | 500 MB |

---

## How it works

```
GitHub URL ──► clone ──► analyze ──► plan ──► interactive demo
                   │          │         │
             stack, routes,  LLM writes  shareable link
             DB, UI, features  a tour    + Why mode + Run app
```

<p align="center">
  <img src="docs/player.png" alt="demo player showing express" width="800">
</p>

**The demo above** was generated for [expressjs/express](https://github.com/expressjs/express) (⭐ 69,495).  
It scored **100/100 health** — every step references a real file in the repo.

### Features

- **Guided demo** — 5–9 narrated steps with real code, syntax highlighting + line numbers, progress rail
- **Why? mode** — ask "how does routing work?" or "why is Redis used here?" and get answers grounded in actual file excerpts, with line numbers
- **Audience-aware** — one-click re-plan for investors / developers / general
- **Run app** — installs deps, starts the project, shows it live in an iframe (streamlit, flask, fastapi, express, vite, django, go…)
- **Presenter mode** — fullscreen slideshow with speaker notes, keyboard navigation
- **Export** — markdown, JSON, iframe embed snippet
- **Share** — #/demo/{id} hash URLs (no database, all state on disk)

---

## Quick start

```bash
# 1. install deps
pip install -r requirements.txt

# 2. set your LLM key (default: relay-ai)
export R2D_API_KEY="your-key"        # or RELAYAI_API_KEY
# optional overrides:
export R2D_BASE_URL="https://your-api/v1"
export R2D_FAST_MODEL="gpt-4o-mini"  # Why mode
export R2D_BIG_MODEL="gpt-4o"        # demo planning

# 3. run
python main.py
# → http://127.0.0.1:8766
```

**Windows one-click:** `run.bat`

---

## Architecture

```
repo2demo/
  backend/
    server.py     FastAPI (jobs, cache, restore, rate limit, proxy, CORS)
    analyzer.py   clone + static analysis (stack, entrypoints, routes, DB, UI, features)
    planner.py    LLM demo-plan generation (audience-aware) + validation
    why.py        code-grounded Q&A with excerpt retrieval + secrets redaction
    runner.py     dep detection/install, start-command discovery, health checks
    llm.py        OpenAI-compatible client (4xx no-retry, BIG→FAST fallback)
  frontend/
    index.html    single-file dark GUI: landing → pipeline → player + Why + Run app
  tests/
    test_backend.py  21 tests
  cli.py          headless mode: python cli.py https://github.com/user/repo
```

---

## API

| Endpoint | Description |
|---|---|
| `POST /api/build` | `{repo_url, description?, audience?, run_app?}` → `{job_id}` |
| `GET /api/jobs/{id}` | progress + demo when done |
| `GET /api/demo/{id}` | full demo JSON |
| `POST /api/replan/{id}` | `{audience}` — regenerate for different audience |
| `POST /api/why/{id}` | `{question}` — grounded answer + code refs + inline snippet |
| `GET /api/code/{file}?jid=` | raw file contents (path-traversal guarded) |
| `POST /api/run/{id}` | start the app (async) |
| `GET /api/run/{id}/status` | running / starting / error + install log |
| `GET /api/proxy/{id}/{path}` | reverse-proxy to living app for the iframe |
| `GET /api/stats` | demos generated, uptime |

---

## Security hardening

- **URL gate** — only `https://github.com/<owner>/<repo>` accepted (no file://, ssh, local paths)
- **Path traversal** — `Path.relative_to()` guard (not prefix-matching)
- **SSRF guard** — `/api/proxy` only forwards to 127.0.0.1/localhost
- **Secrets redaction** — why-mode strips API keys, passwords, tokens, private keys pre-LLM
- **CORS** — restricted to localhost by default (`R2D_CORS=*` override)
- **Clone size cap** — 500MB max
- **Stop kills process** — `taskkill /F /T /PID` (not just state-clear)
- **Concurrency** — JOBS_LOCK on all shared-state mutations

Full audit: see [`AUDIT_PLAN.md`](AUDIT_PLAN.md)

---

## CLI

```bash
python cli.py https://github.com/expressjs/express --audience developers --out demo.json
# [1/4] cloning ...
# [2/4] analyzing ...   1356 files · stack: node, express, javascript
# [3/4] planning demo for developers ...   title: Inside Express   steps: 9 · health: 100/100
# done in 24.3s
```

---

Built by [scar8969](https://github.com/scar8969)