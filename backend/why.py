"""Why-mode: answer questions about the repo, grounded in actual code."""
import re
from . import llm

WHY_SYSTEM = """You are a code explainer. Answer the user's question about a specific
repository using ONLY the code excerpts provided. Cite exact file paths and line
numbers when possible. If the excerpt doesn't contain the answer, say so honestly
and suggest what to look at next. Keep answers under 150 words, concrete, no fluff."""

# common secret patterns to mask before sending to LLM
_SECRET_RE = re.compile(
    r'(api[_-]?key|apikey|secret|password|passwd|token|auth|credential)'
    r'\s*[:=]\s*[\'"]([^\s\'"]{8,})[\'"]',
    re.IGNORECASE)
_PRIVKEY_RE = re.compile(r'-----BEGIN .*?PRIVATE KEY.*?-----.*?-----END .*?-----', re.S)
_ENV_URL_RE = re.compile(r'(://)[^:]+:[^@]+@')

def _redact_secrets(text):
    """Mask common secret patterns BEFORE sending code to the LLM."""
    t = _SECRET_RE.sub(r'\1=[REDACTED]', text)
    t = _PRIVKEY_RE.sub('[PRIVATE KEY REDACTED]', t)
    t = _ENV_URL_RE.sub(r'\1[REDACTED]@', t)
    return t


def _find_excerpts(analysis, query, k=8):
    """Find the most relevant code excerpts for a query (keyword + route/feature match)."""
    q = query.lower()
    qwords = set(re.findall(r"[a-z0-9_]{3,}", q))
    scored = []
    for rel, txt in zip(analysis["files"], analysis["contents"]):
        low = txt.lower()
        score = 0
        for w in qwords:
            if w in low:
                score += 2
        # route/file name matches count extra
        for r in analysis.get("routes", []):
            if r["file"] == rel and any(w in r["path"].lower() for w in qwords):
                score += 3
        for f_ in analysis.get("features", []):
            if f_["file"] == rel and any(w in f_["features"] for w in qwords):
                score += 2
        if score > 0:
            scored.append((score, rel, txt))
    scored.sort(key=lambda x: -x[0])
    out = []
    for score, rel, txt in scored[:k]:
        # trim to relevant window around first keyword hit, keep line numbers
        low = txt.lower()
        pos = min((low.find(w) for w in qwords if w in low), default=0)
        start = max(0, pos - 1200)
        window = txt[start:start + 3000]
        # compute starting line number
        lineno = txt.count("\n", 0, start) + 1
        out.append(f"### {rel} (lines ~{lineno})\n{_redact_secrets(window)}")
    return "\n\n".join(out)


def answer_why(analysis, question, history=None):
    excerpts = _find_excerpts(analysis, question)
    if not excerpts:
        return {
            "answer": "I couldn't find code matching that in this repo. Try asking about a feature, file, or tech from the analysis.",
            "refs": [],
        }
    hist = ""
    if history:
        hist = "PREVIOUS CONVERSATION (for context):\n" + "\n".join(
            f"Q: {h.get('q','')}\nA: {h.get('a','')[:400]}" for h in history[-4:]) + "\n\n"
    prompt = f"""{hist}QUESTION: {question}

RELEVANT CODE:
{excerpts[:12000]}

Answer the question grounded in the code. End with a "References:" line listing the file paths you used."""
    out = llm.chat(prompt, WHY_SYSTEM, model=llm.FAST, temperature=0.2)
    refs = re.findall(r"###\s+([^\n]+)", excerpts)
    refs = list(dict.fromkeys(refs))[:6]
    # first excerpt snippet for inline display (trim to ~40 lines, redacted)
    snippet = ""
    if excerpts:
        first = excerpts.split("\n\n", 1)[0]
        lines = first.split("\n")
        snippet = "\n".join(lines[1:41])
    return {"answer": out, "refs": refs, "snippet": snippet}
