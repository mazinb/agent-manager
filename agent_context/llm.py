"""Minimal OpenAI-compatible chat client (stdlib urllib) for cited answers."""
import json
import urllib.request


def ask(base_url, model, question, chunks, timeout=120, api_key=""):
    """Synthesize an answer grounded in chunks; returns text or None."""
    if not chunks:
        return None
    ctx = "\n\n".join(
        f"[{i+1}] ({c['project']}/{c['kind']}) {c['heading']}\n{c['text']}"
        for i, c in enumerate(chunks[:10]))
    prompt = (
        "You are a retrieval assistant over a personal knowledge base. "
        "Answer the question using ONLY the numbered context snippets and "
        "cite them inline like [1] [2]. If the context is insufficient, say "
        "so plainly.\n\n### Context\n" + ctx +
        "\n\n### Question\n" + question)
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 800,
        "temperature": 0.2,
        "chat_template_kwargs": {"thinking": False},
    }).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 **({"Authorization": "Bearer " + api_key} if api_key else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return None
