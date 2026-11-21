import math
import pytest
from fastapi.testclient import TestClient
from shieldcad import audit
from shieldcad.parser import parse
from shieldcad.pipeline import run, run_spec
from shieldcad.revise import editable, revise

FL = "Steel flange, outer diameter 150 mm, bore 50 mm, 12 mm thick, six M10 bolt holes on a 110 mm bolt circle"
PL = "Aluminium plate 200 x 100 x 10 mm with four 9 mm holes 15 mm from edge"


def test_editable_lists_numeric_params_only():
    ed = editable(parse(PL)[0])
    assert ed["length"] == 200 and ed["layout.edge"] == 15 and "points" not in ed and "layout" not in ed


def test_revise_validates_without_mutating():
    spec, _ = parse(FL)
    new, errs = revise(spec, {"thickness": 14})
    assert not errs and new["params"]["thickness"] == 14 and spec["params"]["thickness"] == 12
    assert revise(spec, {"bore": 200})[1]                      # bore >= OD
    assert revise(spec, {"nonsense": 5})[1]                    # unknown key
    assert revise(spec, {"thickness": -3})[1]                  # non-positive
    assert revise(spec, {"bolt_circle": 40})[1]                # bolt circle collides with bore
    assert revise(parse("turbine blade 200 mm")[0], {"x": 1})[1]


def test_plate_points_follow_dimension_changes():
    spec, _ = parse(PL)
    new, errs = revise(spec, {"length": 300, "layout.edge": 20})
    assert not errs and (130.0, 30.0) in [tuple(p) for p in new["params"]["points"]]


def test_revision_regenerates_and_chains_audit(tmp_path):
    r1 = run(FL, str(tmp_path))
    new, errs = revise(r1.spec, {"thickness": 14})
    r2 = run_spec(new, [], FL, str(tmp_path), "local", parent=r1.run_id, revision=2, changes={"thickness": 14})
    assert r2.status == "ok" and r2.report["revision"] == 2 and r2.report["parent_run_id"] == r1.run_id
    m = r2.report["metrics"]
    assert abs(m["bbox"][0] - 14) < .05
    exp = math.pi * (150**2 - 50**2) / 4 * 14 - 6 * math.pi * 5.5**2 * 14
    assert abs(m["volume"] - exp) / exp < .005
    assert audit.verify(tmp_path / "audit.jsonl") == (True, None)
    lines = (tmp_path / "audit.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2 and r1.run_id in lines[1] and '"changes"' in lines[1]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIELDCAD_DATA_DIR", str(tmp_path))
    from shieldcad import admin
    from shieldcad.server import app, reset_limits
    reset_limits()
    keys = {n: admin.add_user(n, r) for n, r in [("ann", "engineer"), ("bob", "engineer"), ("vic", "viewer")]}
    return TestClient(app), {n: {"X-API-Key": k} for n, k in keys.items()}, tmp_path


def test_revise_api_flow_and_permissions(env):
    c, h, tmp = env
    d = c.post("/api/generate", json={"prompt": FL, "confirmed": True}, headers=h["ann"]).json()
    rid = d["run_id"]
    assert d["report"]["editable"]["thickness"] == 12
    r = c.post(f"/api/runs/{rid}/revise", json={"changes": {"thickness": 16}}, headers=h["ann"]).json()
    assert r["status"] == "ok" and r["report"]["revision"] == 2 and r["report"]["parent_run_id"] == rid
    bad = c.post(f"/api/runs/{rid}/revise", json={"changes": {"bore": 999}}, headers=h["ann"]).json()
    assert bad["status"] == "needs_input" and bad["errors"]
    assert c.post(f"/api/runs/{rid}/revise", json={"changes": {"thickness": 16}}, headers=h["bob"]).status_code == 404
    assert c.post(f"/api/runs/{rid}/revise", json={"changes": {"thickness": 16}}, headers=h["vic"]).status_code == 403
    assert c.post(f"/api/runs/{rid}/revise", json={"changes": {}}, headers=h["ann"]).status_code == 422
    runs = c.get("/api/runs", headers=h["ann"]).json()
    assert sorted(x["revision"] for x in runs) == [1, 2]
    assert len(list((tmp / "runs").glob("2*"))) == 2          # the failed revision created no run
