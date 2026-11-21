import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIELDCAD_DATA_DIR", str(tmp_path))
    from shieldcad import admin
    from shieldcad.server import app, reset_limits
    reset_limits()
    keys = {n: admin.add_user(n, r) for n, r in [("ann", "engineer"), ("bob", "engineer"), ("vic", "viewer"), ("root", "admin")]}
    return TestClient(app), {n: {"X-API-Key": k} for n, k in keys.items()}


P = "Steel shaft 20 mm diameter, 100 mm long"


def test_health_and_static_ui(env):
    c, _ = env
    assert c.get("/api/health").json() == {"ok": True}
    r = c.get("/")
    assert r.status_code == 200 and "ShieldCAD" in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_auth_required_and_roles(env):
    c, h = env
    assert c.get("/api/me").status_code == 401
    assert c.get("/api/me", headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.post("/api/parse", json={"prompt": P}, headers=h["vic"]).status_code == 403
    assert c.get("/api/audit/verify", headers=h["ann"]).status_code == 403


def test_spec_must_be_confirmed(env):
    c, h = env
    assert c.post("/api/generate", json={"prompt": P}, headers=h["ann"]).status_code == 400


def test_generate_download_and_isolation(env):
    c, h = env
    d = c.post("/api/generate", json={"prompt": P, "confirmed": True}, headers=h["ann"]).json()
    assert d["status"] == "ok" and d["report"]["user"] == "ann"
    rid = d["run_id"]
    assert c.get(f"/api/runs/{rid}/files/part.step", headers=h["ann"]).status_code == 200
    assert c.get(f"/api/runs/{rid}/files/part.stl", headers=h["ann"]).content[:5] != b""
    assert c.get(f"/api/runs/{rid}", headers=h["bob"]).status_code == 404       # other engineer
    assert c.get(f"/api/runs/{rid}", headers=h["root"]).status_code == 200      # admin sees all
    assert [r["run_id"] for r in c.get("/api/runs", headers=h["bob"]).json()] == []
    assert len(c.get("/api/runs", headers=h["ann"]).json()) == 1


def test_path_traversal_and_bad_names(env):
    c, h = env
    d = c.post("/api/generate", json={"prompt": P, "confirmed": True}, headers=h["ann"]).json()
    rid = d["run_id"]
    assert c.get(f"/api/runs/{rid}/files/..%2Faudit.jsonl", headers=h["ann"]).status_code == 404
    assert c.get(f"/api/runs/{rid}/files/secret.txt", headers=h["ann"]).status_code == 404
    assert c.get("/api/runs/..%2F..%2Fetc/files/part.step", headers=h["ann"]).status_code == 404


def test_needs_input_and_prompt_limits(env):
    c, h = env
    d = c.post("/api/generate", json={"prompt": "make me a bracket", "confirmed": True}, headers=h["ann"]).json()
    assert d["status"] == "needs_input" and d["errors"]
    assert c.post("/api/parse", json={"prompt": "x" * 5000}, headers=h["ann"]).status_code == 422


def test_audit_verify_endpoint_detects_tampering(env, tmp_path):
    c, h = env
    c.post("/api/generate", json={"prompt": P, "confirmed": True}, headers=h["ann"])
    assert c.get("/api/audit/verify", headers=h["root"]).json()["ok"] is True
    log = tmp_path / "runs" / "audit.jsonl"
    log.write_text(log.read_text().replace('"ann"', '"eve"'))
    assert c.get("/api/audit/verify", headers=h["root"]).json()["ok"] is False
