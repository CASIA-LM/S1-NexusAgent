"""Sandbox built-in tools — always available in CodeAct, never go through tool retrieval.

Design:
  - SANDBOX_TOOLS_PY   : Python helper module written to /home/work/sandbox_tools.py
                         inside the AIO sandbox Docker container at session startup.
                         Functions call the sandbox's own REST API at localhost:8080.
  - BUILTIN_TOOLS_PROMPT : Prompt section describing the helpers to the LLM.

Why not LangChain StructuredTools:
  The AIO sandbox runs as a Docker container. The Jupyter kernel runs *inside* that
  container and cannot import host-side Python modules (workflow.tools.*).
  Instead, we write a self-contained helper module to the sandbox filesystem that
  calls the sandbox's internal REST API (localhost:8080) — completely bypassing
  the Jupyter kernel for file and bash operations.

These tools are intentionally excluded from:
  - workflow/tools/__init__.py  (tools / tool_registry / vector_store)
  - retrieval_tools_node        (ToolRetriever)
"""

# ── Internal sandbox API base ─────────────────────────────────────────────────
# Docker: external 9001 → internal 8080. Jupyter calls localhost:8080 from inside.
# Override with SANDBOX_INTERNAL_URL env var if your setup differs.
_SANDBOX_INTERNAL_URL = "http://localhost:8080"

# ── One-line path bootstrap (prepended to every Jupyter script) ───────────────
# Replaces the old 3-line work_dir block. Sets cwd + sys.path in one shot.
# Must survive kernel restarts, hence injected every execution.
PATH_SETUP_LINE = (
    'import os,sys;'
    'os.chdir("/home/work");'
    '"/home/work" not in sys.path and sys.path.insert(0,"/home/work")\n'
)

