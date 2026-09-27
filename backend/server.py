"""repo2demo API server."""
import json, os, re, shutil, subprocess, threading, time, uuid, copy
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import analyzer, llm, planner, runner, why

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

app = FastAPI(title="repo2demo")
# restrict CORS to localhost by default (override with R2D_CORS=* for dev/deploy)
cors_origins = os.environ.get("R2D_CORS", "http://127.0.0.1:8766,http://localhost:8766").split(",")
app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["*"], allow_headers=["*"])

JOBS = {}
JOBS_LOCK = threading.Lock()
CACHE_LOCK = threading.Lock()
CACHE_DIR = DATA_DIR / "_cache"
CACHE_DIR.mkdir(exist_ok=True)
BUILD_HISTORY = {}  # ip -> [timestamps]
BUILD_LIMIT = 5      # builds per 10 min per ip
BUILD_WINDOW = 600
MAX_CONCURRENT = 2   # max simultaneous build workers
_ACTIVE_BUILDS = 0


def _repo_key(url):
    """Normalize a GitHub URL to a cache key."""
    url = url.rstrip("/").replace("https://", "").replace("http://", "").replace("www.", "")
    url = url.replace("github.com/", "").replace("git@", "").replace(":", "/")
    url = url.replace(".git", "")
    return url.replace("/", "__")


def _gh_meta(url):
    """Fetch repo metadata from GitHub API (best-effort)."""
    import urllib.request
    m = re.search(r"github\.com[:/]([^/]+)/([^/#?]+)", url)
    if not m:
        return {}
    owner, repo = m.group(1), m.group(2).replace(".git", "")
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{owner}/{repo}",
                                     headers={"User-Agent": "repo2demo"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode())
        return {"stars": d.get("stargazers_count", 0), "forks": d.get("forks_count", 0),
                "gh_desc": d.get("description", ""), "language": d.get("language", ""),
                "owner": d.get("owner", {}).get("login", owner)}
    except Exception:
        return {}


def _cache_get(key):
    p = CACHE_DIR / (key + ".json")
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _cache_put(key, data):
    try:
        (CACHE_DIR / (key + ".json")).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _job(jid):
    with JOBS_LOCK:
        return JOBS.get(jid)


def _set(jid, **kw):
    with JOBS_LOCK:
        j = JOBS.setdefault(jid, {})
        j.update(kw)
        j["updated"] = time.time()


class BuildRequest(BaseModel):
    repo_url: str
    description: str = ""
    run_app: bool = False
    audience: str = "investors"


@app.get("/api/health")
def health():
    return {"ok": True, "model": llm.FAST, "big_model": llm.BIG}


_START_TIME = time.time()


@app.get("/api/stats")
def stats():
    """Lightweight server stats for the landing page."""
    with JOBS_LOCK:
        done = sum(1 for j in JOBS.values() if j.get("status") == "done")
        total = len(JOBS)
    return {"demos": done, "jobs": total, "uptime": round(time.time() - _START_TIME, 1)}


@app.get("/api/demos")
def list_demos():
    """List all completed demos (id, repo, title, audience, health, created)."""
    out = []
    with JOBS_LOCK:
        for jid, j in JOBS.items():
            if j.get("status") != "done":
                continue
            d = j.get("demo", {})
            p = d.get("plan", {})
            out.append({
                "jid": jid,
                "repo": d.get("repo_url", ""),
                "title": p.get("title", ""),
                "audience": p.get("audience", ""),
                "health": (p.get("health") or {}).get("score"),
                "steps": len(p.get("steps", [])),
                "created": d.get("created", 0),
            })
    out.sort(key=lambda x: -x["created"])
    return {"demos": out}


@app.post("/api/build")
def build(req: BuildRequest, request: Request):
    if not req.repo_url:
        raise HTTPException(400, "repo_url required")
    # validate the URL is a GitHub repo (blocks local paths / file:// / git@ SSRF)
    if not re.match(r"^https?://(www\.)?github\.com/[^/]+/[^/?#]+", req.repo_url.strip()):
        raise HTTPException(400, "only https://github.com/<owner>/<repo> URLs are supported")
    # simple per-ip rate limit
    ip = request.client.host if request.client else "local"
    now = time.time()
    with JOBS_LOCK:
        ts = [t for t in BUILD_HISTORY.get(ip, []) if now - t < BUILD_WINDOW]
        if len(ts) >= BUILD_LIMIT:
            raise HTTPException(429, f"Too many builds — try again in a few minutes (limit {BUILD_LIMIT}/10min).")
        ts.append(now)
        BUILD_HISTORY[ip] = ts
    jid = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[jid] = {"id": jid, "status": "queued", "stage": "queued",
                     "repo_url": req.repo_url, "created": time.time()}
    threading.Thread(target=_build_worker, args=(jid, req), daemon=True).start()
    return {"job_id": jid}


