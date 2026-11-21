import argparse, json, sys
from . import audit
from .llm import LLM
from .pipeline import run


def _confirm(spec):
    print("\nInterpreted spec:\n" + json.dumps({k: spec[k] for k in ("type", "material", "params", "notes")}, indent=2))
    return input("\nProceed? [y/N] ").strip().lower() == "y"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="shieldcad", description="Prompt -> parametric CAD (DRAFT, needs engineering review)")
    ap.add_argument("prompt", nargs="?")
    ap.add_argument("--out", default="out")
    ap.add_argument("--user", default="local")
    ap.add_argument("--yes", action="store_true", help="skip spec confirmation")
    ap.add_argument("--verify-audit", action="store_true")
    a = ap.parse_args(argv)
    if a.verify_audit:
        ok, bad = audit.verify(f"{a.out}/audit.jsonl")
        print("audit chain OK" if ok else f"AUDIT TAMPERED at line {bad}")
        return 0 if ok else 2
    if not a.prompt:
        ap.error("prompt required")
    r = run(a.prompt, a.out, a.user, None if a.yes else _confirm, LLM.from_env())
    if r.status == "needs_input":
        print("Need more information:\n - " + "\n - ".join(r.errors)); return 1
    if r.status == "rejected":
        print("Cancelled."); return 1
    for c in (r.report.get("validation") or {}).get("checks", []):
        print(("PASS " if c["pass"] else "FAIL ") + c["check"] + ": " + c["detail"])
    if r.report.get("error"): print("ERROR:", r.report["error"])
    print(f"\n{r.status.upper()} -> {r.out_dir}  (est. mass {r.report.get('est_mass_kg')} kg)\n{r.report['disclaimer']}")
    return 0 if r.status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
