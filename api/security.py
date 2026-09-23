"""Small, bounded admission guard for public reads and protected admin writes.

The edge should also rate-limit by visitor IP. This guard protects the LXC if
the edge rule is absent or traffic reaches the origin directly. It uses the
actual socket peer from ASGI, never a client-supplied forwarding header.
"""

import asyncio
import math
import time
from collections import OrderedDict


ADMIN_POST_PATHS = frozenset({"/api/admin/login", "/api/admin/refresh", "/api/admin/logout"})
MAX_ADMIN_BODY = 1024


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
        self._admin_active = 0

    @staticmethod
    def _refill(tokens, updated, capacity, now):
        return min(capacity, tokens + (now - updated) * capacity / 60)

    async def _admit(self, peer, admin_post=False):
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
            if admin_post and self._admin_active >= 2:
                return 503, 1

            self._global_tokens -= 1
            self._clients[peer] = (tokens - 1, now)
            self._active += 1
            if admin_post:
                self._admin_active += 1
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
        headers = self._security_headers() + [
            (b"content-type", b"text/plain; charset=utf-8"),
            (b"cache-control", b"no-store"),
        ]
        if retry_after:
            headers.append((b"retry-after", str(retry_after).encode("ascii")))
        if status == 405:
            headers.append((b"allow", b"GET, HEAD"))
        body = {
            405: b"Method not allowed",
            408: b"Request timeout",
            413: b"Request body too large",
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
        admin_post = scope["method"] == "POST" and scope.get("path", "") in ADMIN_POST_PATHS
        status, retry_after = await self._admit(peer, admin_post=admin_post)
        if status:
            return await self._reject(send, status, retry_after)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(self._security_headers())
                if scope.get("path", "").startswith("/api/admin/"):
                    headers.append((b"cache-control", b"no-store"))
                elif scope.get("path", "").startswith("/api/") and scope["method"] == "GET":
                    headers.append((b"cache-control", b"public, max-age=30"))
                message = {**message, "headers": headers}
            await send(message)

        try:
            method = scope["method"]
            path = scope.get("path", "")
            if method not in {"GET", "HEAD"} and not (method == "POST" and path in ADMIN_POST_PATHS):
                await self._reject(send, 405)
            elif method == "POST":
                headers = dict(scope.get("headers", []))
                try:
                    declared_length = int(headers.get(b"content-length", b"0"))
                except ValueError:
                    declared_length = MAX_ADMIN_BODY + 1
                if declared_length > MAX_ADMIN_BODY or declared_length < 0:
                    await self._reject(send, 413)
                    return

                received = 0
                parts = []
                deadline = asyncio.get_running_loop().time() + 5
                try:
                    while True:
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            raise asyncio.TimeoutError()
                        message = await asyncio.wait_for(receive(), remaining)
                        if message["type"] == "http.disconnect":
                            return
                        if message["type"] != "http.request":
                            continue
                        received += len(message.get("body", b""))
                        if received > MAX_ADMIN_BODY:
                            await self._reject(send, 413)
                            return
                        parts.append(message.get("body", b""))
                        if not message.get("more_body", False):
                            break
                except asyncio.TimeoutError:
                    await self._reject(send, 408)
                    return

                first = True

                async def replay_receive():
                    nonlocal first
                    if first:
                        first = False
                        return {"type": "http.request", "body": b"".join(parts), "more_body": False}
                    return await receive()

                await self.app(scope, replay_receive, send_with_headers)
            else:
                await self.app(scope, receive, send_with_headers)
        finally:
            async with self._lock:
                self._active -= 1
                if admin_post:
                    self._admin_active -= 1
