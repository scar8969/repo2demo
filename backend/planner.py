"""Demo planner: LLM turns analysis into a guided demo script (JSON)."""
import json
from . import llm

PLAN_SYSTEM = """You are a demo director. Given a repo analysis, produce a JSON demo plan.

The demo is an interactive guided tour: the viewer clicks "Next" and you narrate
the project's real screens/features. Steps must be grounded in the ACTUAL files
and routes found in the analysis — do not invent features.

Return JSON exactly like:
{
  "title": "Short catchy title",
  "tagline": "One-line pitch",
  "audience": "investors" | "developers" | "general",
  "hook": "1-2 sentence opening narration",
  "steps": [
    {
      "title": "Step title",
      "narration": "What the viewer is looking at, 1-3 sentences, concrete, references real files/features",
      "target": "landing" | "login" | "dashboard" | "feature" | "api" | "architecture" | "database" | "result",
      "file": "path/to/relevant/file.py (must exist in the analysis)",
      "detail": "Optional technical detail to highlight"
    }
  ],
  "highlights": ["3-5 impressive things worth showing"],
  "skip": ["things NOT worth showing / known weak spots"]
}

Rules:
- 5-9 steps, ordered as a story: problem -> entry -> core flow -> payoff.
- Every step.file must be one of the files listed in the analysis.
- target values only from the allowed list.
- Be honest: if the repo has no auth, don't add a login step.
"""


def plan_demo(analysis, repo_url, user_desc="", audience="investors"):
    summary = analysis["summary"]
    readme = analysis.get("readme", "")
    readme_part = f"\nREADME (project's own description):\n{readme[:3500]}" if readme else ""
    aud_guide = {
        "investors": "Emphasize what the product does, why it matters, market/impact angle, impressive features, and the payoff. Skip deep technical internals.",
        "developers": "Emphasize architecture, tech choices, API design, code quality, and interesting implementation details. Reference specific files and patterns.",
        "general": "Keep it simple and accessible. Focus on what the user experiences, plain-language narration, avoid jargon.",
    }.get(audience, "")
    prompt = f"""Repo: {repo_url}
User description: {user_desc or '(none)'}
Audience: {audience} — {aud_guide}
{readme_part}

ANALYSIS:
{summary}

Create the demo plan JSON now."""
    return llm.chat_json(prompt, PLAN_SYSTEM, model=llm.BIG, temperature=0.3)


VALID_TARGETS = {"landing", "login", "dashboard", "feature", "api",
                 "architecture", "database", "result"}


def validate_plan(plan, analysis):
    """Sanity-check plan against real files; drop steps referencing missing files."""
    files = set(analysis["files"])
    ok_steps = []
    for s in plan.get("steps", []):
        f = s.get("file", "")
        if f and f not in files:
            # try basename match
            base = f.split("/")[-1]
            match = [x for x in files if x.split("/")[-1] == base]
            if match:
                s["file"] = match[0]
            else:
                s["file"] = ""
        t = s.get("target", "")
        if t and t not in VALID_TARGETS:
            s["target"] = "feature"
        ok_steps.append(s)
    plan["steps"] = ok_steps
    return plan
