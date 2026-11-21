"""Static code screening + isolated subprocess execution.
Layers: AST screen, restricted builtins, separate process, stripped env, memory/file-size/CPU limits, timeout,
and (when the host allows) an empty network namespace via `unshare --net`. Still not a full security boundary:
for untrusted LLM-written code add container/gVisor isolation (see docs/SECURITY.md)."""
import ast, functools, json, os, resource, shutil, subprocess, sys
from pathlib import Path

ALLOWED_IMPORTS = {"cadquery", "math"}
BANNED_NAMES = {"open", "eval", "exec", "compile", "__import__", "globals", "locals", "getattr", "setattr", "input", "breakpoint"}
RUNNER = str(Path(__file__).with_name("runner.py"))


def static_check(code):
    """Return list of violations (empty = OK)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"syntax error: {e}"]
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            bad += [f"import {a.name}" for a in n.names if a.name.split(".")[0] not in ALLOWED_IMPORTS]
        elif isinstance(n, ast.ImportFrom):
            if (n.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                bad.append(f"from {n.module} import ...")
        elif isinstance(n, ast.Name) and n.id in BANNED_NAMES:
            bad.append(f"use of {n.id}")
        elif isinstance(n, ast.Attribute) and n.attr.startswith("__"):
            bad.append(f"dunder attribute {n.attr}")
    return bad


@functools.lru_cache(maxsize=1)
def network_isolation_available():
    if os.environ.get("SHIELDCAD_SANDBOX_NETNS", "1") == "0" or not shutil.which("unshare"):
        return False
    try:
        return subprocess.run(["unshare", "--net", "true"], capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


def mem_mb():
    return int(os.environ.get("SHIELDCAD_SANDBOX_MEM_MB", "4096"))


def info():
    """Recorded in every report so reviewers can see which protections were active."""
    return {"network_isolated": network_isolation_available(), "mem_limit_mb": mem_mb(),
            "timeout_s": int(os.environ.get("SHIELDCAD_SANDBOX_TIMEOUT", "90"))}


def _limits():
    m = mem_mb() << 20
    resource.setrlimit(resource.RLIMIT_AS, (m, m))
    resource.setrlimit(resource.RLIMIT_FSIZE, (512 << 20, 512 << 20))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def execute(code, workdir, timeout=None):
    """Returns (ok, metrics_or_error_message)."""
    workdir = Path(workdir).resolve()
    (workdir / "part.py").write_text(code)
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(workdir)}  # no inherited secrets
    timeout = timeout or info()["timeout_s"]
    cmd = [sys.executable, "-I", RUNNER, str(workdir / "part.py"), str(workdir)]
    if network_isolation_available():
        cmd = ["unshare", "--net"] + cmd
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=workdir, env=env,
                           preexec_fn=_limits, start_new_session=True)
    except subprocess.TimeoutExpired:
        return False, f"timeout after {timeout}s"
    for line in p.stdout.splitlines():
        if line.startswith("@@METRICS@@"):
            return True, json.loads(line[len("@@METRICS@@"):])
        if line.startswith("@@ERROR@@"):
            return False, line[len("@@ERROR@@"):]
    return False, (p.stderr or "no output")[-500:]
