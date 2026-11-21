"""Multi-component assemblies from text: one component per line, optional placement phrases.
Placement is computed from known template extents and then VERIFIED against the generated geometry.
Phrases: 'on top of part 1', 'below part 2', 'beside part 1' (+x), 'left of part 1' (-x), 'in front of part 1' (-y),
'behind part 1' (+y), 'gap 2 mm', 'x=10 y=0 z=5' (absolute origin, or extra shift when relative), 'rotate 90 about x'."""
import copy, re

from .parser import NUM, parse
from .revise import editable, revise
from .templates import extent, generate

NEG = r"(-?\d+(?:\.\d+)?)"
REL = [("top", r"(?:on top of|above|over)"), ("bottom", r"(?:below|under|beneath)"),
       ("right", r"(?:to the right of|right of|beside|next to)"), ("left", r"(?:to the left of|left of)"),
       ("front", r"(?:in front of)"), ("back", r"(?:behind|at the back of)")]
REF = r"\s+(?:part|component)\s*#?(\d+)"
MAX_COMPONENTS = 12
PALETTE = [(0.49, 0.59, 0.72), (0.79, 0.55, 0.29), (0.44, 0.66, 0.54), (0.65, 0.48, 0.69), (0.79, 0.74, 0.35), (0.82, 0.44, 0.44)]


def split_placement(line):
    t, pl, errs = line.lower(), {}, []
    for kind, pat in REL:
        m = re.search(pat + REF, t)
        if m:
            pl["rel"], pl["ref"] = kind, int(m.group(1)); t = t.replace(m.group(0), " "); break
    m = re.search(r"\bgap\s*(?:of\s*)?" + NUM + r"\s*(?:mm)?", t)
    if m:
        pl["gap"] = float(m.group(1)); t = t.replace(m.group(0), " ")
    off = {}
    for m in re.finditer(r"(?:\bat\s+)?\b([xyz])\s*=\s*" + NEG + r"\s*(?:mm)?", t):
        off[m.group(1)] = float(m.group(2))
    t = re.sub(r"(?:\bat\s+)?\b[xyz]\s*=\s*" + NEG + r"\s*(?:mm)?", " ", t)
    if off:
        pl["offset"] = off
    m = re.search(r"rotate\w*\s*(?:by\s*)?(\d+)\s*(?:°|deg\w*)?\s*(?:about|around|on)\s*(?:the\s*)?([xyz])\b", t)
    if m:
        ang = int(m.group(1)) % 360
        if ang % 90:
            errs.append("Rotation must be a multiple of 90 degrees.")
        elif ang:
            pl["rot"] = [m.group(2), ang]
        t = t.replace(m.group(0), " ")
    return t, pl, errs


def _rot_ext(mn, mx, axis, ang):
    if not ang:
        return list(mn), list(mx)
    c, s = {90: (0, 1), 180: (-1, 0), 270: (0, -1)}[ang]
    pts = []
    for x in (mn[0], mx[0]):
        for y in (mn[1], mx[1]):
            for z in (mn[2], mx[2]):
                pts.append({"x": (x, y * c - z * s, y * s + z * c), "y": (x * c + z * s, y, -x * s + z * c),
                            "z": (x * c - y * s, x * s + y * c, z)}[axis])
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def compute_transforms(plan):
    """(Re)compute rotation/translation/expected extents for every component from specs + placement phrases."""
    placed = {}
    for c in plan["components"]:
        c["errors"] = [e for e in c.get("errors", []) if not e.startswith("Placement:")]
        if c["errors"]:
            continue
        pl, i = c["placement"], c["index"]
        mn, mx = extent(c["spec"])
        rot = pl.get("rot")
        mn, mx = _rot_ext(mn, mx, *rot) if rot else (mn, mx)
        off = pl.get("offset", {})
        t = [0.0, 0.0, 0.0]
        if "rel" in pl:
            ref = placed.get(pl["ref"])
            if ref is None:
                c["errors"].append(f"Placement: part {pl['ref']} must be an earlier, valid component."); continue
            rmn, rmx, g = ref[0], ref[1], pl.get("gap", 0.0)
            ctr = lambda a, b, k: (a[k] + b[k]) / 2
            k = pl["rel"]
            if k in ("top", "bottom"):
                t[0] = ctr(rmn, rmx, 0) - ctr(mn, mx, 0); t[1] = ctr(rmn, rmx, 1) - ctr(mn, mx, 1)
                t[2] = rmx[2] + g - mn[2] if k == "top" else rmn[2] - g - mx[2]
            else:
                ax, other = (0, 1) if k in ("right", "left") else (1, 0)
                t[ax] = rmx[ax] + g - mn[ax] if k in ("right", "back") else rmn[ax] - g - mx[ax]
                t[other] = ctr(rmn, rmx, other) - ctr(mn, mx, other)
                t[2] = rmn[2] - mn[2]
            for j, a in enumerate("xyz"):
                t[j] += off.get(a, 0.0)
        else:
            if pl.get("ref"):
                pass
            t = [off.get("x", 0.0), off.get("y", 0.0), off.get("z", 0.0)]
        t = [round(v, 4) for v in t]
        c["transform"] = {"rot": rot, "t": t}
        c["bbox_min"] = [round(mn[j] + t[j], 4) for j in range(3)]
        c["bbox_max"] = [round(mx[j] + t[j], 4) for j in range(3)]
        placed[i] = (c["bbox_min"], c["bbox_max"])
    plan["errors"] = [f"Component {c['index']}: {e}" for c in plan["components"] for e in c["errors"]]
    return plan


