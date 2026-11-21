"""LLM path tested against a MOCK OpenAI-compatible server (not a real model): repair loop, feedback, safety."""
import json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import pytest
from shieldcad.llm import LLM
from shieldcad.pipeline import run

GOOD = 'import cadquery as cq\nresult = cq.Workplane("XY").box(200, 50, 10)'
WRONG = 'import cadquery as cq\nresult = cq.Workplane("XY").box(100, 50, 10)'
EVIL = 'import os\nresult = None'
PROMPT = "Machined blade blank 200x50x10 mm"


def serve(replies):
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(body["messages"])
            code = replies[min(len(seen) - 1, len(replies) - 1)]
            out = json.dumps({"choices": [{"message": {"content": "```python\n" + code + "\n```"}}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen, LLM(f"http://127.0.0.1:{srv.server_port}", "mock")


def test_repair_loop_fixes_wrong_geometry(tmp_path):
    srv, seen, llm = serve([WRONG, GOOD])
    r = run(PROMPT, str(tmp_path), llm=llm)
    srv.shutdown()
    assert r.status == "ok" and [a["ok"] for a in r.report["attempts"]] == [False, True]
    assert "failed validation" in seen[1][-1]["content"] and "bounding_box" in seen[1][-1]["content"]
    assert r.report["generator"] == "llm"


def test_malicious_llm_code_is_blocked_then_repaired(tmp_path):
    srv, seen, llm = serve([EVIL, GOOD])
    r = run(PROMPT, str(tmp_path), llm=llm)
    srv.shutdown()
    assert r.status == "ok"
    assert "static check rejected" in seen[1][-1]["content"]


def test_gives_up_after_max_repairs(tmp_path):
    srv, seen, llm = serve([WRONG])
    r = run(PROMPT, str(tmp_path), llm=llm, max_repairs=2)
    srv.shutdown()
    assert r.status == "failed" and len(r.report["attempts"]) == 3
