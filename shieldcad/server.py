"""REST API + static web UI. Auth: X-API-Key header -> role (viewer < engineer < admin)."""
import collections, datetime, hashlib, hmac, json, os, re, time
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import audit
from .admin import data_dir, load_users
from .llm import LLM
from .parser import parse
from . import assembly as asm
from .pipeline import run, run_assembly, run_spec
from .revise import revise

RANK = {"viewer": 0, "engineer": 1, "admin": 2}
RUN_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
FILE_RE = re.compile(r"^(?:(?:part|assembly)\.(?:step|stl|iges|brep|3mf|obj|glb|py)|component_\d{1,2}\.(?:step|stl)|report\.json)$")
app = FastAPI(title="ShieldCAD", version="0.2.0", docs_url=None, redoc_url=None)


@app.middleware("http")
async def security_headers(request, call_next):
    r = await call_next(request)
    r.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:"
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["X-Frame-Options"] = "DENY"
    r.headers["Cache-Control"] = "no-store"
    return r


def runs_dir():
    return data_dir() / "runs"


class Window:
    """Sliding-window counter (in memory; use a shared store if you run several workers)."""
    def __init__(self):
        self.h = collections.defaultdict(collections.deque)

    def _prune(self, key, period):
        q, now = self.h[key], time.monotonic()
        while q and now - q[0] > period:
            q.popleft()
        return q

    def count(self, key, period):
        return len(self._prune(key, period))

    def hit(self, key, limit, period):
        q = self._prune(key, period)
        if len(q) >= limit:
            return False
        q.append(time.monotonic())
        return True


FAILS, GEN = Window(), Window()


def reset_limits():
    FAILS.h.clear(); GEN.h.clear()


def auth(min_role):
    def dep(request: Request, x_api_key: str = Header(default="")):
        ip = request.client.host if request.client else "?"
        if FAILS.count(ip, 300) >= int(os.environ.get("SHIELDCAD_MAX_FAILS", "10")):
            raise HTTPException(429, "too many failed attempts; try again later")
        h = hashlib.sha256(x_api_key.encode()).hexdigest()
        for name, u in load_users().items():
            if hmac.compare_digest(h, u["key_sha256"]):
                exp = u.get("expires")
                if exp and datetime.date.fromisoformat(exp) < datetime.date.today():
                    raise HTTPException(401, "API key expired")
                if RANK[u["role"]] < RANK[min_role]:
                    raise HTTPException(403, "insufficient role")
                return {"user": name, "role": u["role"]}
        FAILS.hit(ip, 10**9, 300)
        raise HTTPException(401, "invalid or missing API key")
    return dep


class Prompt(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)


class Generate(Prompt):
    confirmed: bool = False


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/me")
def me(u=Depends(auth("viewer"))):
    return u


@app.post("/api/parse")
def api_parse(b: Prompt, u=Depends(auth("engineer"))):
    spec, errors = parse(b.prompt)
    return {"spec": spec, "errors": errors}


@app.post("/api/generate")
def api_generate(b: Generate, u=Depends(auth("engineer"))):
    if not b.confirmed:
        raise HTTPException(400, "spec must be confirmed before generation")
    if not GEN.hit(u["user"], int(os.environ.get("SHIELDCAD_RATE_GEN_PER_MIN", "20")), 60):
        raise HTTPException(429, "generation rate limit exceeded")
    r = run(b.prompt, str(runs_dir()), u["user"], None, LLM.from_env())
    return {"status": r.status, "run_id": r.run_id, "errors": r.errors, "spec": r.spec, "report": r.report}


class AsmParse(BaseModel):
    prompt: str = Field(min_length=3, max_length=6000)
    fuse: bool = True


class AsmGenerate(AsmParse):
    confirmed: bool = False


@app.post("/api/assembly/parse")
def api_asm_parse(b: AsmParse, u=Depends(auth("engineer"))):
    plan = asm.plan_assembly(b.prompt, b.fuse)
    return {"plan": plan, "summary": asm.summary(plan), "errors": plan["errors"]}


