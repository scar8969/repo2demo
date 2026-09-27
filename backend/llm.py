"""LLM access for repo2demo via relay-ai (OpenAI-compatible)."""

import json, os, re, time, urllib.request, urllib.error

BASE = os.environ.get("R2D_BASE_URL", "https://relay-ai.cc/v1")
KEY = os.environ.get("R2D_API_KEY", os.environ.get("RELAYAI_API_KEY", ""))
FAST = os.environ.get("R2D_FAST_MODEL", "deepseek-v4-flash")
BIG = os.environ.get("R2D_BIG_MODEL", "deepseek-v4-pro")
# fallback chain: if BIG fails, try FAST before giving up
BIG_FALLBACK = [BIG, FAST]


def _api_call(messages, model, temperature=0.3, max_tokens=8192, timeout=300):
    """Single API call (no retry). Raises on failure."""
    body = json.dumps({
        "model": model, "messages": messages,
        "temperature": temperature, "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        BASE + "/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    return data["choices"][0]["message"]["content"]


def _chat(messages, model, temperature=0.3, max_tokens=8192,
          timeout=300, retries=3, fallback_models=None):
    """Call the LLM. Retries transient errors (5xx/429/timeout), not 4xx.
    If fallback_models is provided, tries them in order before giving up."""
    models = fallback_models or [model]
    last_err = None
    for m in models:
        for attempt in range(retries):
            try:
                return _api_call(messages, m, temperature, max_tokens, timeout)
            except urllib.error.HTTPError as e:
                err = f"HTTP {e.code}: {e.read().decode()[:300]}"
                # 4xx errors (except 429) are permanent — don't retry
                if 400 <= e.code < 500 and e.code != 429:
                    raise RuntimeError(f"LLM call failed: {err}")
                last_err = err
                if e.code == 429:
                    time.sleep(5 * (attempt + 1))  # longer backoff for rate limit
                else:
                    time.sleep(2 * (attempt + 1))
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = str(e)
                time.sleep(2 * (attempt + 1))
        # this model drained all retries — try next fallback
    raise RuntimeError(f"LLM call failed after all retries: {last_err}")


def chat(prompt, system=None, model=None, temperature=0.3, max_tokens=8192):
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    return _chat(msgs, model or FAST, temperature=temperature, max_tokens=max_tokens)


def chat_json(prompt, system=None, model=None, temperature=0.2, max_tokens=8192):
    """Ask for JSON, strip fences, return parsed dict. Uses BIG with fallback."""
    sys = (system or "") + "\n\nRespond with ONLY valid JSON—no markdown fences, no commentary."
    m = model or BIG
    fb = BIG_FALLBACK if m == BIG else None
    out = _chat([{"role": "system", "content": sys}, {"role": "user", "content": prompt}],
                m, temperature=temperature, max_tokens=max_tokens, fallback_models=fb)
    out = re.sub(r"^```(?:json)?\s*|\s*```$", "", out.strip())
    # use lazy match to grab the first complete JSON object (avoids greedy swallowing prose)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        # balanced-brace extraction: find candidate object spans and try parsing each
        for m in re.finditer(r"\{", out):
            start = m.start()
            depth = 0
            end = -1
            for i in range(start, len(out)):
                if out[i] == "{":
                    depth += 1
                elif out[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end == -1:
                continue
            try:
                obj = json.loads(out[start:end])
                if isinstance(obj, dict) and "steps" in obj:
                    return obj
            except json.JSONDecodeError:
                continue
        raise ValueError("LLM did not return valid JSON: " + out[:400])