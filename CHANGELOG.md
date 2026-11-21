# Changelog
## 0.7.0
- Renamed the project from DefCAD to ShieldCAD (package `shieldcad`, env vars `SHIELDCAD_*`, commands `shieldcad`, `shieldcad-admin`, `shieldcad-server`). Behaviour unchanged.
## 0.6.0
- UI redesign: drafting-sheet viewport with live title block (part, revision, mass, status, run), numbered stepper (describe, confirm), results in tabs (checks, downloads, edit parameters, history), readable spec list instead of raw JSON, grouped checks/downloads/parameters, light and dark themes, offline system fonts, keyboard focus and reduced-motion support. No API changes.
## 0.5.0
- Assemblies: one component per prompt line, placement phrases, verified placement, fused single solid, per-component files, assembly STEP/GLB with named coloured bodies, interference reporting, revisions that re-place dependent parts.
- Export formats: STEP, IGES, BREP, STL, 3MF, OBJ, GLB (round-trip tested with independent importers).
- UI: mode switch, assembly preview with coloured parts, format-aware download panel.
## 0.4.0
- Parameter editing with feasibility re-check, linked revisions and audit lineage (API + UI parameter panel).
- Parser refactor: shared `finish()` feasibility checks; plate hole layouts stored symbolically.
- setup.sh, requirements files, .env.example; 48 tests.
## 0.3.0
- Sandbox: memory/file/CPU limits, timeout, own session, optional network namespace; protections recorded in every report.
- Auth: brute-force lockout, per-user generation rate limit, key expiry and rotation.
- Parts: spacer/standoff, plate corner radius (with conflict checks); benchmark grown to 15 prompts incl. casing/unicode variants.
- LLM path: repair loop tested against a mock OpenAI-compatible server.
- deploy/Caddyfile (TLS), compose tls profile.
## 0.2.0
- REST API, web UI with 3D viewer, roles, audit verification, Docker files, business documents.
## 0.1.0
- Engine: parser, templates, sandbox, validator, hash-chained audit, CLI.
