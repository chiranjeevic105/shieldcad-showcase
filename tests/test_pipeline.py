"""Benchmark with INDEPENDENT ground truth (hand-computed here, not taken from templates)."""
import math
import pytest
from shieldcad import audit, sandbox
from shieldcad.pipeline import run

pi = math.pi
A = lambda d, n, t: n * pi * (d / 2) ** 2 * t
CASES = [  # prompt, sorted bbox, hole dia, hole count, volume
    ("Aluminium bracket, 120x60x8 mm, four M6 holes on a 100x40 pattern", [8, 60, 120], 6.6, 4, 120*60*8 - A(6.6, 4, 8)),
    ("Steel plate 200 x 100 x 10 mm with four 9 mm holes 15 mm from edge", [10, 100, 200], 9, 4, 200*100*10 - A(9, 4, 10)),
    ("Plate 300x200x12 mm with six 6 mm holes", [12, 200, 300], 6, 6, 300*200*12 - A(6, 6, 12)),
    ("Steel plate 300x200x12 mm", [12, 200, 300], None, 0, 300*200*12),
    ("Steel flange, outer diameter 150 mm, bore 50 mm, 12 mm thick, six M10 bolt holes on a 110 mm bolt circle",
     [12, 150, 150], 11, 6, pi*(150**2 - 50**2)/4*12 - A(11, 6, 12)),
    ("Stainless flange OD 200, bore 80 mm, 16 mm thick, eight M12 bolts on a 160 mm PCD",
     [16, 200, 200], 13.5, 8, pi*(200**2 - 80**2)/4*16 - A(13.5, 8, 16)),
    ("Steel shaft 25 mm diameter, 300 mm long", [25, 25, 300], None, 0, pi*25**2/4*300),
    ("Aluminium enclosure 160x100x60 mm with 3 mm walls", [60, 100, 160], None, 0, 160*100*60 - 154*94*57),
    ("Aluminium housing 100x80x40 mm", [40, 80, 100], None, 0, 100*80*40 - 94*74*37),  # default 3 mm wall
    ("L-bracket 80 x 60 mm legs, 40 mm wide, 5 mm thick, two M5 holes per leg, aluminium",
     [40, 60, 80], 5.5, 4, 80*40*5 + 5*40*55 - A(5.5, 4, 5)),
    ("Steel spacer OD 20, ID 8 mm, 15 mm long", [15, 20, 20], 8, 1, pi*(20**2 - 8**2)/4*15),
    ("Aluminium standoff outer diameter 12 mm, bore 5 mm, length 30 mm", [12, 12, 30], 5, 1, pi*(12**2 - 5**2)/4*30),
    ("Aluminium plate 100x60x6 mm with 8 mm corner radius and four 5 mm holes 12 mm from edge",
     [6, 60, 100], 5, 4, 100*60*6 - (4 - pi)*8**2*6 - A(5, 4, 6)),
    # robustness: casing, unicode, missing units
    ("STEEL PLATE 200X100X10 MM WITH FOUR Ø9 HOLES 15 MM FROM EDGE", [10, 100, 200], 9, 4, 200*100*10 - A(9, 4, 10)),
    ("steel plate 200 × 100 × 10, four 9 mm holes 15 mm from edge", [10, 100, 200], 9, 4, 200*100*10 - A(9, 4, 10)),
]


@pytest.mark.parametrize("prompt,bbox,d,n,vol", CASES)
def test_benchmark(prompt, bbox, d, n, vol, tmp_path):
    r = run(prompt, str(tmp_path))
    assert r.status == "ok", (r.errors, r.report.get("error"), r.report.get("validation"))
    m = r.report["metrics"]
    assert all(abs(a - b) < 0.05 for a, b in zip(m["bbox"], bbox))
    assert abs(m["volume"] - vol) / vol < 0.005
    if d:
        assert sum(abs(x - d / 2) < 0.01 for x in m["cyl_radii"]) == n
    assert (tmp_path / r.run_id / "part.step").stat().st_size > 0


def test_missing_info_asks_instead_of_guessing(tmp_path):
    for p in ["make me a bracket", "plate 100x50x5 with holes", "flange 100 mm"]:
        assert run(p, str(tmp_path)).status == "needs_input"


def test_impossible_geometry_rejected(tmp_path):
    assert run("plate 40x20x5 mm with four M10 holes on a 38x18 pattern", str(tmp_path)).status == "needs_input"


def test_unsupported_part_without_llm(tmp_path):
    assert run("turbine blade 200 mm", str(tmp_path)).status == "needs_input"


@pytest.mark.parametrize("code", ["import os", "import socket", "open('/etc/passwd')", "__import__('os')",
                                  "import cadquery as cq\nx = cq.__dict__"])
def test_sandbox_blocks_dangerous_code(code):
    assert sandbox.static_check(code)


def test_audit_chain_detects_tampering(tmp_path):
    run("Steel shaft 10 mm diameter, 50 mm long", str(tmp_path))
    run("Steel shaft 12 mm diameter, 60 mm long", str(tmp_path))
    p = tmp_path / "audit.jsonl"
    assert audit.verify(p) == (True, None)
    p.write_text(p.read_text().replace("10 mm", "99 mm"))
    assert audit.verify(p)[0] is False


def test_rounded_corner_conflicts_are_refused(tmp_path):
    assert run("plate 100x60x6 mm with 5 mm fillets and four 10 mm holes 6 mm from edge", str(tmp_path)).status == "needs_input"   # hole radius == fillet radius
    assert run("plate 100x60x6 mm with 40 mm corner radius", str(tmp_path)).status == "needs_input"
    assert run("plate 100x60x6 mm with 12 mm corner radius and four 8 mm holes 5 mm from edge", str(tmp_path)).status == "needs_input"  # hole hits the arc
