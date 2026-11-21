import subprocess, sys
import pytest
from shieldcad import sandbox
from fastapi.testclient import TestClient


def test_infinite_loop_is_killed(tmp_path):
    ok, msg = sandbox.execute("import cadquery as cq\nwhile True:\n    pass\nresult = None", tmp_path, timeout=4)
    assert not ok and "timeout" in msg


def test_memory_bomb_is_contained(tmp_path, monkeypatch):
    ok, msg = sandbox.execute("import cadquery as cq\nx = [0] * (10 ** 10)\nresult = None", tmp_path, timeout=60)
    assert not ok and "MemoryError" in msg


def test_runner_blocks_imports_even_without_static_check(tmp_path):
    ok, msg = sandbox.execute("import cadquery as cq\nimport socket\nresult = None", tmp_path)
    assert not ok and "blocked import" in msg


@pytest.mark.skipif(not sandbox.network_isolation_available(), reason="host does not allow network namespaces")
def test_network_namespace_has_no_interfaces_but_loopback():
    out = subprocess.run(["unshare", "--net", sys.executable, "-c", "import socket;print([n for _,n in socket.if_nameindex()])"],
                         capture_output=True, text=True).stdout
    assert out.strip() == "['lo']"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIELDCAD_DATA_DIR", str(tmp_path))
    from shieldcad import admin, server
    server.reset_limits()
    return TestClient(server.app), admin, server


def test_lockout_after_repeated_bad_keys(env, monkeypatch):
    c, admin, server = env
    monkeypatch.setenv("SHIELDCAD_MAX_FAILS", "3")
    good = admin.add_user("ann", "engineer")
    for _ in range(3):
        assert c.get("/api/me", headers={"X-API-Key": "bad"}).status_code == 401
    assert c.get("/api/me", headers={"X-API-Key": good}).status_code == 429   # locked even for a valid key


def test_generation_rate_limit(env, monkeypatch):
    c, admin, server = env
    monkeypatch.setenv("SHIELDCAD_RATE_GEN_PER_MIN", "1")
    h = {"X-API-Key": admin.add_user("ann", "engineer")}
    b = {"prompt": "Steel shaft 10 mm diameter, 20 mm long", "confirmed": True}
    assert c.post("/api/generate", json=b, headers=h).status_code == 200
    assert c.post("/api/generate", json=b, headers=h).status_code == 429


def test_expired_key_rejected_and_rotation(env):
    c, admin, server = env
    import json
    key = admin.add_user("ann", "engineer", days=30)
    assert c.get("/api/me", headers={"X-API-Key": key}).status_code == 200
    u = admin.load_users(); u["ann"]["expires"] = "2020-01-01"; admin._save(u)
    assert c.get("/api/me", headers={"X-API-Key": key}).status_code == 401
    new = admin.rotate_key("ann")
    assert c.get("/api/me", headers={"X-API-Key": key}).status_code == 401
    assert c.get("/api/me", headers={"X-API-Key": new}).status_code == 200


def test_report_records_sandbox_protections(env):
    c, admin, server = env
    h = {"X-API-Key": admin.add_user("ann", "engineer")}
    d = c.post("/api/generate", json={"prompt": "Steel shaft 10 mm diameter, 20 mm long", "confirmed": True}, headers=h).json()
    assert d["report"]["sandbox"]["mem_limit_mb"] == 4096 and "network_isolated" in d["report"]["sandbox"]
