# ShieldCAD

On-premise assistant that turns an engineer's text prompt into an editable, **validated** parametric CAD part (STEP + STL + source script) with a tamper-evident audit trail. Built for defence suppliers who cannot send design data to public AI services.

> DRAFT tool. All output requires review and approval by a qualified engineer.

## What is in the box
| Path | What |
|---|---|
| `shieldcad/` | Engine: parser, templates, sandbox, validator, audit log, pipeline, CLI, REST server, admin tool |
| `static/` | Web UI (login, spec confirmation, 3D viewer, history, audit verify). Three.js is vendored: works offline |
| `tests/` | 58 tests: 15-prompt benchmark with independent ground truth (incl. casing/unicode variants), sandbox containment, LLM repair loop (mock server), API auth/roles/isolation/rate limits, audit tamper detection |
| `docs/` | Architecture and security model |
| `Dockerfile`, `docker-compose.yml` | Hardened container deployment (not yet built or tested: see docs/SECURITY.md) |

## Quick start
    ./setup.sh --test                                  # venv + deps + first admin key + tests
    # or manually:
    pip install -r requirements-dev.txt
    python -m shieldcad.admin add-user alice admin --days 90   # prints an API key once (expires in 90 days)
    python -m shieldcad.admin rotate-key alice
    python -m shieldcad.server                            # http://127.0.0.1:8000
    python -m pytest -q

CLI without the server: `python -m shieldcad.cli "Steel shaft 25 mm diameter, 300 mm long"`

## Flow
prompt -> **interpret** -> engineer confirms the spec -> template code -> static check -> sandboxed run -> measured validation (bbox, volume, hole count/size, solid validity) -> STEP/STL/script/report -> hash-chained audit record.
The API refuses to generate unless `confirmed: true`; the UI forces re-confirmation after any prompt edit.

## Assemblies: several components -> one model
Switch the UI to **Assembly**, write one component per line, and add placement phrases:

    Steel plate 200x120x10 mm with four M8 holes 20 mm from edge
    Steel flange OD 80, bore 30, 12 mm thick, four M6 bolt holes on a 60 mm bolt circle, on top of part 1
    Steel spacer OD 50, ID 20, 40 mm long, on top of part 2

Placement: `on top of / below / beside (+x) / left of / in front of / behind part N`, `gap 2 mm`, `x=10 y=0 z=5` (absolute origin, or extra shift when relative), `rotate 90 about x` (multiples of 90). ShieldCAD places parts, fuses them into **one solid**, and verifies every component's position/volume/holes, the fused bounding box, volume conservation (sum of parts minus overlaps) and that the result is one connected body. Parts that only touch along a line, or not at all, are reported as not connected (tick off "Fuse" to allow separate bodies). Editing a component (`2.thickness`) re-places everything that depends on it.

## Download formats (all verified by re-opening with independent importers in the tests)
| File | Use |
|---|---|
| `part.step` | Fused single solid. Opens in SolidWorks, Fusion, Inventor, CATIA, NX, FreeCAD, Onshape; geometry is editable with direct-modelling tools |
| `part.iges`, `part.brep` | Older CAD exchange / OpenCascade, FreeCAD |
| `part.stl`, `part.3mf` | 3D printing, slicers |
| `part.obj`, `part.glb` | Blender, web viewers, AR |
| `assembly.step`, `assembly.glb` | Separate named, coloured bodies (assembly structure kept) |
| `component_N.step/.stl` | Each placed component on its own |
| `part.py` | CadQuery source: the **fully parametric** model |
| `report.json` | Spec, measurements, checks, hashes |

Important: neutral formats (STEP/IGES) carry geometry, not the parametric feature history. In another CAD program you can modify the solid (cut, add, move faces) but cannot change "thickness = 8" as a parameter. For true parametric edits use ShieldCAD's revision panel or `part.py`.

## Editing parameters
After generating, change any numeric parameter in the UI ("make the flange 2 mm thicker") and regenerate. The edit is re-checked for feasibility (e.g. bolt circle must still fit), produces a **new revision** linked to its parent, and is written to the audit chain with the exact changes. API: `POST /api/runs/{id}/revise {"changes": {"thickness": 14}}`.

## API summary
`GET /api/health` · `GET /api/me` · `POST /api/parse` · `POST /api/generate` · `POST /api/runs/{id}/revise` · `GET /api/runs` · `GET /api/runs/{id}` · `GET /api/runs/{id}/files/{part.step|part.stl|part.py|report.json}` · `GET /api/audit/verify` (admin)

## Roles
`viewer` (read own runs) < `engineer` (parse/generate) < `admin` (all runs, audit verification). Keys are stored only as SHA-256 hashes.

## Supported parts (v1)
Plate (corner / rectangular-pattern / in-line holes, optional corner radius), L-bracket, flange with bolt circle, spacer/standoff (tube), shaft, open-top enclosure. M3-M20 map to ISO 273 medium-fit clearance holes.

## Known limits (honest list)
- Rule-based English/mm parser; LLM extraction is the next step. Parts with no template use `shieldcad/llm.py` (local OpenAI-compatible server): its repair loop is tested against a mock server, **not yet against a real model**.
- Sandbox has real layers (limits, timeout, network namespace) but is not a full security boundary; see docs/SECURITY.md.
- Validator does not check tolerances, GD&T, threads or manufacturability. No drawings yet.
- TLS proxy config and Docker files are untested; no SSO/MFA or database yet (file-based storage). Planned for the secure-pilot phase.