@app.post("/api/assembly/generate")
def api_asm_generate(b: AsmGenerate, u=Depends(auth("engineer"))):
    if not b.confirmed:
        raise HTTPException(400, "assembly must be confirmed before generation")
    if not GEN.hit(u["user"], int(os.environ.get("SHIELDCAD_RATE_GEN_PER_MIN", "20")), 60):
        raise HTTPException(429, "generation rate limit exceeded")
    r = run_assembly(b.prompt, str(runs_dir()), u["user"], b.fuse)
    return {"status": r.status, "run_id": r.run_id, "errors": r.errors, "spec": r.spec, "report": r.report}


class Revise(BaseModel):
    changes: dict[str, float] = Field(min_length=1, max_length=12)


@app.post("/api/runs/{run_id}/revise")
def api_revise(run_id: str, b: Revise, u=Depends(auth("engineer"))):
    rep = _report(run_id, u)
    if rep.get("assembly"):
        plan, errors = asm.revise_plan(rep["assembly"]["plan"], b.changes)
        if errors:
            return {"status": "needs_input", "errors": errors, "run_id": None, "spec": rep["spec"], "report": {}}
        if not GEN.hit(u["user"], int(os.environ.get("SHIELDCAD_RATE_GEN_PER_MIN", "20")), 60):
            raise HTTPException(429, "generation rate limit exceeded")
        r = run_assembly(rep["prompt"], str(runs_dir()), u["user"], plan["fuse"], plan=plan, parent=run_id,
                         revision=rep.get("revision", 1) + 1, changes=b.changes)
        return {"status": r.status, "run_id": r.run_id, "errors": r.errors, "spec": r.spec, "report": r.report}
    new, errors = revise(rep["spec"], b.changes)
    if errors:
        return {"status": "needs_input", "errors": errors, "run_id": None, "spec": rep["spec"], "report": {}}
    if not GEN.hit(u["user"], int(os.environ.get("SHIELDCAD_RATE_GEN_PER_MIN", "20")), 60):
        raise HTTPException(429, "generation rate limit exceeded")
    r = run_spec(new, [], rep["prompt"], str(runs_dir()), u["user"], parent=run_id,
                 revision=rep.get("revision", 1) + 1, changes=b.changes)
    return {"status": r.status, "run_id": r.run_id, "errors": r.errors, "spec": r.spec, "report": r.report}


def _report(run_id, u):
    if not RUN_ID.match(run_id):
        raise HTTPException(404, "not found")
    f = runs_dir() / run_id / "report.json"
    if not f.exists():
        raise HTTPException(404, "not found")
    rep = json.loads(f.read_text())
    if u["role"] != "admin" and rep.get("user") != u["user"]:
        raise HTTPException(404, "not found")  # do not reveal other users' runs
    return rep


@app.get("/api/runs")
def list_runs(u=Depends(auth("viewer"))):
    out = []
    if runs_dir().exists():
        for d in sorted(runs_dir().iterdir(), reverse=True):
            f = d / "report.json"
            if RUN_ID.match(d.name) and f.exists():
                rep = json.loads(f.read_text())
                if u["role"] == "admin" or rep.get("user") == u["user"]:
                    out.append({"run_id": d.name, "user": rep.get("user"), "prompt": rep.get("prompt"),
                                "passed": (rep.get("validation") or {}).get("passed", False),
                                    "revision": rep.get("revision", 1), "parent_run_id": rep.get("parent_run_id"),
                                    "kind": "assembly" if rep.get("assembly") else "part"})
            if len(out) >= 50:
                break
    return out


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, u=Depends(auth("viewer"))):
    return _report(run_id, u)


@app.get("/api/runs/{run_id}/files/{name}")
def get_file(run_id: str, name: str, u=Depends(auth("viewer"))):
    _report(run_id, u)
    if not FILE_RE.match(name):
        raise HTTPException(404, "not found")
    p = runs_dir() / run_id / name
    if not p.exists():
        raise HTTPException(404, "not found")
    return FileResponse(p, filename=name)


@app.get("/api/audit/verify")
def audit_verify(u=Depends(auth("admin"))):
    ok, bad = audit.verify(runs_dir() / "audit.jsonl")
    return {"ok": ok, "first_bad_line": bad}


app.mount("/", StaticFiles(directory=str(Path(__file__).resolve().parent.parent / "static"), html=True), name="ui")


def main():
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SHIELDCAD_HOST", "127.0.0.1"), port=int(os.environ.get("SHIELDCAD_PORT", "8000")))


if __name__ == "__main__":
    main()
