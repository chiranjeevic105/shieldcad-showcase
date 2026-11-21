"""Stage 1: prompt -> structured spec (deterministic). Missing info is reported, never guessed silently.
`finish(spec)` re-derives geometry-dependent fields and re-checks feasibility; it is shared with revisions."""
import re

NUM = r"(\d+(?:\.\d+)?)"
X = r"\s*[x×*]\s*"
TRIPLE = re.compile(NUM + r"\s*(?:mm)?" + X + NUM + r"\s*(?:mm)?" + X + NUM)
PAIR = re.compile(NUM + X + NUM + r"\s*(?:mm\s*)?(?:hole\s*|bolt\s*)?pattern")
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "twelve": 12}
# ISO 273 medium-fit clearance holes (mm)
CLEARANCE = {3: 3.4, 4: 4.5, 5: 5.5, 6: 6.6, 8: 9.0, 10: 11.0, 12: 13.5, 16: 17.5, 20: 22.0}
DENSITY = {"aluminium": 2.70, "aluminum": 2.70, "stainless": 8.0, "steel": 7.85,
           "titanium": 4.43, "brass": 8.5}  # g/cm3


def _f(pats, t):
    for p in pats:
        m = re.search(p, t)
        if m:
            return float(m.group(1))
    return None


def _count(t):
    m = re.search(r"\b(\d+|" + "|".join(WORDS) + r")\b(?!\s*mm)(?:\s+[\w-]+){0,2}?\s+(?:holes?|bolts?)\b", t)
    if not m:
        return None
    v = m.group(1)
    return int(v) if v.isdigit() else WORDS[v]


def _hole_dia(t):
    m = re.search(r"\bm(\d{1,2})\b", t)
    if m and int(m.group(1)) in CLEARANCE:
        return CLEARANCE[int(m.group(1))]
    return _f([r"[ø⌀]\s*" + NUM,
               NUM + r"\s*mm\s*(?:dia\w*\s*)?(?:bolt\s*|through\s*)?holes?",
               r"holes?\s*(?:of\s*)?(?:dia\w*\s*)?" + NUM], t)


def _kind(t):
    if "flange" in t: return "flange"
    if re.search(r"\b(spacer|standoff|bushing|sleeve|tube)\b", t): return "spacer"
    if re.search(r"\b(shaft|rod|pin)\b", t): return "shaft"
    if re.search(r"enclosure|housing|\bbox\b|\bcase\b", t): return "enclosure"
    if re.search(r"\bl[- ]?(shaped )?bracket|angle bracket", t): return "bracket_l"
    if re.search(r"plate|bracket|mount|panel", t): return "plate"
    return "custom"


def _need(errors, cond, msg):
    if not cond:
        errors.append(msg)
    return bool(cond)


# ---------------- feasibility checks (shared by parse and revise) ----------------
def _finish_plate(p):
    e, L, W, T = [], p["length"], p["width"], p["thickness"]
    d, lay, r = p.get("hole_dia"), p.get("layout"), p.get("corner_radius")
    if r:
        if r >= min(L, W) / 2:
            e.append("Corner radius too large for the plate."); r = None
        elif d and abs(r - d / 2) < 0.01:
            e.append("Corner radius equals the hole radius; change one so the geometry can be checked unambiguously."); r = None
    pts = []
    if lay:
        k = lay["kind"]
        if k == "pair":
            pts = [(sx * lay["px"] / 2, sy * lay["py"] / 2) for sx in (-1, 1) for sy in (-1, 1)]
        elif k == "corners":
            ex = lay["edge"]
            pts = [(sx * (L / 2 - ex), sy * (W / 2 - ex)) for sx in (-1, 1) for sy in (-1, 1)]
        else:
            n = int(lay["n"])
            pts = [(-L / 2 + L * (i + 1) / (n + 1), 0.0) for i in range(n)]
        if any(abs(x) + d / 2 + 1 > L / 2 or abs(y) + d / 2 + 1 > W / 2 for x, y in pts):
            e.append("Holes do not fit on the plate (need >= 1 mm edge margin).")
        if r:
            for x, y in pts:
                dx, dy = abs(x) - (L / 2 - r), abs(y) - (W / 2 - r)
                if dx > 0 and dy > 0 and (dx * dx + dy * dy) ** .5 + d / 2 + 1 > r:
                    e.append("Holes collide with the rounded corners."); break
    p["points"] = [(round(x, 4), round(y, 4)) for x, y in pts]
    return e


