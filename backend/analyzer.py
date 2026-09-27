"""Repo analysis: clone, tree, code map, UI map, architecture. No LLM needed."""
import json, os, re, shutil, subprocess, tempfile
from pathlib import Path

from . import planner

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "env", "__pycache__",
             ".next", "dist", "build", ".cache", "target", "vendor", ".idea",
             ".vscode", "coverage", ".pytest_cache", ".mypy_cache", "Pods",
             ".gradle", ".tox", ".eggs", "site-packages"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".woff",
            ".woff2", ".ttf", ".eot", ".map", ".lock", ".min.js", ".min.css",
            ".pyc", ".class", ".jar", ".zip", ".tar", ".gz", ".pdf", ".mp4",
            ".mp3", ".wav", ".ogg", ".db", ".sqlite", ".ipynb_checkpoints"}
BIG_FILE = 400_000
MAX_FILES = 600
MAX_TOTAL = 3_000_000
MAX_CLONE_MB = 500  # refuse repos larger than this

FILE_HINTS = [
    # manifest/config filenames (matched against file NAMES only)
    (r"package\.json", "node"), (r"requirements\.txt|pyproject\.toml|setup\.py", "python"),
    (r"go\.mod", "go"), (r"Cargo\.toml", "rust"), (r"pom\.xml|build\.gradle", "java"),
    (r"composer\.json", "php"), (r"Gemfile", "ruby"), (r"\.csproj$|\.sln$", "dotnet"),
    (r"next\.config", "nextjs"), (r"vite\.config", "vite"), (r"angular\.json", "angular"),
    (r"nuxt\.config", "nuxt"), (r"astro\.config", "astro"), (r"manage\.py", "django"),
    (r"docker-compose|compose\.ya?ml", "docker"), (r"kubernetes|k8s|helm", "k8s"),
    (r"\.xcodeproj", "ios"), (r"\.dart$", "flutter"), (r"\.kt$", "kotlin"),
    (r"\.rs$", "rust"), (r"\.tsx?$", "typescript"), (r"\.jsx?$", "javascript"),
    (r"\.py$", "python"), (r"\.go$", "go"), (r"\.rb$", "ruby"),
    (r"\.php$", "php"), (r"\.cs$", "csharp"), (r"\.java$", "java"),
    (r"\.c$|\.h$|\.cpp$|\.hpp$", "c/c++"), (r"\.sh$", "shell"),
    (r"\.sql$", "sql"), (r"\.html?$", "html"),
]
CONTENT_HINTS = [
    # tech keywords (matched against file CONTENTS only, word-boundary)
    (r"\bdjango\b", "django"), (r"\bflask\b", "flask"), (r"\bfastapi\b", "fastapi"),
    (r"\bexpress\b", "express"), (r"\btailwind\b", "tailwind"), (r"\breact\b", "react"),
    (r"\bvue\b", "vue"), (r"\bsvelte\b", "svelte"), (r"\btensorflow\b|\btorch\b|\bkeras\b", "ml"),
    (r"\bredis\b", "redis"), (r"\bpostgres\b|\bpsycopg\b|\bpg_", "postgres"),
    (r"\bmysql\b", "mysql"), (r"\bmongodb\b|\bmongoose\b", "mongodb"),
    (r"\bsqlite\b", "sqlite"), (r"\bgraphql\b", "graphql"),
    (r"\bwebsocket\b|socket\.io", "websockets"), (r"\belectron\b", "electron"),
    (r"\bflutter\b", "flutter"), (r"\bswift\b", "ios"), (r"\bkotlin\b", "kotlin"),
]


def clone_repo(url, dest):
    """Clone a repo (shallow). Returns repo dir or raises."""
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    subprocess.run(["git", "clone", "--depth", "1", url, str(dest)],
                   check=True, capture_output=True, timeout=300, env=env)
    return dest


def is_empty_repo(root):
    """True if the repo has no analyzable files."""
    return len(walk_files(root)) == 0


def walk_files(root):
    """Yield relative paths of text files worth analyzing."""
    root = Path(root)
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, "/")
            if fn.startswith(".") or rel.startswith("."):
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext in SKIP_EXT or any(fn.endswith(s) for s in (".min.js", ".min.css")):
                continue
            p = Path(dirpath) / fn
            try:
                if p.stat().st_size > BIG_FILE:
                    continue
            except OSError:
                continue
            out.append(rel)
    out.sort()
    return out[:MAX_FILES]


def read_text(root, rel, limit=BIG_FILE):
    p = Path(root) / rel
    try:
        b = p.read_bytes()
    except OSError:
        return ""
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return b.decode(enc)[:limit]
        except (UnicodeDecodeError, ValueError):
            continue
    return ""


