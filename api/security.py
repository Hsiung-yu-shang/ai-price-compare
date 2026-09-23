"""Small, bounded admission guard for the public read-only application.

The edge should also rate-limit by visitor IP. This guard protects the LXC if
the edge rule is absent or traffic reaches the origin directly. It uses the
actual socket peer from ASGI, never a client-supplied forwarding header.
"""

import asyncio
import math
import time
from collections import OrderedDict


class ResourceGuardMiddleware:
    def __init__(
        self,
        app,
        per_client_per_minute=120,
        global_per_minute=600,
        max_concurrent=32,
        max_clients=4096,
    ):
        self.app = app
        self.per_client = per_client_per_minute
        self.global_limit = global_per_minute
        self.max_concurrent = max_concurrent
        self.max_clients = max_clients
        self._lock = asyncio.Lock()
        self._clients = OrderedDict()
        self._global_tokens = float(global_per_minute)
        self._global_updated = time.monotonic()
        self._active = 0

    @staticmethod
    def _refill(tokens, updated, capacity, now):
        return min(capacity, tokens + (now - updated) * capacity / 60)

    async def _admit(self, peer):
        async with self._lock:
            now = time.monotonic()
            self._global_tokens = self._refill(
                self._global_tokens, self._global_updated, self.global_limit, now
            )
            self._global_updated = now

            tokens, updated = self._clients.get(peer, (float(self.per_client), now))
            tokens = self._refill(tokens, updated, self.per_client, now)
            self._clients[peer] = (tokens, now)
            self._clients.move_to_end(peer)
            if len(self._clients) > self.max_clients:
                self._clients.popitem(last=False)

            if self._global_tokens < 1 or tokens < 1:
                global_wait = (1 - self._global_tokens) * 60 / self.global_limit
                peer_wait = (1 - tokens) * 60 / self.per_client
                return 429, max(1, math.ceil(max(global_wait, peer_wait)))
            if self._active >= self.max_concurrent:
                return 503, 1

            self._global_tokens -= 1
            self._clients[peer] = (tokens - 1, now)
            self._active += 1
            return 0, 0

    @staticmethod
    def _security_headers():
        return [
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"x-frame-options", b"DENY"),
            (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
            (
                b"content-security-policy",
                b"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                b"font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
                b"base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'",
            ),
        ]

    async def _reject(self, send, status, retry_after=0):
        headers = self._security_headers() + [(b"content-type", b"text/plain; charset=utf-8")]
        if retry_after:
            headers.append((b"retry-after", str(retry_after).encode("ascii")))
        if status == 405:
            headers.append((b"allow", b"GET, HEAD"))
        body = {
            405: b"Method not allowed",
            429: b"Too many requests",
            503: b"Server busy",
        }[status]
        headers.append((b"content-length", str(len(body)).encode("ascii")))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        client = scope.get("client")
        peer = client[0] if client else "unknown"
        status, retry_after = await self._admit(peer)
        if status:
            return await self._reject(send, status, retry_after)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(self._security_headers())
                if scope.get("path", "").startswith("/api/") and scope["method"] == "GET":
                    headers.append((b"cache-control", b"public, max-age=30"))
                message = {**message, "headers": headers}
            await send(message)

        try:
            if scope["method"] not in {"GET", "HEAD"}:
                await self._reject(send, 405)
            else:
                await self.app(scope, receive, send_with_headers)
        finally:
            async with self._lock:
                self._active -= 1
