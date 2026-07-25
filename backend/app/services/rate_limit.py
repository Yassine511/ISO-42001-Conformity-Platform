"""Throttle for the password-checking endpoints (audit §3.2 / README TODO).

WHAT THIS IS FOR. Two things become cheap without it:

1. Online password guessing against a known address.
2. Account enumeration. `/api/auth/signup` must answer "this address is
   already taken" — with no e-mail server it either creates the account or
   refuses, so the disclosure is structural and cannot be messaged away. What
   CAN be removed is the ability to ask the question thousands of times per
   minute. Throttling bounds the oracle; it does not close it. That trade-off
   is stated in the README rather than hidden behind a vaguer error message,
   which would cost every legitimate user clarity and buy an attacker nothing
   they cannot get by trying to log in.

DESIGN. A fixed-window counter per key, in process memory. Process-local is
consistent with the rest of the deployment (`--workers 1`, the /api/kb/index
single-flight) and is the honest choice for a self-hosted single-node app: a
shared store would be a lie about the architecture rather than an improvement
to it. Scaling out means moving this to Redis at the same time as the
assessment runner.

Keys are hashed, never raw: this structure is memory-resident and would
otherwise become an in-process list of the e-mail addresses people typed.

The limiter FAILS OPEN on its own errors — it protects an endpoint, it must
never be the reason nobody can log in.
"""

import hashlib
import threading
import time
from dataclasses import dataclass, field

# Deliberately generous: these bound automation, they are not meant to be felt
# by a person who mistyped their password twice.
LOGIN_MAX_ATTEMPTS = 10
LOGIN_WINDOW_SECONDS = 300.0

SIGNUP_MAX_ATTEMPTS = 20
SIGNUP_WINDOW_SECONDS = 3600.0

# Hard ceiling on tracked keys: an attacker rotating addresses must not be able
# to grow this dict without bound (the limiter would become the memory leak it
# exists to prevent). On overflow the oldest windows are dropped first.
MAX_TRACKED_KEYS = 20_000


@dataclass
class _Window:
    started_at: float
    count: int = 0


@dataclass
class RateLimiter:
    """Fixed-window counter. `hit()` returns the seconds to wait, or 0.0 when
    the call is allowed."""

    max_attempts: int
    window_seconds: float
    _windows: dict[str, _Window] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _key(self, *parts: str) -> str:
        return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()

    def hit(self, *parts: str) -> float:
        """Record an attempt. Returns retry-after seconds if it is refused."""
        try:
            key = self._key(*parts)
            now = time.monotonic()
            with self._lock:
                self._evict(now)
                window = self._windows.get(key)
                if window is None or now - window.started_at >= self.window_seconds:
                    self._windows[key] = _Window(started_at=now, count=1)
                    return 0.0
                window.count += 1
                if window.count > self.max_attempts:
                    return max(0.0, self.window_seconds - (now - window.started_at))
                return 0.0
        except Exception:  # fail open: never lock everyone out on our own bug
            return 0.0

    def reset(self, *parts: str) -> None:
        """Forget a key — called after a SUCCESSFUL authentication, so a person
        who eventually remembers their password is not still throttled."""
        try:
            with self._lock:
                self._windows.pop(self._key(*parts), None)
        except Exception:
            pass

    def clear(self) -> None:
        with self._lock:
            self._windows.clear()

    def _evict(self, now: float) -> None:
        """Drop expired windows; if still over the ceiling, drop oldest first.
        Caller holds the lock."""
        expired = [
            key
            for key, window in self._windows.items()
            if now - window.started_at >= self.window_seconds
        ]
        for key in expired:
            del self._windows[key]
        overflow = len(self._windows) - MAX_TRACKED_KEYS
        if overflow > 0:
            for key in sorted(self._windows, key=lambda k: self._windows[k].started_at)[
                :overflow
            ]:
                del self._windows[key]


# One limiter per protected surface.
login_limiter = RateLimiter(LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS)
signup_limiter = RateLimiter(SIGNUP_MAX_ATTEMPTS, SIGNUP_WINDOW_SECONDS)


def client_ip(request) -> str:
    """Best-effort client identity.

    X-Forwarded-For is honoured because the production deployment is behind
    nginx, where request.client.host is always the proxy. It is SPOOFABLE by a
    direct caller — which is why the limiters are keyed on (identifier, ip),
    never on ip alone: forging the header rotates only half the key, and the
    e-mail half is exactly what an enumeration or guessing attack must hold
    fixed."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