def detect_stack(files, contents):
    """Detect tech stack: file patterns against filenames, content keywords against contents."""
    fnames = "\n".join(files[:80])
    ctext = "\n".join(contents[:80])
    hits = set()
    # filename patterns (package.json, go.mod, *.py, etc.) — re.M so $ anchors per-line
    for pat, label in FILE_HINTS:
        if re.search(pat, fnames, re.I | re.M):
            hits.add(label)
    # content keywords (flask, react, redis, etc.)
    for pat, label in CONTENT_HINTS:
        if re.search(pat, ctext, re.I):
            hits.add(label)
    return sorted(hits)


def find_entrypoints(files, contents):
    """Find likely entry points: main files, servers, CLIs, index pages."""
    entries = []
    for rel, txt in zip(files, contents):
        low = txt.lower()
        score = 0
        if re.search(r"__main__|app\.run|uvicorn\.run|Flask\(|FastAPI\(|express\(|app\.listen|createServer|def main\(|if __name__", txt):
            score += 3
        if re.search(r"@app\.(route|get|post)|@router\.|@app\.api|def (index|home|dashboard)", txt):
            score += 2
        if re.search(r"<html|<body|<!doctype", low):
            score += 2
        if re.search(r"package\.json|manage\.py|main\.py|server\.py|app\.py|index\.(js|ts|html)|cli\.py|run\.py", rel):
            score += 2
        if score >= 2:
            entries.append((rel, score, txt[:2000]))
    entries.sort(key=lambda x: -x[1])
    return [{"file": r, "score": s, "snippet": t} for r, s, t in entries[:12]]


def find_routes(files, contents):
    """Find API routes / URL patterns."""
    routes = []
    pats = [
        (r"@app\.(get|post|put|delete|patch)\(['\"]([^'\"]+)['\"]", "flask/fastapi"),
        (r"@router\.(get|post|put|delete|patch)\(['\"]([^'\"]+)['\"]", "fastapi-router"),
        (r"router\.(get|post|put|delete|patch)\(['\"]([^'\"]+)['\"]", "express"),
        (r"app\.(get|post|put|delete|patch)\(['\"]([^'\"]+)['\"]", "express-app"),
        (r"urlpatterns.*path\(['\"]([^'\"]+)['\"]", "django"),
        (r"@RequestMapping\(['\"]([^'\"]+)['\"]", "spring"),
        (r"Route::(get|post|put|delete)\(['\"]([^'\"]+)['\"]", "laravel"),
    ]
    for rel, txt in zip(files, contents):
        for pat, kind in pats:
            for m in re.finditer(pat, txt):
                route = m.group(2) if m.lastindex == 2 else m.group(1)
                routes.append({"method": m.group(1).upper() if m.lastindex == 2 else "GET",
                               "path": route, "file": rel, "kind": kind})
    return routes[:60]


def find_db(files, contents):
    """Find DB usage: ORM models, schemas, migrations, queries."""
    db = []
    for rel, txt in zip(files, contents):
        low = txt.lower()
        hits = []
        for kw in ("create_engine", "sqlalchemy", "sqlite3", "psycopg", "mongoose",
                   "prisma", "sequelize", "knex", "drizzle", "typeorm", "redis",
                   "CREATE TABLE", "ALTER TABLE", "INSERT INTO", "SELECT ",
                   "schema.prisma", "migration", "models.py", "models/"):
            if kw in low:
                hits.append(kw)
        if hits:
            db.append({"file": rel, "hits": hits[:6]})
    return db[:30]


def find_ui_pages(files, contents):
    """Find UI pages: html, templates, react components, screens."""
    pages = []
    for rel, txt in zip(files, contents):
        low = txt.lower()
        score = 0
        if re.search(r"<html|<body|<!doctype", low):
            score += 2
        if re.search(r"function \w+\(|const \w+ = \(|export default", txt):
            score += 1
        if re.search(r"page\.(js|tsx?|jsx|vue|svelte)|\.html$|templates?/|views?/|screens?/|components?/|(App|main|index)\.(jsx?|tsx?|vue|svelte)$", rel):
            score += 2
        if score >= 2:
            title = ""
            m = re.search(r"<title>(.*?)</title>", txt, re.I | re.S)
            if m:
                title = m.group(1).strip()[:80]
            pages.append({"file": rel, "title": title, "score": score})
    pages.sort(key=lambda x: -x["score"])
    return pages[:40]