def finish(spec):
    """Return feasibility errors for spec['params'] (also derives plate hole points)."""
    k, p, e = spec["type"], spec["params"], []
    if k == "plate":
        e = _finish_plate(p)
    elif k == "bracket_l":
        A, B, W, T, n, d = p["leg_a"], p["leg_b"], p["width"], p["thickness"], p["holes_per_leg"], p.get("hole_dia")
        if T >= min(A, B):
            e.append("Thickness too large for the leg sizes.")
        elif n and d and ((A - T) / 2 < d / 2 + 1 or (B - T) / 2 < d / 2 + 1 or W / (n + 1) < d + 1):
            e.append("Holes do not fit on the legs.")
    elif k == "flange":
        od, bore, bc, d = p["od"], p["bore"], p["bolt_circle"], p["hole_dia"]
        if bore >= od:
            e.append("Bore must be smaller than the outer diameter.")
        elif not (bore / 2 < bc / 2 - d / 2 and bc / 2 + d / 2 < od / 2):
            e.append("Bolt circle does not fit between bore and outer diameter.")
    elif k == "spacer":
        if p["bore"] >= p["od"]:
            e.append("Bore must be smaller than the outer diameter.")
    elif k == "enclosure":
        if 2 * p["wall"] >= min(p["length"], p["width"], p["height"]):
            e.append("Wall thickness too large for the box.")
    return e


