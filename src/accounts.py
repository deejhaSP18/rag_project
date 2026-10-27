"""Accounts and login sessions (through the ORM models in db.py).

Passwords are stored as salted scrypt hashes. Login tokens are random, sent in an httpOnly
cookie, and stored only as a SHA-256 hash, so a copy of the database cannot be replayed.
"""
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from .db import AuthSession, User, now, session_scope

SESSION_DAYS = 14
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD = 8


class AccountError(ValueError):
    """A problem the user can fix (bad username, taken name, weak password)."""


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    salt_hex, digest_hex = stored.split("$")
    candidate = _hash_password(password, bytes.fromhex(salt_hex)).split("$")[1]
    return hmac.compare_digest(candidate, digest_hex)


# Burned on unknown usernames so a missing account takes as long to reject as a wrong password.
_DUMMY_HASH = _hash_password("not-a-real-password")


def _public(user: User) -> dict:
    return {"id": user.id, "username": user.username, "is_admin": user.is_admin}


def _by_name(db, username: str) -> User | None:
    return db.scalars(select(User).where(func.lower(User.username) == username.strip().lower())).first()


def create_user(username: str, password: str, is_admin: bool = False) -> dict:
    username = username.strip()
    if not USERNAME_RE.match(username):
        raise AccountError("Username must be 3-32 characters: letters, digits, '.', '_' or '-'.")
    if len(password) < MIN_PASSWORD:
        raise AccountError(f"Password must be at least {MIN_PASSWORD} characters.")
    with session_scope() as db:
        if _by_name(db, username):
            raise AccountError("That username is already taken.")
        user = User(username=username, password_hash=_hash_password(password), is_admin=is_admin)
        db.add(user)
        db.flush()
        return _public(user)


def has_users() -> bool:
    with session_scope() as db:
        return db.scalars(select(User.id).limit(1)).first() is not None


def authenticate(username: str, password: str) -> dict | None:
    with session_scope() as db:
        user = _by_name(db, username)
        ok = _verify_password(password, user.password_hash if user else _DUMMY_HASH)
        return _public(user) if user and ok else None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
    with session_scope() as db:
        db.execute(delete(AuthSession).where(AuthSession.expires_at < now()))  # tidy up
        db.add(AuthSession(token_hash=_token_hash(token), user_id=user_id, expires_at=expires))
    return token


def user_for_token(token: str | None) -> dict | None:
    if not token:
        return None
    with session_scope() as db:
        user = db.scalars(
            select(User).join(AuthSession, AuthSession.user_id == User.id)
            .where(AuthSession.token_hash == _token_hash(token), AuthSession.expires_at > now())
        ).first()
        return _public(user) if user else None


def end_session(token: str | None) -> None:
    if token:
        with session_scope() as db:
            db.execute(delete(AuthSession).where(AuthSession.token_hash == _token_hash(token)))


class LoginThrottle:
    """Allow a few failed logins per client per window (in memory; resets on restart)."""

    def __init__(self, limit: int = 8, window: int = 300):
        self.limit, self.window, self.failures = limit, window, {}

    def _recent(self, key: str) -> list[float]:
        cutoff = time.monotonic() - self.window
        self.failures[key] = [t for t in self.failures.get(key, []) if t > cutoff]
        return self.failures[key]

    def blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= self.limit

    def record_failure(self, key: str) -> None:
        self._recent(key).append(time.monotonic())

    def clear(self, key: str) -> None:
        self.failures.pop(key, None)