def find_features(files, contents):
    """Find feature-ish code: auth, uploads, payments, AI, etc."""
    feats = []
    for rel, txt in zip(files, contents):
        low = txt.lower()
        found = []
        for kw, label in (("jwt", "auth"), ("oauth", "auth"), ("login", "auth"),
                          ("password", "auth"), ("session", "auth"),
                          ("upload", "upload"), ("multipart", "upload"),
                          ("stripe", "payments"), ("razorpay", "payments"),
                          ("payment", "payments"), ("checkout", "payments"),
                          ("openai", "ai"), ("anthropic", "ai"), ("gemini", "ai"),
                          ("llm", "ai"), ("embedding", "ai"), ("gpt", "ai"),
                          ("websocket", "realtime"), ("socket.io", "realtime"),
                          ("cron", "jobs"), ("queue", "jobs"), ("celery", "jobs"),
                          ("search", "search"), ("elasticsearch", "search"),
                          ("notification", "notifications"), ("email", "email"),
                          ("export", "export"), ("csv", "export"), ("pdf", "export"),
                          ("rate.limit", "rate-limiting"), ("redis", "cache"),
                          ("cache", "cache"), ("docker", "docker"), ("kubernetes", "k8s")):
            if kw in low:
                found.append(label)
        if found:
            feats.append({"file": rel, "features": sorted(set(found))[:8]})
    return feats[:40]


def readme_summary(root, limit=4000):
    """Extract README content (best candidate file) for LLM context."""
    root = Path(root)
    for name in ("README.md", "README.MD", "readme.md", "Readme.md",
                 "README.txt", "README.rst", "README"):
        p = root / name
        if p.exists():
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            # strip badges/images/links noise, keep prose + headings
            txt = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", txt)
            txt = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", txt)
            txt = re.sub(r"<[^>]+>", "", txt)
            txt = re.sub(r"\n{3,}", "\n\n", txt)
            return txt[:limit]
    return ""


def demo_health(plan, analysis):
    """Score a demo plan: what fraction of steps reference real files, valid targets."""
    steps = plan.get("steps", [])
    if not steps:
        return {"score": 0, "file_hits": 0, "total": 0, "issues": ["no steps"]}
    files = set(analysis["files"])
    file_hits = sum(1 for s in steps if s.get("file") in files)
    valid_targets = sum(1 for s in steps if s.get("target") in planner.VALID_TARGETS)
    issues = []
    for s in steps:
        if s.get("file") and s["file"] not in files:
            issues.append(f"missing file: {s['file']}")
    score = round((file_hits / len(steps)) * 60 + (valid_targets / len(steps)) * 40)
    return {"score": score, "file_hits": file_hits, "total": len(steps),
            "valid_targets": valid_targets, "issues": issues[:5]}


def analyze_repo(root):
    """Full static analysis. Returns dict."""
    files = walk_files(root)
    contents = [read_text(root, f) for f in files]
    return {
        "file_count": len(files),
        "total_bytes": sum(len(c) for c in contents),
        "files": files,
        "contents": contents,
        "readme": readme_summary(root),
        "stack": detect_stack(files, contents),
        "entrypoints": find_entrypoints(files, contents),
        "routes": find_routes(files, contents),
        "db": find_db(files, contents),
        "ui_pages": find_ui_pages(files, contents),
        "features": find_features(files, contents),
    }


def summarize_for_llm(analysis, max_chars=9000):
    """Compact text summary of analysis for the LLM planner."""
    a = analysis
    parts = []
    parts.append(f"STACK: {', '.join(a['stack']) or 'unknown'}")
    parts.append(f"FILES: {a['file_count']} ({a['total_bytes']} bytes)")
    if a["entrypoints"]:
        parts.append("ENTRYPOINTS:\n" + "\n".join(
            f"- {e['file']} (score {e['score']}): {e['snippet'][:150]}" for e in a["entrypoints"][:6]))
    if a["routes"]:
        parts.append("API ROUTES:\n" + "\n".join(
            f"- {r['method']} {r['path']} ({r['file']})" for r in a["routes"][:25]))
    if a["db"]:
        parts.append("DATABASE:\n" + "\n".join(
            f"- {d['file']}: {', '.join(d['hits'])}" for d in a["db"][:12]))
    if a["ui_pages"]:
        parts.append("UI PAGES:\n" + "\n".join(
            f"- {p['file']}" + (f" ({p['title']})" if p["title"] else "") for p in a["ui_pages"][:20]))
    if a["features"]:
        parts.append("FEATURES:\n" + "\n".join(
            f"- {f['file']}: {', '.join(f['features'])}" for f in a["features"][:20]))
    txt = "\n\n".join(parts)
    return txt[:max_chars]
