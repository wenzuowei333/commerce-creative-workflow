import json
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock

from argon2 import PasswordHasher
from redis import Redis

from app.config import Settings

PASSWORD_HASHER = PasswordHasher()


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except Exception:
        return False


@dataclass(frozen=True)
class SessionData:
    user_id: str
    csrf_token: str
    expires_at: datetime


class MemorySessionStore:
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, SessionData] = {}
        self._lock = Lock()

    def create(self, user_id: str) -> tuple[str, SessionData]:
        session_id = secrets.token_urlsafe(32)
        data = SessionData(
            user_id=user_id,
            csrf_token=secrets.token_urlsafe(24),
            expires_at=datetime.now(UTC) + timedelta(seconds=self.ttl_seconds),
        )
        with self._lock:
            self._sessions[session_id] = data
        return session_id, data

    def get(self, session_id: str) -> SessionData | None:
        with self._lock:
            data = self._sessions.get(session_id)
            if data and data.expires_at > datetime.now(UTC):
                return data
            self._sessions.pop(session_id, None)
        return None

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)


class RedisSessionStore:
    def __init__(self, redis_url: str, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self.client = Redis.from_url(redis_url, decode_responses=True)

    @staticmethod
    def _key(session_id: str) -> str:
        return f"image-studio:session:{session_id}"

    def create(self, user_id: str) -> tuple[str, SessionData]:
        session_id = secrets.token_urlsafe(32)
        data = SessionData(
            user_id=user_id,
            csrf_token=secrets.token_urlsafe(24),
            expires_at=datetime.now(UTC) + timedelta(seconds=self.ttl_seconds),
        )
        self.client.setex(
            self._key(session_id),
            self.ttl_seconds,
            json.dumps(
                {
                    "user_id": data.user_id,
                    "csrf_token": data.csrf_token,
                    "expires_at": data.expires_at.isoformat(),
                }
            ),
        )
        return session_id, data

    def get(self, session_id: str) -> SessionData | None:
        if not session_id:
            return None
        raw = self.client.get(self._key(session_id))
        if not raw:
            return None
        try:
            payload = json.loads(raw)
            data = SessionData(
                user_id=payload["user_id"],
                csrf_token=payload["csrf_token"],
                expires_at=datetime.fromisoformat(payload["expires_at"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.delete(session_id)
            return None
        if data.expires_at <= datetime.now(UTC):
            self.delete(session_id)
            return None
        return data

    def delete(self, session_id: str) -> None:
        if session_id:
            self.client.delete(self._key(session_id))


def build_session_store(settings: Settings):
    if settings.session_backend == "redis":
        return RedisSessionStore(settings.redis_url, settings.session_ttl_seconds)
    return MemorySessionStore(settings.session_ttl_seconds)


class MemoryLoginLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._attempts: dict[str, tuple[int, float]] = {}
        self._lock = Lock()

    def check(self, key: str) -> tuple[bool, int]:
        with self._lock:
            count, expires_at = self._attempts.get(key, (0, 0))
            now = time.monotonic()
            if expires_at <= now:
                self._attempts.pop(key, None)
                return True, 0
            return count < self.limit, max(int(expires_at - now), 1)

    def record_failure(self, key: str) -> None:
        with self._lock:
            count, expires_at = self._attempts.get(key, (0, 0))
            now = time.monotonic()
            if expires_at <= now:
                count = 0
                expires_at = now + self.window_seconds
            self._attempts[key] = (count + 1, expires_at)

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


class RedisLoginLimiter:
    def __init__(self, redis_url: str, limit: int, window_seconds: int) -> None:
        self.client = Redis.from_url(redis_url, decode_responses=True)
        self.limit = limit
        self.window_seconds = window_seconds

    @staticmethod
    def _key(key: str) -> str:
        return f"image-studio:login-attempt:{key}"

    def check(self, key: str) -> tuple[bool, int]:
        redis_key = self._key(key)
        count = int(self.client.get(redis_key) or 0)
        ttl = max(self.client.ttl(redis_key), 0)
        return count < self.limit, ttl

    def record_failure(self, key: str) -> None:
        redis_key = self._key(key)
        count = self.client.incr(redis_key)
        if count == 1:
            self.client.expire(redis_key, self.window_seconds)

    def reset(self, key: str) -> None:
        self.client.delete(self._key(key))


def build_login_limiter(settings: Settings):
    if settings.session_backend == "redis":
        return RedisLoginLimiter(
            settings.redis_url,
            settings.login_attempt_limit,
            settings.login_window_seconds,
        )
    return MemoryLoginLimiter(settings.login_attempt_limit, settings.login_window_seconds)