def _build_worker(jid, req):
    global _ACTIVE_BUILDS
    # wait for a concurrency slot
    while True:
        with JOBS_LOCK:
            if _ACTIVE_BUILDS < MAX_CONCURRENT:
                _ACTIVE_BUILDS += 1
                break
        time.sleep(2)
    workdir = DATA_DIR / jid
    try:
        _set(jid, status="running", stage="cloning", progress=5)
        meta = _gh_meta(req.repo_url)
        try:
            repo_dir = analyzer.clone_repo(req.repo_url, workdir / "repo")
        except subprocess.CalledProcessError as e:
            err = (e.stderr or e.stdout or "").decode("utf-8", "ignore") if isinstance(e.stderr, bytes) else str(e)
            low = err.lower()
            if "not found" in low or ("repository" in low and "not" in low):
                raise RuntimeError("Repository not found — check the URL (it may be private or deleted).")
            if "cancelled dialog" in low or "askpass" in low or "authentication" in low or "could not read" in low:
                raise RuntimeError("This repo requires authentication (private repo?). repo2demo can only clone public repos.")
            raise RuntimeError(f"Clone failed: {err[:300]}")
        if analyzer.is_empty_repo(repo_dir):
            raise RuntimeError("Repo has no analyzable source files (empty or binary-only).")
        # size cap: refuse repos that are too large
        clone_bytes = sum(f.stat().st_size for f in repo_dir.rglob("*") if f.is_file())
        clone_mb = clone_bytes / (1024 * 1024)
        if clone_mb > analyzer.MAX_CLONE_MB:
            raise RuntimeError(f"Repo is too large ({clone_mb:.0f} MB > {analyzer.MAX_CLONE_MB} MB cap). Try a smaller or shallow-cloned repo.")

        _set(jid, stage="analyzing", progress=25)
        key = _repo_key(req.repo_url)
        analysis = _cache_get(key)
        if analysis is None:
            analysis = analyzer.analyze_repo(repo_dir)
            _cache_put(key, {k: v for k, v in analysis.items() if k != "contents"})
        else:
            # cache strips contents — re-read them from the cloned repo
            analysis["contents"] = [analyzer.read_text(repo_dir, f) for f in analysis["files"]]
        analysis["summary"] = analyzer.summarize_for_llm(analysis)
        analysis["repo_url"] = req.repo_url
        analysis["description"] = req.description
        with open(workdir / "analysis.json", "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in analysis.items() if k != "contents"}, f, indent=1)
        # keep contents in a side file (they can be large)
        with open(workdir / "contents.json", "w", encoding="utf-8") as f:
            json.dump(analysis["contents"], f)

        _set(jid, stage="planning", progress=55)
        plan = planner.plan_demo(analysis, req.repo_url, req.description, audience=req.audience)
        plan = planner.validate_plan(plan, analysis)
        plan["audience"] = req.audience
        plan["health"] = analyzer.demo_health(plan, analysis)
        with open(workdir / "plan.json", "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=1)

        _set(jid, stage="finalizing", progress=80)
        demo = {
            "job_id": jid,
            "repo_url": req.repo_url,
            "description": req.description,
            "meta": meta,
            "analysis": {k: v for k, v in analysis.items() if k not in ("contents", "summary")},
            "plan": plan,
            "created": time.time(),
        }

        # optional: run the app (best-effort, non-blocking)
        if req.run_app:
            _set(jid, stage="running", progress=85)
            res = runner.run_project(repo_dir)
            if res.get("ok"):
                demo["app"] = {"url": res["url"], "port": res["port"]}
                _set(jid, app_url=res["url"], app_port=res["port"])
            else:
                demo["app"] = {"ok": False, "reason": res.get("reason", "failed"),
                               "log": res.get("log", "")[-3000:]}
            _set(jid, stage="finalizing", progress=95)

        with open(workdir / "demo.json", "w", encoding="utf-8") as f:
            json.dump(demo, f, indent=1)

        _set(jid, status="done", stage="done", progress=100, demo=demo)
    except Exception as e:
        _set(jid, status="error", stage="error", error=str(e))
    finally:
        with JOBS_LOCK:
            _ACTIVE_BUILDS = max(0, _ACTIVE_BUILDS - 1)


@app.get("/api/jobs/{jid}")
def job_status(jid: str):
    j = _job(jid)
    if not j:
        raise HTTPException(404, "job not found")
    out = {k: v for k, v in j.items() if k != "demo"}
    if j.get("status") == "done":
        out["demo"] = j["demo"]
    return out


@app.get("/api/demo/{jid}")
def get_demo(jid: str):
    j = _job(jid)
    if not j or j.get("status") != "done":
        raise HTTPException(404, "demo not ready")
    return j["demo"]


class WhyRequest(BaseModel):
    question: str


class ReplanRequest(BaseModel):
    audience: str = "investors"


@app.post("/api/replan/{jid}")
def replan(jid: str, req: ReplanRequest):
    """Regenerate the demo plan for a different audience (reuses analysis)."""
    j = _job(jid)
    if not j or j.get("status") != "done":
        raise HTTPException(404, "demo not ready")
    # same audience → return existing plan (no LLM call)
    if j["demo"].get("plan", {}).get("audience") == req.audience:
        return {"ok": True, "demo": j["demo"], "cached": True}
    workdir = DATA_DIR / jid
    analysis_file = workdir / "analysis.json"
    if not analysis_file.exists():
        raise HTTPException(404, "analysis missing")
    analysis = json.loads(analysis_file.read_text(encoding="utf-8"))
    analysis["contents"] = json.loads((workdir / "contents.json").read_text(encoding="utf-8"))
    analysis["summary"] = analyzer.summarize_for_llm(analysis)
    plan = planner.plan_demo(analysis, j["repo_url"], analysis.get("description", ""),
                             audience=req.audience)
    plan = planner.validate_plan(plan, analysis)
    plan["audience"] = req.audience
    plan["health"] = analyzer.demo_health(plan, analysis)
    demo = copy.deepcopy(j["demo"])
    demo["plan"] = plan
    demo["created"] = time.time()
    with open(workdir / "demo.json", "w", encoding="utf-8") as f:
        json.dump(demo, f, indent=1)
    _set(jid, demo=demo)
    return {"ok": True, "demo": demo, "cached": False}


@app.post("/api/why/{jid}")
def ask_why(jid: str, req: WhyRequest):
    j = _job(jid)
    if not j or j.get("status") != "done":
        raise HTTPException(404, "demo not ready")
    workdir = DATA_DIR / jid
    contents = json.loads((workdir / "contents.json").read_text(encoding="utf-8"))
    analysis = {"files": j["demo"]["analysis"]["files"],
                "contents": contents,
                "routes": j["demo"]["analysis"].get("routes", []),
                "features": j["demo"]["analysis"].get("features", [])}
    with JOBS_LOCK:
        history = j.get("why_history", [])
        j["why_history"] = history[-12:]
    res = why.answer_why(analysis, req.question, history=history[-4:])
    with JOBS_LOCK:
        history.append({"q": req.question, "a": res["answer"][:800]})
        j["why_history"] = history[-12:]
        # persist to disk so history survives restart
        with open(workdir / "why_history.json", "w", encoding="utf-8") as f:
            json.dump(j["why_history"], f)
    return res


@app.get("/api/code/{file:path}")
def get_code(file: str, jid: str = ""):
    """Fetch a file's raw code for a given job (jid as query param)."""
    j = _job(jid)
    if not j or j.get("status") != "done":
        raise HTTPException(404, "demo not ready")
    workdir = DATA_DIR / jid
    # path traversal guard: resolved path must be strictly inside repo_dir
    repo_dir = (workdir / "repo").resolve()
    p = (repo_dir / file).resolve()
    try:
        p.relative_to(repo_dir)
    except ValueError:
        raise HTTPException(404, "file not found")
    if not p.is_file():
        raise HTTPException(404, "file not found")
    try:
        txt = p.read_text(encoding="utf-8")
    except Exception:
        txt = p.read_text(encoding="latin-1")
    return {"file": file, "code": txt[:200_000]}


# ---------- app run endpoints ----------
@app.post("/api/run/{jid}")
def run_app(jid: str):
    j = _job(jid)
    if not j or j.get("status") != "done":
        raise HTTPException(404, "demo not ready")
    if j.get("app_url"):
        return {"ok": True, "url": j["app_url"], "already": True}
    with JOBS_LOCK:
        if j.get("run_started"):
            return {"ok": None, "starting": True}
        j["run_started"] = True
        j["run_log"] = ""
    _set(jid, run_started=True, run_log="")
    workdir = DATA_DIR / jid

    def _worker():
        try:
            res = runner.run_project(workdir / "repo")
            if res.get("ok"):
                _set(jid, app_url=res["url"], app_port=res["port"],
                     run_log=res.get("log", ""), app_proc=res.get("proc"))
            else:
                _set(jid, run_error=res.get("reason", "failed"),
                     run_log=res.get("log", "")[-3000:])
        except Exception as e:
            _set(jid, run_error=str(e))

    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": None, "starting": True}


@app.post("/api/run/{jid}/stop")
def stop_app(jid: str):
    j = _job(jid)
    if not j:
        raise HTTPException(404, "job not found")
    # kill the spawned process tree
    proc = j.get("app_proc")
    if proc:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, timeout=10)
            else:
                proc.kill()
        except Exception:
            try: proc.kill()
            except Exception: pass
    _set(jid, app_url=None, app_port=None, app_proc=None, run_started=None)
    return {"ok": True}


@app.get("/api/run/{jid}/status")
def app_status(jid: str):
    j = _job(jid)
    if not j:
        raise HTTPException(404, "job not found")
    url = j.get("app_url")
    if not url:
        if j.get("run_started"):
            return {"running": False, "starting": True,
                    "error": j.get("run_error"), "log": j.get("run_log", "")[-2000:]}
        return {"running": False}
    return {"running": runner.is_up(url), "url": url}


@app.get("/api/proxy/{jid}/{path:path}")
def proxy_app(jid: str, path: str = ""):
    """Reverse-proxy to the running app so the iframe works same-origin."""
    j = _job(jid)
    if not j or not j.get("app_url"):
        raise HTTPException(404, "app not running")
    import urllib.request, urllib.parse
    base = j["app_url"].rstrip("/")
    # SSRF guard: only proxy to localhost/127.0.0.1 (the app we started)
    host = urllib.parse.urlparse(base).hostname or ""
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise HTTPException(403, "proxy target must be localhost")
    target = f"{base}/{path}" if path else base
    try:
        req = urllib.request.Request(target, headers={"User-Agent": "repo2demo"})
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read()
            ctype = r.headers.get("Content-Type", "text/html")
            return Response(content=body, media_type=ctype)
    except urllib.error.HTTPError as e:
        return Response(content=e.read(), status_code=e.code,
                        media_type=e.headers.get("Content-Type", "text/plain"))
    except Exception as e:
        raise HTTPException(502, f"proxy failed: {e}")


# static frontend last (catches /)
frontend_dir = BASE_DIR / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")


# ---------- job TTL cleanup ----------
JOB_TTL = 6 * 3600  # 6 hours


def _cleanup_jobs():
    """Prune old jobs (and their data dirs) — also kill orphaned processes."""
    now = time.time()
    to_del = []
    with JOBS_LOCK:
        for jid, j in list(JOBS.items()):
            if now - j.get("updated", j.get("created", now)) > JOB_TTL:
                # kill any orphaned app process
                proc = j.get("app_proc")
                if proc:
                    try:
                        if os.name == "nt":
                            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                           capture_output=True, timeout=5)
                        else:
                            proc.kill()
                    except Exception:
                        pass
                to_del.append(jid)
        for jid in to_del:
            JOBS.pop(jid, None)
    for jid in to_del:
        shutil.rmtree(DATA_DIR / jid, ignore_errors=True)


def _cleanup_loop():
    while True:
        time.sleep(1800)
        try:
            _cleanup_jobs()
        except Exception:
            pass


threading.Thread(target=_cleanup_loop, daemon=True).start()


# ---------- restore jobs from disk on startup ----------
def _restore_jobs():
    """Rehydrate in-memory job state from demo.json files on disk."""
    if not DATA_DIR.exists():
        return
    for d in DATA_DIR.iterdir():
        if not d.is_dir() or d.name.startswith("_"):
            continue
        demo_file = d / "demo.json"
        if not demo_file.exists():
            continue
        try:
            demo = json.loads(demo_file.read_text(encoding="utf-8"))
            jid = demo.get("job_id") or d.name
            JOBS[jid] = {
                "id": jid, "status": "done", "stage": "done", "progress": 100,
                "repo_url": demo.get("repo_url", ""), "created": demo.get("created", time.time()),
                "updated": time.time(), "demo": demo,
            }
            if demo.get("app", {}).get("url"):
                JOBS[jid]["app_url"] = demo["app"]["url"]
                JOBS[jid]["app_port"] = demo["app"].get("port")
        except Exception:
            continue


_restore_jobs()
