import json, math
import pytest
import cadquery as cq
from fastapi.testclient import TestClient
from shieldcad import audit
from shieldcad.assembly import plan_assembly, revise_plan, split_placement
from shieldcad.pipeline import run_assembly

PI = math.pi
STACK = ("Steel plate 200x120x10 mm with four M8 holes 20 mm from edge\n"
         "Steel flange OD 80, bore 30, 12 mm thick, four M6 bolt holes on a 60 mm bolt circle, on top of part 1\n"
         "Steel spacer OD 50, ID 20, 40 mm long, on top of part 2")


def test_placement_phrases_are_split_out():
    t, pl, e = split_placement("Steel shaft 10 mm diameter, 50 mm long, beside part 2, gap 3 mm, x=5 z=-2, rotate 90 about y")
    assert pl == {"rel": "right", "ref": 2, "gap": 3.0, "offset": {"x": 5.0, "z": -2.0}, "rot": ["y", 90]} and not e
    assert "part 2" not in t and "gap" not in t and "rotate" not in t


def test_plan_computes_stacking_positions():
    p = plan_assembly(STACK)
    assert not p["errors"]
    c = p["components"]
    assert c[1]["bbox_min"][2] == 10 and c[1]["bbox_max"][2] == 22      # flange sits on plate
    assert c[2]["bbox_min"][2] == 22 and c[2]["bbox_max"][2] == 62      # spacer on flange
    assert c[1]["transform"]["t"][:2] == [0.0, 0.0]                     # centred


def test_plan_errors_are_reported_per_component():
    assert "Component 1" in plan_assembly("Steel plate 100x50x5 mm, on top of part 2")["errors"][0]
    assert any("earlier" in e for e in plan_assembly("Steel plate 100x50x5\nSteel shaft 10 mm diameter, 20 mm long, on top of part 5")["errors"])
    assert any("Component 2" in e for e in plan_assembly("Steel plate 100x50x5\nmake me a bracket")["errors"])
    assert plan_assembly("Steel plate 100x50x5\nturbine blade 200 mm")["errors"]
    assert plan_assembly("")["errors"]
    assert any("90" in e for e in plan_assembly("Steel plate 100x50x5\nSteel shaft 10 mm diameter, 20 mm long, rotate 45 about x")["errors"])


def test_stack_generates_one_solid_with_all_formats(tmp_path):
    r = run_assembly(STACK, str(tmp_path))
    assert r.status == "ok", [c for c in r.report["validation"]["checks"] if not c["pass"]]
    m, d = r.report["metrics"], tmp_path / r.run_id
    assert m["n_solids"] == 1 and abs(m["bbox_max"][2] - 62) < .05
    vol = 200*120*10 - 4*PI*4.5**2*10 + PI*(80**2 - 30**2)/4*12 - 4*PI*3.3**2*12 + PI*(50**2 - 20**2)/4*40
    assert abs(m["volume"] - vol) / vol < .005
    for f in ["part.step", "part.iges", "part.brep", "part.stl", "part.3mf", "part.obj", "part.glb", "assembly.step", "assembly.glb",
              "component_1.step", "component_3.stl", "part.py", "report.json"]:
        assert (d / f).stat().st_size > 0, f
    assert r.report["est_mass_kg"] > 0 and audit.verify(tmp_path / "audit.jsonl") == (True, None)


def test_exported_files_reopen_in_other_software(tmp_path):
    """Round-trip: files written by ShieldCAD are re-read with independent importers."""
    r = run_assembly(STACK, str(tmp_path)); d = tmp_path / r.run_id; vol = r.report["metrics"]["volume"]
    assert abs(cq.importers.importStep(str(d / "part.step")).val().Volume() - vol) / vol < 1e-4
    assert abs(cq.Shape.importBrep(str(d / "part.brep")).Volume() - vol) / vol < 1e-4
    from OCP.IGESControl import IGESControl_Reader
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    rd = IGESControl_Reader(); assert rd.ReadFile(str(d / "part.iges")) == 1; rd.TransferRoots()
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(rd.OneShape(), g); assert abs(g.Mass() - vol) / vol < 1e-3
    a = cq.Assembly.importStep(str(d / "assembly.step"))
    assert sorted(c.name for c in a.children) == ["part_1_plate", "part_2_flange", "part_3_spacer"]
    assert (d / "part.stl").read_bytes()[:5] != b"" and (d / "part.obj").read_text().count("\nf ") > 100
    assert (d / "part.glb").read_bytes()[:4] == b"glTF"


