# Architecture

```
Browser UI -> FastAPI (auth, roles, CSP) -> pipeline
pipeline: parser -> spec (confirmed) -> template code -> AST screen -> sandbox subprocess (CadQuery/OpenCascade)
          -> validator (measured vs spec) -> files + report.json -> hash-chained audit.jsonl
Optional: local LLM (OpenAI-compatible, e.g. vLLM) for parts with no template, with a repair loop (max 3).
```
Design decisions
- **Code, not meshes.** The system produces parametric CadQuery source, so dimensions are computed exactly and every part is editable and reproducible.
- **Two-stage generation.** Interpretation is shown and confirmed before geometry exists; misunderstandings die cheaply.
- **Measure, don't trust.** The validator reads the generated solid (tight bounding box, volume, cylindrical faces) and compares to the spec. Test ground truth is hand-computed, independent of the templates.
- **Traceability.** Each record stores prompt, user, spec, code hash and output file hashes, chained by SHA-256. Editing any past record breaks verification.
- **Offline by default.** No CDN dependencies in the UI; no telemetry.

Revisions: `shieldcad/revise.py` changes numeric spec parameters, `parser.finish()` re-derives geometry-dependent fields (e.g. plate hole positions) and re-checks feasibility, then `pipeline.run_spec()` generates a new run linked by `parent_run_id` with the exact `changes` recorded in `report.json` and the audit chain.

Storage layout: `data/users.json`, `data/runs/<run_id>/{part.step,part.stl,part.py,report.json}`, `data/runs/audit.jsonl`.

Extension points: add a template in `shieldcad/templates.py` plus parser rules; add benchmark cases in `tests/test_pipeline.py` (ground truth first).
