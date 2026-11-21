"""prompt -> spec -> (confirm) -> code -> static check -> sandbox -> validate -> (repair) -> outputs + audit."""
import hashlib, json, secrets, time
from dataclasses import dataclass, field
from pathlib import Path

from . import audit, sandbox
from .parser import parse
from .revise import editable
from .templates import generate
from .validator import validate, validate_assembly
from . import assembly as asm

DISCLAIMER = "DRAFT - generated geometry requires review and approval by a qualified engineer before use."


@dataclass
class Result:
    status: str                      # ok | failed | needs_input | rejected
    run_id: str
    spec: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    report: dict = field(default_factory=dict)
    out_dir: str = ""


def _attempt(code, expected, work):
    bad = sandbox.static_check(code)
    if bad:
        return False, {"error": "static check rejected code: " + "; ".join(bad)}
    ok, res = sandbox.execute(code, work)
    if not ok:
        return False, {"error": res}
    return True, {"metrics": res, "validation": validate(res, expected)}


def run(prompt, out_dir="out", user="local", confirm=None, llm=None, max_repairs=3):
    spec, errors = parse(prompt)
    return run_spec(spec, errors, prompt, out_dir, user, confirm, llm, max_repairs)


def run_spec(spec, errors, prompt, out_dir="out", user="local", confirm=None, llm=None, max_repairs=3,
             parent=None, revision=1, changes=None):
    """Generate from an already-parsed (and confirmed) spec. `parent`/`changes` record revision lineage."""
    run_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    audit_path = Path(out_dir) / "audit.jsonl"
    base = {"ts": time.time(), "user": user, "run_id": run_id, "prompt": prompt, "spec": spec,
            "parent_run_id": parent, "revision": revision, "changes": changes}

    if errors:
        audit.append(audit_path, {**base, "status": "needs_input", "errors": errors})
        return Result("needs_input", run_id, spec, errors)
    if confirm and not confirm(spec):
        audit.append(audit_path, {**base, "status": "rejected"})
        return Result("rejected", run_id, spec)

    work = Path(out_dir) / run_id
    work.mkdir(parents=True, exist_ok=True)
    tries, code, outcome = [], "", {}

    if spec["type"] == "custom":
        if not llm:
            msg = ["No template for this part type and no LLM configured (set SHIELDCAD_LLM_URL)."]
            audit.append(audit_path, {**base, "status": "needs_input", "errors": msg})
            return Result("needs_input", run_id, spec, msg)
        expected = {"bbox": spec["params"].get("bbox_hint")}
        generator, feedback = "llm", None
        for i in range(max_repairs + 1):
            code = llm.generate(prompt, feedback)
            ok, outcome = _attempt(code, expected, work)
            ok = ok and outcome["validation"]["passed"]
            tries.append({"attempt": i, "ok": ok})
            if ok:
                break
            feedback = outcome.get("error") or json.dumps(outcome["validation"]["checks"])
    else:
        code, expected = generate(spec)
        generator = "template:" + spec["type"]
        ok, outcome = _attempt(code, expected, work)
        ok = ok and outcome["validation"]["passed"]
        tries.append({"attempt": 0, "ok": ok})

    metrics = outcome.get("metrics", {})
    mass = metrics["volume"] * spec["density"] / 1e6 if metrics and spec.get("density") else None
    report = {"disclaimer": DISCLAIMER, "run_id": run_id, "generator": generator, "user": user, "prompt": prompt, "spec": spec, "editable": editable(spec),
              "parent_run_id": parent, "revision": revision, "changes": changes,
              "attempts": tries, "sandbox": sandbox.info(), "files": metrics.get("files", []), "metrics": metrics, "validation": outcome.get("validation"),
              "error": outcome.get("error"), "est_mass_kg": round(mass, 4) if mass else None,
              "code_sha256": hashlib.sha256(code.encode()).hexdigest()}
    (work / "report.json").write_text(json.dumps(report, indent=2))
    files = {f.name: audit.sha256_file(f) for f in work.iterdir() if f.suffix in (".step", ".stl", ".py", ".json")}
    audit.append(audit_path, {**base, "status": "ok" if ok else "failed", "generator": generator,
                              "code_sha256": report["code_sha256"], "files": files})
    return Result("ok" if ok else "failed", run_id, spec, [], report, str(work))


def run_assembly(prompt, out_dir="out", user="local", fuse=True, plan=None, parent=None, revision=1, changes=None):
    """Several components -> placed, verified, fused into one solid; exports single-solid + assembly + per-component files."""
    plan = plan or asm.plan_assembly(prompt, fuse)
    run_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    audit_path = Path(out_dir) / "audit.jsonl"
    summ = {"type": "assembly", "components": len(plan["components"]), "fuse": plan["fuse"]}
    base = {"ts": time.time(), "user": user, "run_id": run_id, "prompt": prompt, "spec": summ,
            "parent_run_id": parent, "revision": revision, "changes": changes}
    if plan["errors"]:
        audit.append(audit_path, {**base, "status": "needs_input", "errors": plan["errors"]})
        return Result("needs_input", run_id, summ, plan["errors"])
    work = Path(out_dir) / run_id
    work.mkdir(parents=True, exist_ok=True)
    code, expected = asm.build(plan)
    bad = sandbox.static_check(code)
    outcome = {"error": "static check rejected code: " + "; ".join(bad)} if bad else {}
    ok = False
    if not bad:
        ok, res = sandbox.execute(code, work)
        outcome = {"metrics": res, "validation": validate_assembly(res, expected, plan["fuse"])} if ok else {"error": res}
        ok = ok and outcome["validation"]["passed"]
    m = outcome.get("metrics", {})
    dens = [c["spec"].get("density") for c in plan["components"]]
    mass = sum(m["components"][f"component_{c['index']}"]["volume"] * d for c, d in zip(plan["components"], dens)) / 1e6 if m and all(dens) else None
    report = {"disclaimer": DISCLAIMER, "run_id": run_id, "generator": "assembly:template", "user": user, "prompt": prompt,
              "spec": summ, "editable": asm.editable_plan(plan), "parent_run_id": parent, "revision": revision, "changes": changes,
              "attempts": [{"attempt": 0, "ok": ok}], "sandbox": sandbox.info(), "files": m.get("files", []),
              "metrics": {k: v for k, v in m.items() if k not in ("components",)}, "validation": outcome.get("validation"),
              "assembly": {"plan": plan, "summary": asm.summary(plan), "interference": (outcome.get("validation") or {}).get("interference", [])},
              "error": outcome.get("error"), "est_mass_kg": round(mass, 4) if mass else None,
              "code_sha256": hashlib.sha256(code.encode()).hexdigest()}
    (work / "report.json").write_text(json.dumps(report, indent=2))
    files = {f.name: audit.sha256_file(f) for f in work.iterdir() if f.suffix in (".step", ".stl", ".py", ".json", ".iges", ".brep", ".3mf", ".obj", ".glb")}
    audit.append(audit_path, {**base, "status": "ok" if ok else "failed", "generator": "assembly:template", "plan": plan,
                              "code_sha256": report["code_sha256"], "files": files})
    return Result("ok" if ok else "failed", run_id, summ, [], report, str(work))
