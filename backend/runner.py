"""App runner: detect deps, install, start, health-check, auto-fix. Best-effort, sandboxed-ish."""
import json, os, re, shutil, subprocess, time
from pathlib import Path

TIMEOUT_INSTALL = 600
TIMEOUT_START = 90
HEALTH_WAIT = 60


def _run(cmd, cwd, timeout=TIMEOUT_INSTALL, env=None):
    """Run a command, return (rc, output). Handles Windows .cmd shims."""
    cmd = list(cmd)
    # npm/npx are .cmd shims on Windows — subprocess needs shell or the .cmd path
    if os.name == "nt" and cmd and cmd[0] in ("npm", "npx", "yarn", "pnpm", "go", "cargo"):
        shim = shutil.which(cmd[0] + ".cmd") or shutil.which(cmd[0] + ".exe")
        if shim and shim.endswith(".cmd"):
            cmd = [shim] + cmd[1:]
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           timeout=timeout, env=env or os.environ.copy())
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except FileNotFoundError:
        return -2, f"command not found: {cmd[0]}"
    except Exception as e:
        return -3, str(e)


def detect_manifest(root):
    """Find the primary project manifest(s) to decide install strategy."""
    root = Path(root)
    candidates = []
    for name in ("package.json", "requirements.txt", "pyproject.toml", "Pipfile",
                 "go.mod", "Cargo.toml", "composer.json", "Gemfile", "pom.xml",
                 "build.gradle", "setup.py", "environment.yml", "Dockerfile"):
        p = root / name
        if p.exists():
            candidates.append(name)
    # nested package.json wins if root has none
    if not candidates:
        for sub in ("client", "frontend", "web", "app", "src", "server"):
            p = root / sub / "package.json"
            if p.exists():
                candidates.append(f"{sub}/package.json")
                break
    return candidates


