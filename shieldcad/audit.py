"""Append-only, hash-chained audit log (tamper-evident, safe for concurrent writers)."""
import fcntl, hashlib, json, os
from pathlib import Path

GENESIS = "0" * 64


def _h(rec):
    return hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def append(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        lines = f.read().strip().splitlines()
        prev = json.loads(lines[-1])["hash"] if lines else GENESIS
        record = {**record, "prev": prev}
        record["hash"] = _h(record)
        f.write(json.dumps(record, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return record["hash"]


def verify(path):
    """Return (ok, index_of_first_bad_line or None). A missing/empty log is valid."""
    path = Path(path)
    if not path.exists():
        return True, None
    prev = GENESIS
    for i, line in enumerate(path.read_text().strip().splitlines()):
        rec = json.loads(line)
        h = rec.pop("hash")
        if rec["prev"] != prev or _h(rec) != h:
            return False, i
        prev = h
    return True, None
