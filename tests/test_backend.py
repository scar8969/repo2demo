"""Unit tests for repo2demo backend (stdlib only, no pytest needed)."""
import json, os, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import analyzer, planner, why, runner

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {detail}")


def make_repo():
    """Create a fake mini repo for analyzer tests."""
    d = Path(tempfile.mkdtemp())
    (d / "package.json").write_text(json.dumps({
        "name": "test", "scripts": {"start": "node server.js"},
        "dependencies": {"express": "^4", "react": "^18"}}), encoding="utf-8")
    (d / "server.js").write_text(
        'const express=require("express");const app=express();\n'
        'app.get("/api/users",(q,s)=>s.json([]));\n'
        'app.post("/api/upload",(q,s)=>s.json({}));\n'
        'app.listen(3000);\n', encoding="utf-8")
    (d / "App.jsx").write_text(
        'export default function App(){return <div><h1>Dashboard</h1></div>}\n', encoding="utf-8")
    (d / "db.js").write_text(
        'const mongoose=require("mongoose");mongoose.connect("mongodb://x");\n', encoding="utf-8")
    (d / "README.md").write_text(
        "# Test Repo\n\nA test project for unit tests.\n\n![badge](https://img.shields.io/badge/x)\n",
        encoding="utf-8")
    return d


print("== analyzer ==")
d = make_repo()
a = analyzer.analyze_repo(d)
a["summary"] = analyzer.summarize_for_llm(a)
check("stack detects express/react/mongodb", "express" in a["stack"] and "react" in a["stack"] and "mongodb" in a["stack"], str(a["stack"]))
check("entrypoints finds server.js", any(e["file"] == "server.js" for e in a["entrypoints"]))
check("routes finds GET /api/users", any(r["path"] == "/api/users" and r["method"] == "GET" for r in a["routes"]))
check("routes finds POST /api/upload", any(r["path"] == "/api/upload" for r in a["routes"]))
check("db finds mongoose", any("mongoose" in dd["hits"] for dd in a["db"]))
check("ui_pages finds App.jsx", any(p["file"] == "App.jsx" for p in a["ui_pages"]))
check("readme extracted + badges stripped", "badge" not in a["readme"] and "Test Repo" in a["readme"], a["readme"][:80])
check("summary has STACK + FILES", "STACK:" in a["summary"] and "FILES:" in a["summary"])
check("is_empty_repo false", not analyzer.is_empty_repo(d))
check("is_empty_repo true on empty", analyzer.is_empty_repo(Path(tempfile.mkdtemp())))

print("== planner ==")
plan = {
    "title": "T", "tagline": "tg", "audience": "investors", "hook": "h",
    "steps": [
        {"title": "s1", "narration": "n", "target": "landing", "file": "server.js"},
        {"title": "s2", "narration": "n", "target": "bogus-target", "file": "nonexistent.py"},
        {"title": "s3", "narration": "n", "target": "feature", "file": "App.jsx"},
    ],
    "highlights": ["x"], "skip": ["y"],
}
v = planner.validate_plan(plan, a)
check("valid file kept", v["steps"][0]["file"] == "server.js")
check("missing file cleared", v["steps"][1]["file"] == "")
check("bogus target normalized", v["steps"][1]["target"] == "feature", v["steps"][1]["target"])
check("valid target kept", v["steps"][2]["target"] == "feature")

print("== why ==")
analysis = {"files": a["files"], "contents": a["contents"],
            "routes": a["routes"], "features": a["features"]}
ex = why._find_excerpts(analysis, "mongoose")
check("excerpts find mongoose file", "db.js" in ex)
check("excerpts include line numbers", "lines ~" in ex)
ex2 = why._find_excerpts(analysis, "zzzz_no_match_zzzz")
check("no-match returns empty", ex2 == "")

print("== runner ==")
check("sys_python returns real exe", os.path.exists(runner.sys_python()), runner.sys_python())
manifests = runner.detect_manifest(d)
check("detect_manifest finds package.json", "package.json" in manifests, str(manifests))
cmds = runner.detect_start_cmd(d, manifests)
check("start cmd finds npm start", any("npm run start" in c["name"] for c in cmds), str([c["name"] for c in cmds]))
check("find_free_port returns int", isinstance(runner.find_free_port(), int))

print(f"\n== RESULT: {PASS} passed, {FAIL} failed ==")
sys.exit(1 if FAIL else 0)
