"""Runs INSIDE the sandbox subprocess (standalone script, no package imports).
usage: python -I runner.py code.py outdir
User code contract: `result` (cq.Workplane); optional `components` {name: Workplane}, `assembly` (cq.Assembly), `extra_metrics` (dict)."""
import sys, json, builtins


def main():
    code_path, out = sys.argv[1], sys.argv[2]
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    import cadquery as cq
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    real_import = builtins.__import__

    def imp(name, *a, **k):
        if name.split(".")[0] not in ("cadquery", "math"):
            raise ImportError("blocked import: " + name)
        return real_import(name, *a, **k)

    banned = {"open", "eval", "exec", "compile", "input", "breakpoint", "exit", "quit", "help"}
    safe = {k: v for k, v in vars(builtins).items() if k not in banned}
    safe["__import__"] = imp
    g = {"__builtins__": safe}
    exec(compile(open(code_path).read(), "part.py", "exec"), g)
    result = g["result"]

    def measure(wp):
        s = wp.val()
        box = Bnd_Box()
        BRepBndLib.AddOptimal_s(s.wrapped, box, False, False)  # tight box (default one overshoots curves)
        x0, y0, z0, x1, y1, z1 = box.Get()
        radii = []
        for f in wp.faces().vals():
            sf = BRepAdaptor_Surface(f.wrapped)
            if sf.GetType() == GeomAbs_Cylinder:
                radii.append(round(sf.Cylinder().Radius(), 4))
        return {"bbox_min": [x0, y0, z0], "bbox_max": [x1, y1, z1], "bbox": sorted([x1 - x0, y1 - y0, z1 - z0]),
                "volume": s.Volume(), "is_valid": bool(s.isValid()), "n_solids": len(wp.solids().vals()), "cyl_radii": radii}

    files = []

    def opt(name, fn):  # optional formats must never fail the run
        try:
            fn(out + "/" + name)
            files.append(name)
        except Exception:
            pass

    def iges(path):
        from OCP.IGESControl import IGESControl_Writer
        w = IGESControl_Writer(); w.AddShape(result.val().wrapped); w.ComputeModel()
        if not w.Write(path): raise RuntimeError("iges")

    def obj(path):
        v, t = result.val().tessellate(0.05, 0.2)
        with open(path, "w") as f:
            f.write("# ShieldCAD export (mm)\n")
            f.writelines(f"v {p.x:.5f} {p.y:.5f} {p.z:.5f}\n" for p in v)
            f.writelines(f"f {a + 1} {b + 1} {c + 1}\n" for a, b, c in t)

    def glb(path):
        a = cq.Assembly(name="model"); a.add(result, name="part"); a.export(path)

    cq.exporters.export(result, out + "/part.step"); files.append("part.step")
    cq.exporters.export(result, out + "/part.stl"); files.append("part.stl")
    opt("part.iges", iges)
    opt("part.brep", lambda p: result.val().exportBrep(p))
    opt("part.3mf", lambda p: cq.exporters.export(result, p))
    opt("part.obj", obj)
    opt("part.glb", glb)
    comps = g.get("components") or {}
    for name, wp in comps.items():
        cq.exporters.export(wp, out + f"/{name}.step"); files.append(name + ".step")
        cq.exporters.export(wp, out + f"/{name}.stl"); files.append(name + ".stl")
    if g.get("assembly") is not None:
        opt("assembly.step", lambda p: g["assembly"].export(p))
        opt("assembly.glb", lambda p: g["assembly"].export(p))
    m = measure(result)
    m.update(files=files, components={n: measure(w) for n, w in comps.items()}, extra=g.get("extra_metrics"))
    print("@@METRICS@@" + json.dumps(m))


try:
    main()
except Exception as e:  # report, never crash silently
    print("@@ERROR@@" + type(e).__name__ + ": " + str(e))
    sys.exit(1)
