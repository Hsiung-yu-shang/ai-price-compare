"""Bounded, in-memory admin sessions and a file-based systemd crawler trigger."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from scripts.admin_password import verify_password


SESSION_SECONDS = 15 * 60
LOGIN_WINDOW_SECONDS = 5 * 60
MAX_FAILED_LOGINS = 5
REFRESH_COOLDOWN_SECONDS = 10 * 60


def valid_admin_origin(origin: str | None, host: str | None) -> bool:
    """Require a same-host HTTPS browser request, except loopback development."""
    if not origin or not host:
        return False
    parsed = urlsplit(origin)
    if parsed.path not in ("", "/"):
        return False
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        return False
    if parsed.scheme == "https":
        return parsed.netloc.lower() == host.lower()
    loopback = {"localhost", "127.0.0.1", "::1"}
    return parsed.scheme == "http" and parsed.hostname in loopback and \
        urlsplit("//" + host).hostname in loopback


class AdminManager:
    def __init__(self, password_hash: str, marker: Path, status_file: Path):
        self.password_hash = password_hash
        self.marker = marker
        self.status_file = status_file
        self._lock = threading.Lock()
        self._verifying = False
        self._failures = deque()
        self._sessions = OrderedDict()
        self._last_refresh = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.password_hash)

    def login(self, password: str) -> tuple[int, str | None]:
        if not self.enabled:
            return 503, None
        now = time.monotonic()
        with self._lock:
            while self._failures and now - self._failures[0] > LOGIN_WINDOW_SECONDS:
                self._failures.popleft()
            if len(self._failures) >= MAX_FAILED_LOGINS or self._verifying:
                return 429, None
            self._verifying = True
        try:
            correct = verify_password(password, self.password_hash)
        finally:
            with self._lock:
                self._verifying = False

        with self._lock:
            if not correct:
                self._failures.append(time.monotonic())
                return 401, None
            self._failures.clear()
            token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token.encode("ascii")).digest()
            self._sessions[token_hash] = time.monotonic() + SESSION_SECONDS
            while len(self._sessions) > 4:
                self._sessions.popitem(last=False)
            return 200, token

    def authorized(self, token: str | None) -> bool:
        if not self.enabled or not token or len(token) > 128:
            return False
        token_hash = hashlib.sha256(token.encode("utf-8")).digest()
        now = time.monotonic()
        with self._lock:
            for key, expiry in list(self._sessions.items()):
                if expiry <= now:
                    del self._sessions[key]
            return token_hash in self._sessions

    def logout(self, token: str) -> None:
        token_hash = hashlib.sha256(token.encode("utf-8")).digest()
        with self._lock:
            self._sessions.pop(token_hash, None)

    def request_refresh(self) -> tuple[int, int]:
        """Create one marker; the enabled systemd .path unit starts the crawler."""
        now = time.monotonic()
        with self._lock:
            remaining = REFRESH_COOLDOWN_SECONDS - (now - self._last_refresh)
            if remaining > 0:
                return 429, int(remaining) + 1
            try:
                descriptor = os.open(self.marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                return 202, 0
            with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                stream.write(datetime.now(timezone.utc).isoformat() + "\n")
            self._last_refresh = now
            return 202, 0

    def status(self) -> dict:
        result = {"queued": self.marker.exists(), "state": "unknown", "started_at": None,
                  "finished_at": None, "platforms": []}
        try:
            with self.status_file.open("r", encoding="utf-8") as stream:
                saved = json.loads(stream.read(4096))
            if isinstance(saved, dict):
                result.update({key: saved.get(key) for key in
                               ("state", "started_at", "finished_at", "platforms")})
        except (FileNotFoundError, OSError, ValueError):
            pass
        if result["state"] == "running" and result["started_at"]:
            try:
                started = datetime.fromisoformat(result["started_at"])
                if (datetime.now(timezone.utc) - started).total_seconds() > 11 * 60:
                    result["state"] = "interrupted"
            except (TypeError, ValueError):
                result["state"] = "unknown"
        return result
