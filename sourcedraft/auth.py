"""Team accounts for the web UI: PBKDF2-hashed passwords, HTTP Basic auth.

Accounts live in a users file (one `帳號:雜湊` per line) pointed to by
SOURCEDRAFT_USERS_FILE. Generate a line with:  sourcedraft adduser <帳號>
Basic auth sends the password with every request, so always serve over HTTPS
(the bundled Caddy config does this).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path

ITERATIONS = 600_000


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def check_password(password: str, encoded: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = encoded.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(iters))
    return hmac.compare_digest(digest, base64.b64decode(hash_b64))


def load_users(path: str | None = None) -> dict[str, str]:
    path = path or os.environ.get("SOURCEDRAFT_USERS_FILE", "")
    if not path or not Path(path).is_file():
        return {}
    users: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        name, encoded = line.split(":", 1)
        users[name.strip()] = encoded.strip()
    return users


def parse_basic(header: str | None) -> tuple[str, str] | None:
    if not header or not header.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
    except Exception:
        return None
    name, sep, password = raw.partition(":")
    return (name, password) if sep else None


class Authenticator:
    """Caches verified credentials so PBKDF2 runs once per user/password, not per request."""

    def __init__(self, users: dict[str, str]):
        self.users = users
        self._ok: set[str] = set()

    def check(self, header: str | None) -> str | None:
        creds = parse_basic(header)
        if creds is None:
            return None
        name, password = creds
        encoded = self.users.get(name)
        if encoded is None:
            return None
        key = hashlib.sha256(f"{name}\0{password}\0{encoded}".encode()).hexdigest()
        if key in self._ok:
            return name
        if check_password(password, encoded):
            self._ok.add(key)
            return name
        return None
