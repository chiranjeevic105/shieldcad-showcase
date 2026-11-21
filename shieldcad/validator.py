"""Compare measured geometry against what the spec says it must be."""


def validate(m, exp, tol_mm=0.05, vol_rel=0.005):
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    add("valid_single_solid", m["is_valid"] and m["n_solids"] == 1, f"valid={m['is_valid']} solids={m['n_solids']}")
    if exp.get("bbox"):
        ok = all(abs(a - b) <= tol_mm for a, b in zip(m["bbox"], exp["bbox"]))
        add("bounding_box", ok, f"measured {[round(x, 3) for x in m['bbox']]} expected {exp['bbox']}")
    if exp.get("volume") is not None:
        rel = abs(m["volume"] - exp["volume"]) / exp["volume"]
        add("volume", rel <= vol_rel, f"measured {m['volume']:.1f} expected {exp['volume']:.1f} mm3 (err {rel:.3%})")
    if exp.get("hole_dia"):
        got = sum(1 for r in m["cyl_radii"] if abs(r - exp["hole_dia"] / 2) <= 0.01)
        add("hole_count", got == exp["hole_count"], f"found {got} holes of dia {exp['hole_dia']} expected {exp['hole_count']}")
    return {"passed": all(c["pass"] for c in checks), "checks": checks}


def validate_assembly(m, exp, fuse=True, tol_mm=0.05, vol_rel=0.005):
    """Per-component placement/volume/holes, then the fused solid: validity, connectivity, bbox, volume conservation."""
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    r3 = lambda v: [round(x, 2) for x in v]
    for ce in exp["components"]:
        n, cm = ce["name"], m.get("components", {}).get(ce["name"])
        if not cm:
            add(f"{n}: present", False, "missing from output"); continue
        add(f"{n}: valid solid", cm["is_valid"] and cm["n_solids"] == 1, f"valid={cm['is_valid']} solids={cm['n_solids']}")
        ok = all(abs(a - b) <= tol_mm for a, b in zip(cm["bbox_min"] + cm["bbox_max"], ce["bbox_min"] + ce["bbox_max"]))
        add(f"{n}: placement", ok, f"min {r3(cm['bbox_min'])} max {r3(cm['bbox_max'])} · expected min {r3(ce['bbox_min'])} max {r3(ce['bbox_max'])}")
        rel = abs(cm["volume"] - ce["volume"]) / ce["volume"]
        add(f"{n}: volume", rel <= vol_rel, f"{cm['volume']:.0f} vs {ce['volume']:.0f} mm3 (err {rel:.3%})")
        if ce.get("hole_dia"):
            got = sum(1 for r in cm["cyl_radii"] if abs(r - ce["hole_dia"] / 2) <= 0.01)
            add(f"{n}: holes", got == ce["hole_count"], f"found {got} of dia {ce['hole_dia']}, expected {ce['hole_count']}")
    inter = [x for x in ((m.get("extra") or {}).get("interference") or []) if x[2] > 0.01]
    add("fused: valid solid", m["is_valid"], f"valid={m['is_valid']}")
    add("fused: one connected body", m["n_solids"] == 1 or not fuse,
        f"{m['n_solids']} body/bodies" + ("" if m["n_solids"] == 1 else " (parts do not touch)" if fuse else " (separate bodies allowed)"))
    ok = all(abs(a - b) <= tol_mm for a, b in zip(m["bbox_min"] + m["bbox_max"], exp["fused_bbox_min"] + exp["fused_bbox_max"]))
    add("fused: overall bounding box", ok, f"min {r3(m['bbox_min'])} max {r3(m['bbox_max'])}")
    expv = sum(c["volume"] for c in exp["components"]) - sum(x[2] for x in inter)
    rel = abs(m["volume"] - expv) / expv
    add("fused: volume conservation", rel <= vol_rel, f"{m['volume']:.0f} vs sum of parts minus overlaps {expv:.0f} mm3 (err {rel:.3%})")
    return {"passed": all(c["pass"] for c in checks), "checks": checks, "interference": inter}
