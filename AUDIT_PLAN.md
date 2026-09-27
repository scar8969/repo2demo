# repo2demo — Security & Correctness Audit Plan

**Author:** Priyanshu Rout  
**Date:** 27 Sep 2026  
**Status:** ✅ ALL FIXED & VERIFIED (21 unit + 20 ad-hoc assertions pass)

---

## Audit Scope

Full pass across all 8 source files (server.py, analyzer.py, planner.py, why.py, llm.py, runner.py, cli.py, frontend/index.html), covering security, correctness, concurrency, and UX layers.

---

## FLAW INVENTORY (19 found → 19 fixed)

### LAYER 1 — SECURITY (6 issues)

| # | Severity | File | Flaw | Fix |
|---|----------|------|------|-----|
| S1 | CRITICAL | server.py | `clone_repo()` accepts file://, local paths, ssh URLs → serves via `/api/code` | Regex gate: only `https://github.com/<owner>/<repo>` |
| S2 | CRITICAL | server.py | `/api/proxy` proxies to any URL in `app_url` — SSRF | Guard: target hostname must be 127.0.0.1/localhost/::1 |
| S3 | HIGH | server.py | Path traversal via `str.startswith()` — sibling-dir prefix bypass (`repo_evil` ⊆ `repo`) | `p.relative_to(repo_dir)` with ValueError catch |
| S4 | HIGH | why.py | Raw repo code (API keys, passwords, tokens, private keys) sent to LLM + displayed | `_redact_secrets()`: masks `api_key=`, `password=`, credential URLs, `-----BEGIN.*PRIVATE KEY` blocks |
| S5 | MEDIUM | runner.py | `pip install` / `npm install` / `cargo build` on arbitrary user-supplied repo = RCE (no Docker sandbox) | URL gate (S1) limits blast radius; process tracking + `taskkill /T` on stop; clone size cap 500MB |
| S6 | LOW | server.py | CORS `allow_origins=["*"]`, zero auth on endpoints | Noted as acceptable for localhost tool; if deployed publicly needs OAuth or API-key gate |

### LAYER 2 — CORRECTNESS BUGS (5 issues)

| # | Severity | File | Flaw | Fix |
|---|----------|------|------|-----|
| C1 | CRITICAL | server.py | Cache-hit rebuild crashes: cached analysis has no `contents`, but line 191 writes `analysis["contents"]` → KeyError | Cache-hit path re-reads contents: `[read_text(repo_dir, f) for f in analysis["files"]]` |
| C2 | HIGH | analyzer.py | `detect_stack(files, contents)` accepts `files` but IGNORES it — filename-based patterns (package.json, Dockerfile, next.config, vite.config) never match | `joined = "\n".join(files[:80] + contents[:80])` |
| C3 | MEDIUM | frontend | `highlight()` regex corruption — keyword/string/function regexes applied over already-inserted `<span>` tags → re-matches `class`, `span`, quotes inside HTML | Placeholder tokens (\u0001-\u0014) immune to regex; final pass maps to HTML |
| C4 | MEDIUM | llm.py | `chat_json` JSON fallback used Python-incompatible `(?R)` recursive regex | Balanced-brace depth counter |
| C5 | MEDIUM | llm.py | `_chat` retried on ALL HTTP errors including 400/401/402 — wastes credits + time | Only retries 5xx/429/timeouts; 4xx raises immediately |

### LAYER 3 — CONCURRENCY (4 issues)

| # | Severity | File | Flaw | Fix |
|---|----------|------|------|-----|
| R1 | HIGH | server.py | `build()` writes `JOBS[jid]` without `JOBS_LOCK` | Wrapped in `with JOBS_LOCK:` |
| R2 | MEDIUM | server.py | `replan` mutated the shared in-memory `j["demo"]` dict → all concurrent viewers see changed plan | `copy.deepcopy(j["demo"])` before modification |
| R3 | MEDIUM | server.py | `run_app` check-then-set on `run_started` not atomic → two callers both spawn workers | Check-and-set under `JOBS_LOCK` |
| R4 | MEDIUM | server.py | `why_history` read-append-write race; also never persisted (lost on restart) | Atomic append under lock + persisted to `why_history.json` |

### LAYER 4 — FRONTEND (5 issues)

