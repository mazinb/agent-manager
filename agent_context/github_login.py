"""Optional GitHub sign-in (minimal scope, read-only, no repo access).

Scope is `read:user` only — the app sees the public profile login and nothing
else. The GitHub access token is exchanged for the login name and discarded
immediately; the only credential kept is the agent-manager API token the
token flow already issues (label github:<login>). GitHub sign-in is
optional: plain tokens keep working as before.
"""
import json
import secrets
import time
import urllib.parse
import urllib.request

SCOPE = "read:user"
STATE_TTL = 600  # 10 minutes

_states = {}


class GitHubError(Exception):
    pass


def configured(env):
    return bool(env.get("GITHUB_CLIENT_ID")) and bool(
        env.get("GITHUB_CLIENT_SECRET"))


def new_state():
    s = secrets.token_urlsafe(16)
    _states[s] = time.time() + STATE_TTL
    return s


def pop_state(state):
    """One-shot: True only for a known state within its TTL."""
    exp = _states.pop(state, None)
    return exp is not None and exp > time.time()


def build_authorize_url(client_id, redirect_uri, state):
    q = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "state": state,
    })
    return "https://github.com/login/oauth/authorize?" + q


def _post_json(url, params, headers=None, http=None):
    if http is None:
        http = urllib.request
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with http.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def _get_json(url, token, http=None):
    if http is None:
        http = urllib.request
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "agent-context-brain",
    })
    with http.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def complete(code, state, env, redirect_uri="", http=None):
    """state+code -> github login name. Raises GitHubError on any failure."""
    if not pop_state(state):
        raise GitHubError("bad or expired state")
    if not code:
        raise GitHubError("missing code")
    http = http or urllib.request
    try:
        tok = _post_json(
            "https://github.com/login/oauth/access_token",
            {"client_id": env.get("GITHUB_CLIENT_ID", ""),
             "client_secret": env.get("GITHUB_CLIENT_SECRET", ""),
             "code": code,
             "redirect_uri": redirect_uri},
            {"Accept": "application/json"}, http)
    except Exception as e:
        raise GitHubError(f"token exchange failed: {e}") from e
    access = tok.get("access_token")
    if not access:
        raise GitHubError(f"github rejected the code: {tok.get('error')}")
    try:
        me = _get_json("https://api.github.com/user", access, http)
    except Exception as e:
        raise GitHubError(f"profile fetch failed: {e}") from e
    login = me.get("login")
    if not login:
        raise GitHubError("no login in profile")
    return login
