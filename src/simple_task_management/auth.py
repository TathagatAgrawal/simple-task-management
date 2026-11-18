"""Password hashing, sessions, temporary passwords and a small login throttle."""

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta

from fastapi import Request, Response

from .db import now_iso

SESSION_DAYS = 30
COOKIE_NAME = "tb_session"
MIN_PASSWORD_LENGTH = 8

_N, _R, _P = 2**14, 8, 1
_TEMP_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i


def hash_password(password: str) -> str:
    """Hash a password with scrypt and a random salt, as ``scrypt$n$r$p$salt$hash``."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Check a password against a stored scrypt hash in constant time."""
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    candidate = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p)
    )
    return hmac.compare_digest(candidate.hex(), digest)


def temp_password() -> str:
    """Generate an easy-to-read one-time password like ``k7mqp-x3wfd``."""
    chars = [secrets.choice(_TEMP_ALPHABET) for _ in range(10)]
    return "".join(chars[:5]) + "-" + "".join(chars[5:])


def create_session(conn: sqlite3.Connection, user_id: int) -> str:
    """Store a new 30-day session for ``user_id`` and return its cookie token."""
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(UTC) + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
    with conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now_iso(),))
        conn.execute(
            "INSERT INTO sessions (token, user_id, csrf_token, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, secrets.token_urlsafe(32), expires),
        )
    return token


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    """Put the session token in an HttpOnly cookie, marked Secure when reached over HTTPS."""
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https" or request.headers.get("X-Forwarded-Proto") == "https",
    )


def session_user(conn: sqlite3.Connection, token: str | None) -> tuple[sqlite3.Row, str] | None:
    """Return ``(user, csrf_token)`` for a valid, unexpired session of an active user."""
    if not token:
        return None
    row = conn.execute(
        """SELECT u.*, s.csrf_token FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token = ? AND s.expires_at > ? AND u.is_active = 1""",
        (token, now_iso()),
    ).fetchone()
    return (row, row["csrf_token"]) if row else None


def end_session(conn: sqlite3.Connection, token: str | None) -> None:
    """Delete one session (sign out)."""
    if token:
        with conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


class LoginThrottle:
    """Slows down repeated failed logins for the same username.

    After ``free_attempts`` failures each further attempt waits one extra second (up to
    ``max_delay``). State is in memory, which is fine for a single-process app.
    """

    def __init__(self, free_attempts: int = 5, max_delay: float = 5.0) -> None:
        """Create an empty throttle."""
        self.free_attempts = free_attempts
        self.max_delay = max_delay
        self._failures: dict[str, int] = {}
        self._lock = threading.Lock()

    def wait(self, username: str) -> None:
        """Sleep according to how many times this username has recently failed."""
        with self._lock:
            failures = self._failures.get(username.lower(), 0)
        extra = failures - self.free_attempts + 1
        if extra > 0:
            time.sleep(min(extra, self.max_delay))

    def failed(self, username: str) -> None:
        """Record a failed attempt."""
        with self._lock:
            key = username.lower()
            self._failures[key] = self._failures.get(key, 0) + 1

    def succeeded(self, username: str) -> None:
        """Forget failures after a successful sign-in."""
        with self._lock:
            self._failures.pop(username.lower(), None)