def detect_start_cmd(root, manifests):
    """Figure out how to start the app. Returns list of candidate commands."""
    root = Path(root)
    cmds = []

    def add(cmd, cwd=None, name=None):
        cmds.append({"cmd": cmd, "cwd": cwd or str(root), "name": name or " ".join(cmd[:2])})

    if "package.json" in manifests or any(m.endswith("package.json") for m in manifests):
        pkg = json.loads((root / "package.json").read_text(encoding="utf-8", errors="ignore"))
        scripts = pkg.get("scripts", {})
        for key in ("start", "dev", "serve", "preview", "run"):
            if key in scripts and scripts[key]:
                add(["npm", "run", key], name=f"npm run {key}")
                break
        # next/vite/astro have dev conventions
        for key in ("dev", "start"):
            if key in scripts:
                add(["npx", key], name=f"npx {key}")
        if "vite" in str(pkg.get("devDependencies", {})) or "vite" in str(pkg.get("dependencies", {})):
            add(["npx", "vite", "--host", "127.0.0.1"], name="npx vite")
    if "requirements.txt" in manifests or "pyproject.toml" in manifests or "setup.py" in manifests:
        # streamlit apps first (they're web UIs, most demo-worthy)
        reqs = ""
        if (root / "requirements.txt").exists():
            reqs = (root / "requirements.txt").read_text(encoding="utf-8", errors="ignore").lower()
        for f in ("app.py", "dashboard.py", "streamlit_app.py"):
            if (root / f).exists() and ("streamlit" in reqs or "streamlit" in
                    (root / f).read_text(encoding="utf-8", errors="ignore").lower()[:2000]):
                add([sys_python(), "-m", "streamlit", "run", f,
                     "--server.address", "127.0.0.1", "--server.port", "8501"], name=f"streamlit {f}")
        # fastapi/flask servers
        for f in ("app.py", "main.py", "server.py", "run.py", "wsgi.py", "manage.py"):
            if (root / f).exists():
                if f == "manage.py":
                    add([sys_python(), "manage.py", "runserver", "127.0.0.1:8000"], name="django runserver")
                else:
                    add([sys_python(), f], name=f"python {f}")
                break
        if (root / "app").exists() or (root / "src").exists():
            add([sys_python(), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
                name="uvicorn main:app")
    if "go.mod" in manifests:
        add(["go", "run", "."], name="go run .")
    if "Cargo.toml" in manifests:
        add(["cargo", "run"], name="cargo run")
    if "composer.json" in manifests:
        add(["php", "-S", "127.0.0.1:8000"], name="php -S")
    if "Gemfile" in manifests:
        add(["bundle", "exec", "rails", "server"], name="rails server")
    if "Dockerfile" in manifests:
        add(["docker", "compose", "up"], name="docker compose up")
    return cmds


def install_deps(root, manifests):
    """Install deps for the detected manifests. Returns (ok, log)."""
    root = Path(root)
    log = []
    if "package.json" in manifests or any(m.endswith("package.json") for m in manifests):
        pkgdir = root
        if any(m.endswith("package.json") for m in manifests):
            m = [x for x in manifests if x.endswith("package.json")][0]
            pkgdir = root / Path(m).parent
        if (pkgdir / "node_modules").exists():
            log.append("node_modules present (skipping npm install)")
        else:
            rc, out = _run(["npm", "install", "--no-audit", "--no-fund"], pkgdir)
            log.append(f"npm install: rc={rc} {out[-400:]}")
            if rc != 0:
                rc2, out2 = _run(["npm", "install", "--no-audit", "--no-fund", "--legacy-peer-deps"], pkgdir)
                log.append(f"npm install (legacy-peer-deps): rc={rc2} {out2[-400:]}")
                rc = rc2 if rc2 == 0 else rc
            if rc != 0:
                return False, "\n".join(log)
    if "requirements.txt" in manifests:
        # skip if already installed (fast path)
        if (root / "site_done").exists():
            log.append("deps already installed (cached)")
        else:
            rc, out = _run([sys_python(), "-m", "pip", "install", "-r", "requirements.txt", "-q"], root)
            log.append(f"pip install: rc={rc} {out[-400:]}")
            if rc == 0:
                try:
                    (root / "site_done").write_text("1", encoding="utf-8")
                except Exception:
                    pass
            else:
                return False, "\n".join(log)
    if "pyproject.toml" in manifests:
        rc, out = _run([sys_python(), "-m", "pip", "install", "-e", ".", "-q"], root)
        log.append(f"pip install -e .: rc={rc} {out[-400:]}")
        if rc != 0:
            log.append("pyproject install failed (continuing)")
    if "go.mod" in manifests:
        rc, out = _run(["go", "mod", "tidy"], root)
        log.append(f"go mod tidy: rc={rc} {out[-300:]}")
    if "Cargo.toml" in manifests:
        rc, out = _run(["cargo", "build"], root)
        log.append(f"cargo build: rc={rc} {out[-300:]}")
    return True, "\n".join(log)


def sys_python():
    """Find a real python interpreter (skip MS Store stubs that return rc=9009)."""
    import sys as _sys
    # 1) the interpreter running this server is guaranteed real
    exe = _sys.executable
    if exe:
        return exe
    # 2) fallbacks
    for cand in ("python3", "python", "py"):
        p = shutil.which(cand)
        if not p:
            continue
        try:
            r = subprocess.run([p, "-c", "print(1)"], capture_output=True, timeout=10)
            if r.returncode == 0:
                return p
        except Exception:
            continue
    return "python"


def find_free_port(preferred=8000):
    import socket
    for port in range(preferred, preferred + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0


def is_up(url, timeout=3):
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status < 500
    except Exception:
        return False


def wait_up(url, wait=HEALTH_WAIT):
    for _ in range(wait):
        if is_up(url):
            return True
        time.sleep(1)
    return False


def start_app(root, manifests, port):
    """Try start commands until one responds. Returns (proc, url, log)."""
    cmds = detect_start_cmd(root, manifests)
    log = []
    for c in cmds:
        log.append(f"trying: {c['name']} (cwd {c['cwd']})")
        cmd = list(c["cmd"])
        if os.name == "nt" and cmd and cmd[0] in ("npm", "npx", "yarn", "pnpm", "go", "cargo"):
            shim = shutil.which(cmd[0] + ".cmd") or shutil.which(cmd[0] + ".exe")
            if shim and shim.endswith(".cmd"):
                cmd = [shim] + cmd[1:]
        try:
            proc = subprocess.Popen(
                cmd, cwd=c["cwd"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PORT": str(port), "HOST": "127.0.0.1"})
        except Exception as e:
            log.append(f"  spawn failed: {e}")
            continue
        # probe the assigned port first, then common defaults
        url = None
        for p in (port, 3000, 5173, 8080, 8000, 8501):
            u = f"http://127.0.0.1:{p}"
            if wait_up(u, wait=12):
                url = u
                break
        if url:
            log.append(f"  UP at {url}")
            return proc, url, "\n".join(log)
        # not up — check if process died immediately (CLI, not a server)
        rc = proc.poll()
        if rc is not None:
            log.append(f"  exited immediately (rc={rc}) — likely a CLI, skipping")
            proc = None
            continue
        # still alive but no port — kill and try next
        proc.kill()
        log.append("  no response, killed")
    return None, None, "\n".join(log)


def run_project(root, port=None):
    """Full pipeline: detect -> install -> start -> health. Returns status dict."""
    root = Path(root)
    port = port or find_free_port()
    manifests = detect_manifest(root)
    log = [f"manifests: {manifests}"]
    if not manifests:
        return {"ok": False, "log": "\n".join(log), "reason": "no manifest found"}

    ok, out = install_deps(root, manifests)
    log.append(out)
    if not ok:
        return {"ok": False, "log": "\n".join(log), "reason": "dependency install failed"}

    proc, url, out = start_app(root, manifests, port)
    log.append(out)
    if not proc or not url:
        return {"ok": False, "log": "\n".join(log), "reason": "app did not start"}

    return {"ok": True, "url": url, "port": int(url.rsplit(":", 1)[1].rstrip("/")),
            "log": "\n".join(log), "proc": proc}
