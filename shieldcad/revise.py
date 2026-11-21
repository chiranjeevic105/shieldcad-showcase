"""Parameter editing: change numbers on an existing spec, re-check feasibility, regenerate as a new revision."""
import copy

INT_KEYS = {"holes_per_leg", "bolts", "layout.n"}


def editable(spec):
    """Flat {name: value} of numeric parameters a user may change (template parts only)."""
    if spec.get("type") == "custom":
        return {}
    out = {}
    for k, v in spec["params"].items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = v
        elif k == "layout" and isinstance(v, dict):
            out.update({f"layout.{a}": b for a, b in v.items() if isinstance(b, (int, float))})
    return out


def revise(spec, changes):
    """Return (new_spec, errors). Never mutates the input."""
    from .parser import finish
    ed = editable(spec)
    if not ed:
        return spec, ["This part type has no editable parameters."]
    errors, new = [], copy.deepcopy(spec)
    for k, v in changes.items():
        if k not in ed:
            errors.append(f"'{k}' is not an editable parameter."); continue
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0 or v > 100000:
            errors.append(f"'{k}' must be a positive number (max 100000)."); continue
        v = int(v) if k in INT_KEYS else float(v)
        if k.startswith("layout."):
            new["params"]["layout"][k.split(".", 1)[1]] = v
        else:
            new["params"][k] = v
    if errors:
        return spec, errors
    new["notes"] = [n for n in new.get("notes", []) if not n.startswith("Edge offset assumed")]
    errors = finish(new)
    return (spec if errors else new), errors
