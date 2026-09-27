"""CLI mode: build a demo from the terminal without the web UI.

Usage:
  python cli.py https://github.com/user/repo [--desc "..." ] [--audience investors] [--out demo.json]
"""
import argparse, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend import analyzer, llm, planner, runner


def main():
    ap = argparse.ArgumentParser(description="repo2demo CLI")
    ap.add_argument("repo_url", help="GitHub repo URL")
    ap.add_argument("--desc", default="", help="optional project description")
    ap.add_argument("--audience", default="investors",
                    choices=["investors", "developers", "general"])
    ap.add_argument("--out", default="demo.json", help="output file")
    ap.add_argument("--run", action="store_true", help="try to run the app too")
    ap.add_argument("--why", default="", help="ask a question after building")
    args = ap.parse_args()

    t0 = time.time()
    print(f"[1/4] cloning {args.repo_url} ...")
    import tempfile
    workdir = Path(tempfile.mkdtemp(prefix="r2d_cli_"))
    repo_dir = analyzer.clone_repo(args.repo_url, workdir / "repo")

    print("[2/4] analyzing ...")
    analysis = analyzer.analyze_repo(repo_dir)
    analysis["summary"] = analyzer.summarize_for_llm(analysis)
    print(f"      {analysis['file_count']} files · stack: {', '.join(analysis['stack']) or '?'}")

    print(f"[3/4] planning demo for {args.audience} ...")
    plan = planner.plan_demo(analysis, args.repo_url, args.desc, audience=args.audience)
    plan = planner.validate_plan(plan, analysis)
    plan["audience"] = args.audience
    plan["health"] = analyzer.demo_health(plan, analysis)
    print(f"      title: {plan.get('title')}")
    print(f"      steps: {len(plan.get('steps', []))} · health: {plan['health']['score']}/100")

    demo = {
        "job_id": "cli", "repo_url": args.repo_url, "description": args.desc,
        "meta": {}, "analysis": {k: v for k, v in analysis.items() if k not in ("contents", "summary")},
        "plan": plan, "created": time.time(),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(demo, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"      saved to {out.resolve()}")

    if args.run:
        print("[4/4] running app ...")
        res = runner.run_project(repo_dir)
        print(f"      ok={res.get('ok')} url={res.get('url')} reason={res.get('reason','')}")

    if args.why:
        print(f"\nQ: {args.why}")
        ans = __import__("backend.why", fromlist=["answer_why"]).answer_why(
            {"files": analysis["files"], "contents": analysis["contents"],
             "routes": analysis["routes"], "features": analysis["features"]}, args.why)
        print(f"A: {ans['answer'][:800]}")

    print(f"\ndone in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