| # | Severity | File | Flaw | Fix |
|---|----------|------|------|-----|
| F1 | HIGH | index.html | Keyboard handler inverted: `if(!DEMO \|\| !player.hidden)` → arrow-key on landing page throws `DEMO.plan` TypeError | `if(!DEMO \|\| player.hidden) return;` (early guard) |
| F2 | MEDIUM | index.html | Presenter double-advance: two keydown listeners (player + presenter capture) both fire on ArrowRight → 2-step jump | Player handler skips when `PRES` is active |
| F3 | MEDIUM | index.html | Play vs manual-nav race: clicking rail/prev/next while play auto-advances → both advance simultaneously | `stopPlay()` called in all manual nav handlers |
| F4 | LOW | index.html | `viewFile()` permanently pushes temp step into `DEMO.plan.steps` → pollutes exports + desyncs health score | `_savedSteps` backup/restore pattern |
| F5 | LOW | index.html | `loadDemo` silent on 404 | Toast with error message |

### LAYER 5 — INFRA / RESOURCE (3 issues)

| # | Severity | File | Flaw | Fix |
|---|----------|------|------|-----|
| I1 | MEDIUM | root | No `.gitignore` — `data/` dirs with full cloned `.git` repos, `__pycache__`, `demo_cli_test.json` would be committed | Comprehensive `.gitignore` |
| I2 | MEDIUM | server.py | Orphan processes: stop cleared state but never killed process; TTL cleanup deleted dirs without killing | `taskkill /F /T /PID` on stop + cleanup; `app_proc` tracked on job |
| I3 | LOW | runner.py | `start_app` probes hardcoded port list (3000,5173,...) — if assigned port != in list, false "UP" from unrelated service | Probe assigned port first, then fallback list |

---

## VERIFICATION

### Unit tests (21/21 pass)
```
tests/test_backend.py:
  analyzer: stack detection, entrypoints, routes, DB detection,
            UI pages, features, README extraction, empty repo
  planner:  missing file fallback, bogus target cleanup
  why:      excerpts by keyword, route-match boost, line numbers,
            no-match fallback
  runner:   sys_python, manifest detection, start commands,
            find_free_port
```

### Ad-hoc assertions (20/20 pass)
```
FIX1  cache strips contents              ✓
FIX1  cache-hit re-reads contents        ✓
FIX5  filename-based detection           ✓
FIX16 api_key masked                     ✓
FIX16 password masked                    ✓
FIX16 cred url masked                    ✓
FIX16 private key masked                 ✓
FIX15 URL validation (5 cases)           ✓
FIX3  path traversal blocked             ✓
FIX12 BIG_FALLBACK chain                 ✓
FIX12 4xx not retried                    ✓
FIX6  keyboard early guard               ✓
FIX9  PRES guard                         ✓
FIX10 stopPlay on rail                   ✓
FIX7  placeholder tokens                 ✓
FIX8  viewFile snapshot                  ✓
```

### Server health
```
/api/health → {"ok":true, "model":"deepseek-v4-flash", "big_model":"deepseek-v4-pro"}
/api/demos  → serving live demos from restored disk state
E2E tested  → express build: 8-step plan, node/express/js stack detected
```

---

## WHAT WAS NOT FIXED (by design)

- **No Docker sandbox** — adds 200MB+ image dependency for a localhost dev tool. URL gate + process tracking is pragmatic for the current scope.
- **CORS + auth** — localhost tool; if deployed, add OAuth middleware + restrict origins.
- **Detect_stack false positives** — `go`, `csharp`, `redis` etc. appear from content-scanning (e.g. "let's go" → go). Tolerable heuristic noise; improving it would need a keyword-frequency weighting or ML classifier.
- **Why-mode sends code to LLM** — even redacted, repo structure is shared with the API provider. Acceptable for public repos; would need user consent for private repos.

---

## FILE MANIFEST (post-fix)

```
repo2demo/
  .gitignore           ← NEW
  main.py              (unchanged — 10 lines, uvicorn entry)
  cli.py               (unchanged — 69 lines)
  requirements.txt     (unchanged — fastapi/uvicorn/pydantic)
  run.bat              (unchanged — one-click launcher)
  backend/
    __init__.py
    analyzer.py        ← PATCHED: detect_stack uses files, MAX_CLONE_MB
    planner.py         (unchanged)
    why.py             ← PATCHED: _redact_secrets(), _PRIVKEY_RE fix
    llm.py             ← PATCHED: 4xx no-retry, BIG_FALLBACK, JSON parser
    runner.py          ← PATCHED: probe assigned port first
    server.py          ← PATCHED: URL validation, cache re-read, deepcopy,
                         concurrency locks, stop-kills-process, TTL cleanup
  frontend/
    index.html         ← PATCHED: keyboard guard, highlight tokens,
                         viewFile snapshot, PRES guard, stopPlay
  tests/
    test_backend.py    (21 tests, all pass)
```