def test_overlap_is_detected_and_merged(tmp_path):
    r = run_assembly("Steel plate 100x100x10\nSteel plate 100x100x10, x=50", str(tmp_path))
    assert r.status == "ok" and r.report["assembly"]["interference"][0][2] == pytest.approx(50 * 100 * 10, rel=.01)
    assert abs(r.report["metrics"]["volume"] - 150 * 100 * 10) / 1.5e6 < .005          # union, not double counted


def test_disconnected_parts_fail_fuse_but_still_export(tmp_path):
    r = run_assembly("Steel plate 100x100x10\nSteel plate 50x50x5, x=300", str(tmp_path))
    assert r.status == "failed" and any(c["check"] == "fused: one connected body" and not c["pass"] for c in r.report["validation"]["checks"])
    assert (tmp_path / r.run_id / "assembly.step").exists()
    r2 = run_assembly("Steel plate 100x100x10\nSteel plate 50x50x5, x=300", str(tmp_path), fuse=False)
    assert r2.status == "ok"                                                           # separate bodies allowed


def test_rotation_and_side_placement_match_measurement(tmp_path):
    r = run_assembly("Steel plate 100x60x10\nAluminium shaft 10 mm diameter, 80 mm long, rotate 90 about y, beside part 1", str(tmp_path))
    assert r.status == "ok", [c for c in r.report["validation"]["checks"] if not c["pass"]]
    c2 = r.report["assembly"]["plan"]["components"][1]
    assert c2["bbox_min"][0] == pytest.approx(50, abs=.01) and c2["bbox_max"][0] == pytest.approx(130, abs=.01)


def test_revision_moves_dependent_parts(tmp_path):
    plan = plan_assembly(STACK)
    new, errs = revise_plan(plan, {"1.thickness": 16})
    assert not errs and new["components"][1]["bbox_min"][2] == 16 and plan["components"][1]["bbox_min"][2] == 10
    assert revise_plan(plan, {"2.bore": 500})[1] and revise_plan(plan, {"9.thickness": 1})[1] and revise_plan(plan, {"thickness": 1})[1]
    r = run_assembly(STACK, str(tmp_path), plan=new, parent="x", revision=2, changes={"1.thickness": 16})
    assert r.status == "ok" and abs(r.report["metrics"]["bbox_max"][2] - 68) < .05


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIELDCAD_DATA_DIR", str(tmp_path))
    from shieldcad import admin
    from shieldcad.server import app, reset_limits
    reset_limits()
    keys = {n: admin.add_user(n, r) for n, r in [("ann", "engineer"), ("bob", "engineer"), ("vic", "viewer")]}
    return TestClient(app), {n: {"X-API-Key": k} for n, k in keys.items()}


def test_assembly_api_flow(env):
    c, h = env
    p = c.post("/api/assembly/parse", json={"prompt": STACK}, headers=h["ann"]).json()
    assert not p["errors"] and len(p["summary"]) == 3
    assert c.post("/api/assembly/generate", json={"prompt": STACK}, headers=h["ann"]).status_code == 400
    assert c.post("/api/assembly/parse", json={"prompt": STACK}, headers=h["vic"]).status_code == 403
    d = c.post("/api/assembly/generate", json={"prompt": STACK, "confirmed": True}, headers=h["ann"]).json()
    assert d["status"] == "ok" and "1.thickness" in d["report"]["editable"]
    rid = d["run_id"]
    for f in ["part.step", "assembly.step", "component_2.stl", "part.iges"]:
        assert c.get(f"/api/runs/{rid}/files/{f}", headers=h["ann"]).status_code == 200, f
    assert c.get(f"/api/runs/{rid}/files/component_2.exe", headers=h["ann"]).status_code == 404
    assert c.get(f"/api/runs/{rid}/files/part.step", headers=h["bob"]).status_code == 404
    rv = c.post(f"/api/runs/{rid}/revise", json={"changes": {"2.thickness": 20}}, headers=h["ann"]).json()
    assert rv["status"] == "ok" and rv["report"]["revision"] == 2 and abs(rv["report"]["metrics"]["bbox_max"][2] - 70) < .05
    bad = c.post(f"/api/runs/{rid}/revise", json={"changes": {"2.bore": 500}}, headers=h["ann"]).json()
    assert bad["status"] == "needs_input"
    kinds = {r["kind"] for r in c.get("/api/runs", headers=h["ann"]).json()}
    assert kinds == {"assembly"}
