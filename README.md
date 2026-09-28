<p align="center">
  <img src="https://img.shields.io/badge/tests-21_passed-green" alt="tests">
  <img src="https://img.shields.io/badge/python-3.11+-blue" alt="python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="license">
  <img src="https://img.shields.io/badge/lines-2,697-inactive" alt="lines">
  <img src="https://img.shields.io/badge/patterns-52-orange" alt="patterns">
  <img src="https://img.shields.io/badge/functions-57-purple" alt="functions">
</p>

<h1 align="center">
  Your GitHub repo deserves more than a README.<br>
  <em>Connect it. Get a demo.</em>
</h1>

<p align="center">
  <b>repo2demo</b> is an AI agent that takes <b>any public GitHub repo</b>, clones it,<br>
  maps the stack / architecture / API routes / UI / features using <b>52 detection patterns</b>,<br>
  plans a guided tour, and generates an <b>interactive demo</b> in ~20 seconds.
</p>

<p align="center">
  <img src="docs/landing.png" alt="repo2demo landing" width="800">
</p>

---

## The numbers

| What | Value |
|------|-------|
| **Build time** | **~20s** (clone → analyze → plan → serve) |
| **Lines of code** | 2,697 (1,526 Python + 1,171 frontend) |
| **Functions** | 57 |
| **Stack patterns** | 52 (32 file patterns + 20 content keywords) |
| **Unit tests** | 21 (analyzer, planner, why, runner) |
| **Demo health score** | 0–100 (file-hits × 60% + valid-targets × 40%) |
| **Max files analyzed** | 600 per repo (3MB contents cap) |
| **Concurrent builds** | 2 workers |
| **Rate limit** | 5 builds / 10 min / IP |
| **Clone size cap** | 500 MB |
| **Job TTL** | 6 hours (auto-pruned, orphan processes killed) |

---

## The demo

<p align="center">
  <img src="docs/player.png" alt="demo player — express" width="800">
</p>

**This screenshot is real** — generated for [expressjs/express](https://github.com/expressjs/express)  
(⭐ 69,495 stars, pulled live from GitHub API). It scored **100/100 health** —
every step references a real file in the repo.

### What you're looking at

- **Left**: narrated step (9-step guided tour), code view with syntax highlighting + line numbers, playback controls
- **Right**: clickable step rail (landing → entrypoint → routing → middleware → auth → ... → architecture)
- **Top bar**: Copy link, Embed, JSON export, Run app, Why mode, Re-plan, Present, New demo
- **Bottom**: progress bar, Play/Pause, keyboard shortcuts

---

## Why? mode — ask the code anything

> **Q:** "how does express routing work under the hood?"
>
> **A:** *Express routing works by delegating to a separate `Router` module. In
> `lib/application.js`, the app lazily creates a `Router` instance (lines ~40–50)
> with options for `caseSensitive` and `strict` routing. The `app.get()`, `app.post()`,
> etc. methods delegate to this router. The router handles matching HTTP methods
> and URL paths…*
>
> **Refs:** `lib/application.js`, `History.md`, `Readme.md`, `lib/response.js`,
> `examples/view-locals/index.js`

Every answer is **grounded in actual file excerpts** with line numbers.  
Secrets (API keys, passwords, tokens, private keys) are **redacted before the LLM sees them**.

---

## Quick start

```bash
pip install -r requirements.txt    # fastapi, uvicorn, pydantic, httpx
export R2D_API_KEY="your-key"       # or RELAYAI_API_KEY (relay-ai defaults)
python main.py                      # → http://127.0.0.1:8766
```

**Windows one-click:** `run.bat`

**CLI:**
```bash
$ python cli.py https://github.com/expressjs/express --audience developers
[1/4] cloning ...
[2/4] analyzing ...   1356 files · stack: express, javascript, node, react
[3/4] planning demo for developers ...
      title: Inside Express   steps: 9 · health: 100/100
done in 24.3s
```

---

## Architecture

```
backend/          FastAPI (1,526 Python lines, 57 functions)
  server.py       jobs, cache, restore, rate limit, proxy, CORS, TTL cleanup
  analyzer.py     clone + static analysis (stack, entrypoints, routes, DB, UI, features)
  planner.py      LLM plan generation (audience-aware) + file validation
  why.py          code-grounded Q&A with excerpt retrieval + secrets redaction
  runner.py       dep detect/install, start-command discovery, health checks
  llm.py          OpenAI-compatible (4xx no-retry, BIG→FAST fallback)
frontend/          single-file vanilla JS (1,171 lines, dark theme)
tests/             21 unit tests
cli.py             headless mode: build demos from the terminal
```

---

## API reference

| Endpoint | Description |
|---|---|
| `POST /api/build` | `{repo_url, description?, audience?, run_app?}` → `{job_id}` |
| `GET /api/jobs/{id}` | progress + demo when done |
| `GET /api/demo/{id}` | full demo JSON (restored from disk on restart) |
| `POST /api/replan/{id}` | `{audience}` — regenerate for a different audience |
| `POST /api/why/{id}` | `{question}` — grounded answer + code refs + inline snippet |
| `GET /api/code/{file}?jid=` | raw file contents (path-traversal guarded with `relative_to`) |
| `POST /api/run/{id}` | start the app (async) |
| `GET /api/run/{id}/status` | running / starting / error + install log |
| `GET /api/proxy/{id}/{path}` | reverse-proxy to the running app (localhost-only) |
| `GET /api/stats` | demos generated, uptime |

---

## Security hardening (full audit in [AUDIT_PLAN.md](AUDIT_PLAN.md))

- URL gate — only `https://github.com/<owner>/<repo>` (no file://, ssh, local paths)
- Path traversal — `Path.relative_to()` not prefix-matching
- SSRF — `/api/proxy` restricted to 127.0.0.1/localhost/::1
- Secrets — why-mode strips API keys, passwords, tokens, private keys before LLM
- CORS — localhost by default (`R2D_CORS=*` override)
- Stop kills process — `taskkill /F /T /PID`, not just state-clear
- Concurrency — JOBS_LOCK on all shared-state paths
- 19 issues found & fixed — 21 tests confirm

---

Built by [scar8969](https://github.com/scar8969)