"""Tested parametric templates. Each returns (cadquery_source, expected_checks). Code is stored with every part."""
import math

PI = math.pi


def _hole_area(d, n):
    return n * PI * (d / 2) ** 2


def plate(p):
    L, W, T, pts, d = p["length"], p["width"], p["thickness"], p["points"], p.get("hole_dia")
    r = p.get("corner_radius")
    code = f'import cadquery as cq\nresult = cq.Workplane("XY").box({L}, {W}, {T}, centered=(True, True, False))\n'
    if r:
        code += f'result = result.edges("|Z").fillet({r})\n'
    if pts:
        code += f'result = result.faces(">Z").workplane(centerOption="CenterOfBoundBox").pushPoints({pts}).hole({d})\n'
    vol = L * W * T - ((4 - PI) * r * r * T if r else 0) - (_hole_area(d, len(pts)) * T if pts else 0)
    return code, {"bbox": sorted([L, W, T]), "volume": vol, "hole_dia": d, "hole_count": len(pts)}


def bracket_l(p):
    A, B, W, T, n, d = p["leg_a"], p["leg_b"], p["width"], p["thickness"], p["holes_per_leg"], p.get("hole_dia")
    code = ('import cadquery as cq\n'
            f'base = cq.Workplane("XY").box({A}, {W}, {T}, centered=False).translate((0, {-W/2}, 0))\n'
            f'up = cq.Workplane("XY").box({T}, {W}, {B}, centered=False).translate((0, {-W/2}, 0))\n'
            'result = base.union(up)\n')
    if n:
        ys = [round(-W / 2 + W * (i + 1) / (n + 1), 4) for i in range(n)]
        bx, uz, r = round((A + T) / 2, 4), round((B + T) / 2, 4), d / 2
        code += (f'cut_base = cq.Workplane("XY").workplane(offset=-1).pushPoints([({bx}, y) for y in {ys}]).circle({r}).extrude({T + 2})\n'
                 f'cut_up = cq.Workplane("YZ").workplane(offset=-1).pushPoints([(y, {uz}) for y in {ys}]).circle({r}).extrude({T + 2})\n'
                 'result = result.cut(cut_base).cut(cut_up)\n')
    vol = A * W * T + T * W * (B - T) - (_hole_area(d, 2 * n) * T if n else 0)
    return code, {"bbox": sorted([A, W, B]), "volume": vol, "hole_dia": d, "hole_count": 2 * n}


def flange(p):
    OD, bore, T, bc, d, n = p["od"], p["bore"], p["thickness"], p["bolt_circle"], p["hole_dia"], p["bolts"]
    code = ('import cadquery as cq\n'
            f'result = cq.Workplane("XY").circle({OD/2}).circle({bore/2}).extrude({T})\n'
            f'result = result.faces(">Z").workplane(centerOption="CenterOfBoundBox").polarArray({bc/2}, 0, 360, {n}).hole({d})\n')
    vol = PI * (OD ** 2 - bore ** 2) / 4 * T - _hole_area(d, n) * T
    return code, {"bbox": sorted([OD, OD, T]), "volume": vol, "hole_dia": d, "hole_count": n}


def spacer(p):
    OD, bore, L = p["od"], p["bore"], p["length"]
    code = f'import cadquery as cq\nresult = cq.Workplane("XY").circle({OD/2}).circle({bore/2}).extrude({L})\n'
    return code, {"bbox": sorted([OD, OD, L]), "volume": PI * (OD ** 2 - bore ** 2) / 4 * L, "hole_dia": bore, "hole_count": 1}


def shaft(p):
    D, L = p["diameter"], p["length"]
    code = f'import cadquery as cq\nresult = cq.Workplane("XY").circle({D/2}).extrude({L})\n'
    return code, {"bbox": sorted([D, D, L]), "volume": PI * D ** 2 / 4 * L}


def enclosure(p):
    L, W, H, w = p["length"], p["width"], p["height"], p["wall"]
    code = ('import cadquery as cq\n'
            f'result = cq.Workplane("XY").box({L}, {W}, {H}, centered=(True, True, False)).faces(">Z").shell({-w})\n')
    return code, {"bbox": sorted([L, W, H]), "volume": L * W * H - (L - 2 * w) * (W - 2 * w) * (H - w)}


GENERATORS = {"plate": plate, "bracket_l": bracket_l, "flange": flange, "spacer": spacer, "shaft": shaft, "enclosure": enclosure}


def generate(spec):
    return GENERATORS[spec["type"]](spec["params"])


def extent(spec):
    """Local-coordinate bounding box ((x0,y0,z0),(x1,y1,z1)) of a template part, before any placement."""
    k, p = spec["type"], spec["params"]
    if k == "plate":
        return (-p["length"] / 2, -p["width"] / 2, 0), (p["length"] / 2, p["width"] / 2, p["thickness"])
    if k == "bracket_l":
        return (0, -p["width"] / 2, 0), (p["leg_a"], p["width"] / 2, p["leg_b"])
    if k == "flange":
        r = p["od"] / 2
        return (-r, -r, 0), (r, r, p["thickness"])
    if k == "spacer":
        r = p["od"] / 2
        return (-r, -r, 0), (r, r, p["length"])
    if k == "shaft":
        r = p["diameter"] / 2
        return (-r, -r, 0), (r, r, p["length"])
    if k == "enclosure":
        return (-p["length"] / 2, -p["width"] / 2, 0), (p["length"] / 2, p["width"] / 2, p["height"])
    raise ValueError("no extent for " + k)