def parse(prompt):
    t = prompt.lower()
    errors, notes, p = [], [], {}
    kind = _kind(t)
    mat = next((m for m in DENSITY if m in t), None)
    d, n = _hole_dia(t), _count(t)
    holes_mentioned = bool(re.search(r"\bholes?\b", t))

    if kind == "plate":
        m = TRIPLE.search(t)
        if _need(errors, m, "Plate needs length x width x thickness, e.g. '120x60x8 mm'."):
            L, W, T = map(float, m.groups())
            p.update(length=L, width=W, thickness=T)
            rad = _f([NUM + r"\s*mm\s*(?:corner\s*radius|corner\s*fillets?|fillets?|rounded corners?)",
                      r"(?:corner\s*radius|corner\s*fillets?|fillets?|rounded corners?)\s*(?:of\s*)?" + NUM], t)
            if rad:
                p["corner_radius"] = rad
            pair = PAIR.search(t)
            if d or n or pair or holes_mentioned:
                if _need(errors, d, "Hole size missing (e.g. 'M6' or '6.5 mm holes')."):
                    p["hole_dia"] = d
                    if pair:
                        if n not in (None, 4):
                            errors.append(f"A rectangular pattern gives 4 holes but the prompt says {n}.")
                        p["layout"] = {"kind": "pair", "px": float(pair.group(1)), "py": float(pair.group(2))}
                    elif _need(errors, n, "Hole count missing."):
                        if n == 4:
                            e = _f([NUM + r"\s*mm\s*from\s*(?:the\s*)?edge"], t) or 2 * d
                            if e == 2 * d:
                                notes.append(f"Edge offset assumed {2*d:g} mm (2 x hole dia).")
                            p["layout"] = {"kind": "corners", "edge": e}
                        else:
                            p["layout"] = {"kind": "line", "n": n}
                            notes.append("Holes spaced evenly along the centreline of the length.")

    elif kind == "bracket_l":
        m = re.search(NUM + X + NUM, t)
        W = _f([NUM + r"\s*mm\s*wide", r"width\s*(?:of\s*)?" + NUM], t)
        T = _f([NUM + r"\s*mm\s*thick", r"thickness\s*(?:of\s*)?" + NUM], t)
        if _need(errors, m and W and T, "L-bracket needs leg sizes ('80 x 60'), width ('40 mm wide') and thickness ('5 mm thick')."):
            p.update(leg_a=float(m.group(1)), leg_b=float(m.group(2)), width=W, thickness=T, holes_per_leg=0)
            if d or n or holes_mentioned:
                if _need(errors, d and n, "Give both hole size and count."):
                    p.update(hole_dia=d, holes_per_leg=n)
                    notes.append("Hole count is applied per leg.")

    elif kind == "flange":
        od = _f([r"\b(?:od|outer diameter|outside diameter)\s*(?:of\s*)?" + NUM], t)
        bore = _f([r"\b(?:bore|inner diameter|id)\s*(?:of\s*|dia\w*\s*)?" + NUM], t)
        T = _f([NUM + r"\s*mm\s*thick", r"thickness\s*(?:of\s*)?" + NUM], t)
        bc = _f([NUM + r"\s*mm\s*(?:bolt circle|pcd|bcd|pitch circle)", r"(?:bolt circle|pcd|bcd)\s*(?:of\s*)?" + NUM], t)
        if _need(errors, all([od, bore, T, bc, d, n]),
                 "Flange needs OD, bore, thickness, bolt circle diameter, bolt size and bolt count."):
            p.update(od=od, bore=bore, thickness=T, bolt_circle=bc, hole_dia=d, bolts=n)

    elif kind == "spacer":
        od = _f([r"\b(?:od|outer diameter|outside diameter)\s*(?:of\s*)?" + NUM, NUM + r"\s*mm\s*(?:od|outer diameter)"], t)
        idd = _f([r"\b(?:id|inner diameter|bore)\s*(?:of\s*|dia\w*\s*)?" + NUM, NUM + r"\s*mm\s*(?:id|inner diameter|bore)"], t)
        Ln = _f([NUM + r"\s*mm\s*long", r"length\s*(?:of\s*)?" + NUM], t)
        if _need(errors, od and idd and Ln, "Spacer needs OD, ID (or bore) and length, e.g. 'OD 20, ID 8, 15 mm long'."):
            p.update(od=od, bore=idd, length=Ln)

    elif kind == "shaft":
        D = _f([NUM + r"\s*mm\s*dia\w*", r"dia\w*\s*(?:of\s*)?" + NUM, r"[ø⌀]\s*" + NUM], t)
        Ln = _f([NUM + r"\s*mm\s*long", r"length\s*(?:of\s*)?" + NUM], t)
        if _need(errors, D and Ln, "Shaft needs diameter ('25 mm diameter') and length ('300 mm long')."):
            p.update(diameter=D, length=Ln)

    elif kind == "enclosure":
        m = TRIPLE.search(t)
        if _need(errors, m, "Enclosure needs length x width x height, e.g. '160x100x60 mm'."):
            L, W, H = map(float, m.groups())
            w = _f([NUM + r"\s*mm\s*wall", r"wall\w*\s*(?:thickness\s*)?(?:of\s*)?" + NUM], t)
            if w is None:
                w = 3.0
                notes.append("Wall thickness assumed 3 mm.")
            p.update(length=L, width=W, height=H, wall=w)

    else:  # custom: no template, LLM path
        m = TRIPLE.search(t)
        if m:
            p["bbox_hint"] = sorted(map(float, m.groups()))

    spec = {"type": kind, "material": mat, "density": DENSITY.get(mat), "params": p, "notes": notes}
    if not errors and kind != "custom":
        errors += finish(spec)
    return spec, errors