def plan_assembly(text, fuse=True):
    lines = [re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", l).strip() for l in text.splitlines()]
    lines = [l for l in lines if l]
    plan = {"fuse": bool(fuse), "components": [], "errors": []}
    if not lines:
        plan["errors"].append("Describe at least one component (one per line)."); return plan
    if len(lines) > MAX_COMPONENTS:
        plan["errors"].append(f"At most {MAX_COMPONENTS} components per assembly."); return plan
    for i, line in enumerate(lines, 1):
        clean, pl, perr = split_placement(line)
        spec, errs = parse(clean)
        errs = perr + errs
        if spec["type"] == "custom":
            errs.append("No template for this part type (assemblies support template parts only).")
        if i == 1 and pl.get("rel"):
            errs.append("Placement: the first component cannot be placed relative to another part.")
        if pl.get("ref") and pl["ref"] >= i:
            errs.append("Placement: a component can only refer to an earlier part.")
        plan["components"].append({"index": i, "prompt": line, "spec": spec, "placement": pl, "errors": errs})
    return compute_transforms(plan)


def summary(plan):
    out = []
    for c in plan["components"]:
        if c.get("bbox_min"):
            d = [round(b - a, 2) for a, b in zip(c["bbox_min"], c["bbox_max"])]
            out.append(f"{c['index']} · {c['spec']['type']} · {d[0]}×{d[1]}×{d[2]} mm · origin at {c['transform']['t']}"
                       + (f" · rotated {c['transform']['rot']}" if c["transform"]["rot"] else ""))
        else:
            out.append(f"{c['index']} · {c['spec']['type']} · (not placed: see errors)")
    return out


def build(plan):
    """Return (cadquery_source, expected). Source defines result (fused), components, assembly, extra_metrics."""
    L = ["import cadquery as cq", "import math", ""]
    exp = {"components": []}
    for c in plan["components"]:
        code, e = generate(c["spec"])
        body = "\n".join("    " + ln for ln in code.splitlines() if not ln.startswith("import cadquery"))
        L += [f"def make_{c['index']}():", body, "    return result", ""]
        i, tr = c["index"], c["transform"]
        L.append(f"c{i} = make_{i}()")
        if tr["rot"]:
            vec = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[tr["rot"][0]]
            L.append(f"c{i} = c{i}.rotate((0, 0, 0), {vec}, {tr['rot'][1]})")
        L.append(f"c{i} = c{i}.translate({tuple(tr['t'])})")
        exp["components"].append({"name": f"component_{i}", "bbox_min": c["bbox_min"], "bbox_max": c["bbox_max"],
                                  "volume": e["volume"], "hole_dia": e.get("hole_dia"), "hole_count": e.get("hole_count", 0)})
    n = [c["index"] for c in plan["components"]]
    L.append("components = {" + ", ".join(f'"component_{i}": c{i}' for i in n) + "}")
    L.append('assembly = cq.Assembly(name="assembly")')
    for k, c in enumerate(plan["components"]):
        r, g, b = PALETTE[k % len(PALETTE)]
        L.append(f'assembly.add(c{c["index"]}, name="part_{c["index"]}_{c["spec"]["type"]}", color=cq.Color({r}, {g}, {b}, 1.0))')
    L.append(f"result = c{n[0]}")
    L += [f"result = result.union(c{i})" for i in n[1:]]
    L += ["", "def overlap(a, b):", "    try:", "        return sum(s.Volume() for s in a.intersect(b).solids().vals())",
          "    except Exception:", "        return 0.0", "",
          "extra_metrics = {\"interference\": [" + ", ".join(f"[{i}, {j}, overlap(c{i}, c{j})]" for a, i in enumerate(n) for j in n[a + 1:]) + "]}"]
    allmn = [min(c["bbox_min"][k] for c in plan["components"]) for k in range(3)]
    allmx = [max(c["bbox_max"][k] for c in plan["components"]) for k in range(3)]
    exp["fused_bbox_min"], exp["fused_bbox_max"] = allmn, allmx
    return "\n".join(L) + "\n", exp


def editable_plan(plan):
    out = {}
    for c in plan["components"]:
        out.update({f"{c['index']}.{k}": v for k, v in editable(c["spec"]).items()})
    return out


def revise_plan(plan, changes):
    new, errors = copy.deepcopy(plan), []
    by = {}
    for k, v in changes.items():
        m = re.match(r"^(\d+)\.(.+)$", k)
        if not m or int(m.group(1)) > len(new["components"]):
            errors.append(f"'{k}' is not an editable parameter."); continue
        by.setdefault(int(m.group(1)), {})[m.group(2)] = v
    for i, ch in by.items():
        c = new["components"][i - 1]
        spec, errs = revise(c["spec"], ch)
        errors += [f"Component {i}: {e}" for e in errs]
        if not errs:
            c["spec"] = spec
    if errors:
        return plan, errors
    compute_transforms(new)
    return (plan, new["errors"]) if new["errors"] else (new, [])