# ── sandbox_tools.py content (written to sandbox filesystem) ──────────────────
SANDBOX_TOOLS_PY = f'''\
"""
sandbox_tools.py — Built-in sandbox utilities. Auto-injected at session startup.

Provides direct REST API access from within Jupyter WITHOUT consuming kernel state.
All functions are synchronous (safe to call anywhere in <execute> blocks).

Usage:
    from sandbox_tools import list_files, read_file, bash_exec, grep_files

Sandbox API: {_SANDBOX_INTERNAL_URL} (internal Docker port)
Override with env var SANDBOX_INTERNAL_URL if needed.
"""
import os as _os

# ── HTTP helper (httpx preferred, urllib fallback) ───────────────────────────
try:
    import httpx as _httpx

    def _post(url, payload, timeout=30):
        with _httpx.Client(timeout=timeout) as _c:
            return _c.post(url, json=payload).json()
except ImportError:
    import urllib.request as _req
    import json as _json

    def _post(url, payload, timeout=30):
        _data = _json.dumps(payload).encode()
        _r = _req.Request(url, data=_data, headers={{"Content-Type": "application/json"}})
        with _req.urlopen(_r, timeout=timeout) as _resp:
            return _json.loads(_resp.read())

_BASE = _os.environ.get("SANDBOX_INTERNAL_URL", "{_SANDBOX_INTERNAL_URL}")


# ── list_files ────────────────────────────────────────────────────────────────
def list_files(path: str, recursive: bool = False) -> str:
    """List files in a sandbox directory.

    Does NOT use the Jupyter kernel — calls sandbox file API directly.

    Args:
        path: Absolute sandbox path, e.g. "/home/work/outputs/"
        recursive: Recurse into subdirectories (default False)

    Returns:
        Formatted string with file types and sizes.

    Example:
        from sandbox_tools import list_files
        print(list_files("/home/work/outputs/"))
    """
    data = _post(
        f"{{_BASE}}/v1/file/list",
        {{"path": path, "recursive": recursive, "include_size": True, "sort_by": "name"}},
    )
    if not data.get("success"):
        return f"Error listing {{path}}: {{data.get('message', 'unknown error')}}"
    files = data.get("data", {{}}).get("files", [])
    if not files:
        return f"(empty: {{path}})"
    lines = []
    for f in files:
        tag = "DIR " if f.get("is_dir") else "FILE"
        name = f.get("name", "")
        size = f.get("size")
        sz = f"  ({{size}}B)" if size else ""
        lines.append(f"[{{tag}}] {{name}}{{sz}}")
    return "\\n".join(lines)


# ── read_file ────────────────────────────────────────────────────────────────
def read_file(file: str, start_line: int = None, end_line: int = None) -> str:
    """Read file content from the sandbox filesystem.

    Supports partial reads (start_line/end_line) for large files.
    Does NOT use the Jupyter kernel.

    Args:
        file: Absolute sandbox path, e.g. "/home/work/outputs/result.csv"
        start_line: 0-based start line (inclusive). None = read from beginning.
        end_line: 0-based end line (exclusive). None = read to end.

    Returns:
        File content string (truncated at 5000 chars if large).

    Example:
        from sandbox_tools import read_file
        print(read_file("/home/work/outputs/result.csv", start_line=0, end_line=10))
    """
    payload = {{"file": file}}
    if start_line is not None:
        payload["start_line"] = start_line
    if end_line is not None:
        payload["end_line"] = end_line
    data = _post(f"{{_BASE}}/v1/file/read", payload)
    if not data.get("success"):
        return f"Error reading {{file}}: {{data.get('message', 'unknown error')}}"
    content = data.get("data", {{}}).get("content", "")
    if len(content) > 5000:
        content = content[:2500] + "\\n...[ OUTPUT TRUNCATED — use start_line/end_line ]...\\n" + content[-1000:]
    return content


# ── bash_exec ────────────────────────────────────────────────────────────────
def bash_exec(cmd: str, timeout: int = 60) -> str:
    """Execute a bash command WITHOUT affecting Jupyter kernel state.

    Uses the sandbox bash/shell API — runs in a separate process.
    Jupyter variables and imports are completely unaffected.

    Use for:
        - Installing packages : bash_exec("pip install seaborn -q")
        - File operations     : bash_exec("cp /home/work/uploads/data.csv /home/work/workspace/")
        - System commands     : bash_exec("mkdir -p /home/work/outputs/plots")
        - Long shell tasks    : bash_exec("Rscript analysis.R", timeout=120)

    Args:
        cmd: Bash command string
        timeout: Max execution seconds (capped at 300)

    Returns:
        Combined stdout/stderr output string.

    Example:
        from sandbox_tools import bash_exec
        print(bash_exec("pip install seaborn scikit-learn -q"))
        # Now safely import seaborn in the next <execute> block
    """
    timeout = min(timeout, 300)
    for endpoint in ["/v1/bash/exec", "/v1/shell/exec"]:
        try:
            data = _post(f"{{_BASE}}{{endpoint}}", {{"command": cmd, "timeout": timeout}}, timeout=timeout + 15)
            if data.get("success"):
                result = data.get("data", {{}})
                out = result.get("output") or result.get("stdout", "")
                err = result.get("stderr", "")
                code = result.get("exit_code", 0)
                parts = []
                if out:
                    parts.append(out[-2000:] if len(out) > 2000 else out)
                if err and code not in (0, None):
                    parts.append(f"[stderr]: {{err[-400:]}}")
                if code not in (0, None):
                    parts.append(f"[exit_code: {{code}}]")
                return "\\n".join(p for p in parts if p) or "(no output)"
        except Exception:
            continue
    return "Error: bash execution failed (tried /v1/bash/exec and /v1/shell/exec)"


# ── grep_files ───────────────────────────────────────────────────────────────
def grep_files(
    path: str,
    pattern: str,
    include: list = None,
    context_before: int = 0,
    context_after: int = 0,
    fixed_strings: bool = False,
) -> str:
    """Search file contents with regex across sandbox directories.

    Faster and more reliable than running subprocess grep inside Jupyter.

    Args:
        path: Directory to search, e.g. "/home/work/"
        pattern: Regex or literal search pattern
        include: File extension filters, e.g. [".py", ".csv"] (None = all files)
        context_before: Lines of context before each match (0-5)
        context_after: Lines of context after each match (0-5)
        fixed_strings: If True, treat pattern as literal (not regex)

    Returns:
        Formatted match results string (up to 50 matches shown).

    Example:
        from sandbox_tools import grep_files
        print(grep_files("/home/work/", "def analyze", include=[".py"]))
    """
    payload = {{
        "path": path,
        "pattern": pattern,
        "context_before": min(context_before, 5),
        "context_after": min(context_after, 5),
        "fixed_strings": fixed_strings,
        "max_results": 100,
        "recursive": True,
    }}
    if include:
        payload["include"] = include
    data = _post(f"{{_BASE}}/v1/file/grep", payload, timeout=20)
    if not data.get("success"):
        return f"Grep error: {{data.get('message', 'unknown error')}}"
    result = data.get("data", {{}})
    matches = result.get("matches", [])
    count = result.get("match_count", 0)
    if not matches:
        return f"No matches for '{{pattern}}' in {{path}}"
    lines = [f"Found {{count}} match(es):"]
    for m in matches[:50]:
        lines.append(f"  {{m.get('file','?')}}:{{m.get('line_number','?')}}: {{m.get('line','').rstrip()}}")
    if count > 50:
        lines.append(f"  ... ({{count - 50}} more not shown)")
    return "\\n".join(lines)
'''

# ── System prompt section ─────────────────────────────────────────────────────
BUILTIN_TOOLS_PROMPT = """\
## Built-in Sandbox Tools (Always Available — NOT retrieved, NOT imported from workflow)

These helpers are pre-written to `/home/work/sandbox_tools.py` at session startup.
They call the sandbox REST API directly — **zero Jupyter kernel state consumed**.

```python
from sandbox_tools import list_files, read_file, bash_exec, grep_files
```

| Tool | Signature | When to use |
|------|-----------|-------------|
| `list_files` | `list_files(path, recursive=False)` | Check uploads/outputs directory contents |
| `read_file` | `read_file(file, start_line=None, end_line=None)` | Verify output file content without loading into memory |
| `bash_exec` | `bash_exec(cmd, timeout=60)` | pip install, mkdir, cp, mv — **does NOT reset Jupyter variables** |
| `grep_files` | `grep_files(path, pattern, include=None, ...)` | Multi-file regex search across sandbox dirs |

**Prefer these over Python equivalents for non-compute tasks:**
- Check files    → `list_files('/home/work/outputs/')` NOT `os.listdir()`
- Verify output  → `read_file('/home/work/outputs/result.csv', 0, 5)` NOT `open(...).read()`
- Install pkg    → `bash_exec('pip install seaborn -q')` ← Jupyter state is preserved after this
- Search code    → `grep_files('/home/work/', 'import pandas', include=['.py'])`
"""
