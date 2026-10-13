"""Generic ingest: file scanner driven by config, plus services scanner.

Config sources shape (config.json -> "sources"):
  [
    {"type": "files", "roots": ["~/projects/*"], "include":
      ["README.md", ".cursor/rules/*.mdc"], "max_depth": 3},
    {"type": "memory", "path": "~/.hermes/profiles/*/memories/MEMORY.md"},
    {"type": "services"}   # systemd --user + docker ps + listening ports
  ]

Every file becomes one source; text is split into chunks on headings.
"""
import glob
import os
import re
import subprocess

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
             "dist", "build", ".next", "cache"}
MAX_FILE_BYTES = 512 * 1024

HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")


def _chunk_markdown(text, max_len=1400):
    """Split markdown into (heading, body) chunks by headings/paragraphs."""
    chunks = []
    heading = ""
    buf = []
    buf_len = 0

    def flush():
        nonlocal buf, buf_len
        body = "\n".join(buf).strip()
        if body:
            chunks.append((heading, body))
        buf, buf_len = [], 0

    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            flush()
            heading = m.group(2).strip()
            buf.append(line)
            buf_len += len(line)
            continue
        if buf_len + len(line) > max_len:
            flush()
        buf.append(line)
        buf_len += len(line) + 1
    flush()
    return chunks


def _safe_read(path):
    try:
        st = os.stat(path)
        if st.st_size > MAX_FILE_BYTES or not os.path.isfile(path):
            return None
        if st.st_size == 0:
            return None
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _iter_root_files(root, include, max_depth):
    root = os.path.expanduser(root)
    expanded = glob.glob(root) or ([root] if os.path.isdir(root) else [])
    for root in expanded:
        yield from _walk_root(root, include, max_depth)


def _walk_root(root, include, max_depth):
    if not os.path.isdir(root):
        return
    for inc in include:
        # walk with depth limit; match basename or relative suffix
        for dirpath, dirnames, filenames in os.walk(root):
            rel = dirpath[len(root):].strip("/")
            depth = 0 if not rel else len(rel.split("/"))
            dirnames[:] = [d for d in dirnames
                           if d not in SKIP_DIRS and not d.startswith(".env")]
            if depth > max_depth:
                dirnames[:] = []
                continue
            for fn in filenames:
                if fn.endswith(".env") or "token" in fn.lower() \
                        or "secret" in fn.lower():
                    continue
                relfn = os.path.join(rel, fn) if rel else fn
                if _glob_match(relfn, inc) or fn == inc:
                    yield os.path.join(dirpath, fn)


def _glob_match(name, pattern):
    from fnmatch import fnmatch
    return fnmatch(name, pattern) or fnmatch(os.path.basename(name), pattern)


def scan_files(source):
    """Yield (path, kind, project, chunks) for each matched file."""
    roots = source.get("roots", [])
    include = source.get("include", ["README.md"])
    max_depth = int(source.get("max_depth", 3))
    tag = source.get("tag", "files")
    for root in roots:
        for path in _iter_root_files(root, include, max_depth):
            text = _safe_read(path)
            if text is None:
                continue
            parts = os.path.expanduser(path).split(os.sep)
            # project = first path segment after ~/projects/ (or dir name)
            try:
                i = parts.index("projects")
                project = parts[i + 1] if len(parts) > i + 1 else parts[-2]
            except ValueError:
                project = parts[-2] if len(parts) > 1 else ""
            yield (os.path.expanduser(path), tag, project,
                   _chunk_markdown(text))


def scan_memory(source):
    """Hermes-style memory/user profile files."""
    path_pattern = os.path.expanduser(source.get("path", ""))
    for path in glob.glob(path_pattern):
        text = _safe_read(path)
        if text is None:
            continue
        project = os.path.basename(os.path.dirname(os.path.dirname(path)))
        yield (path, "memory", project, _chunk_markdown(text))


def _run(cmd, timeout=10):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def scan_services(source):
    """Running services, containers, ports -> one synthetic source."""
    lines = []
    out = _run(["systemctl", "--user", "list-units", "--type=service",
                "--state=running", "--no-legend", "--plain"])
    for line in out.splitlines():
        if line.strip():
            lines.append("service: " + line.strip())
    out = _run(["docker", "ps", "--format",
                "{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"])
    for line in out.splitlines():
        if line.strip():
            lines.append("container: " + line.replace("\t", " | "))
    if not lines:
        return
    text = "\n".join(lines)
    yield ("/proc/services-snapshot", "services", "(system)",
           [("Running services and containers", text)])


SCANNERS = {"files": scan_files, "memory": scan_memory, "services": scan_services}


def collect(config):
    """Yield (path, kind, project, chunks) across all configured sources."""
    for source in config.get("sources", []):
        fn = SCANNERS.get(source.get("type"))
        if fn:
            yield from fn(source)
