"""User management. Keys are shown once; only SHA-256 hashes are stored.
usage: shieldcad-admin add-user NAME ROLE   |   shieldcad-admin list-users   |   shieldcad-admin remove-user NAME"""
import argparse, datetime, hashlib, json, os, secrets
from pathlib import Path

ROLES = ("viewer", "engineer", "admin")


def data_dir():
    return Path(os.environ.get("SHIELDCAD_DATA_DIR", "data"))


def users_path():
    return Path(os.environ.get("SHIELDCAD_USERS", str(data_dir() / "users.json")))


def load_users():
    p = users_path()
    return json.loads(p.read_text()) if p.exists() else {}


def _save(users):
    p = users_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(users, indent=2))
    os.chmod(p, 0o600)


def add_user(name, role, days=None):
    if role not in ROLES:
        raise ValueError("role must be one of " + ", ".join(ROLES))
    users = load_users()
    if name in users:
        raise ValueError("user exists")
    key = secrets.token_urlsafe(32)
    users[name] = {"role": role, "key_sha256": hashlib.sha256(key.encode()).hexdigest()}
    if days:
        users[name]["expires"] = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
    _save(users)
    return key


def rotate_key(name, days=None):
    users = load_users()
    if name not in users:
        raise ValueError("no such user")
    key = secrets.token_urlsafe(32)
    users[name]["key_sha256"] = hashlib.sha256(key.encode()).hexdigest()
    users[name].pop("expires", None)
    if days:
        users[name]["expires"] = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
    _save(users)
    return key


def main(argv=None):
    ap = argparse.ArgumentParser(prog="shieldcad-admin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add-user"); a.add_argument("name"); a.add_argument("role", choices=ROLES); a.add_argument("--days", type=int, help="key validity in days")
    k = sub.add_parser("rotate-key"); k.add_argument("name"); k.add_argument("--days", type=int)
    sub.add_parser("list-users")
    r = sub.add_parser("remove-user"); r.add_argument("name")
    args = ap.parse_args(argv)
    if args.cmd == "add-user":
        print("API key (shown once, store it safely):\n" + add_user(args.name, args.role, args.days))
    elif args.cmd == "rotate-key":
        print("New API key (shown once):\n" + rotate_key(args.name, args.days))
    elif args.cmd == "list-users":
        for n, u in load_users().items():
            print(n, u["role"], u.get("expires", "no expiry"))
    else:
        users = load_users()
        users.pop(args.name, None)
        _save(users)
        print("removed", args.name)


if __name__ == "__main__":
    main()
