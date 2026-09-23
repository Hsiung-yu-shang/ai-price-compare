"""Exercise the public ASGI surface without binding a network port."""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.main import app
from api.admin import AdminManager, valid_admin_origin
from api.security import ResourceGuardMiddleware
from crawlers.gemini_crawler import GeminiPricingCrawler
from scripts.admin_password import hash_password, verify_password, write_password_file
from scripts import run_all


async def request(
    target, path="/", method="GET", peer="192.0.2.1", extra_headers=(), query=b"", body=b""
):
    messages = []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "scheme": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": query,
        "root_path": "",
        "headers": [(b"host", b"testserver"), *extra_headers],
        "client": (peer, 12345),
        "server": ("testserver", 80),
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    await target(scope, receive, send)
    response = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return response["status"], dict(response["headers"]), body


async def cheap_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


class ResourceSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_app_cannot_trigger_crawlers(self):
        status, _, _ = await request(
            app,
            "/api/crawler/trigger",
            method="POST",
            extra_headers=((b"x-admin-token", b"old-token"),),
        )
        self.assertEqual(status, 405)
        self.assertFalse(any(route.path == "/api/crawler/trigger" for route in app.routes))

    async def test_public_reads_and_validation(self):
        status, headers, body = await request(app, "/api/platforms")
        self.assertEqual(status, 200)
        self.assertIn(b"chatgpt", body)
        self.assertEqual(headers[b"x-content-type-options"], b"nosniff")
        self.assertIn(b"script-src 'self'", headers[b"content-security-policy"])
        self.assertEqual(headers[b"cache-control"], b"public, max-age=30")

        status, _, _ = await request(app, "/docs")
        self.assertEqual(status, 404)

        status, _, _ = await request(app, "/api/compare", query=b"country=INVALID")
        self.assertEqual(status, 422)

    async def test_limits_ignore_spoofed_forwarding_headers(self):
        guard = ResourceGuardMiddleware(
            cheap_app, per_client_per_minute=2, global_per_minute=3, max_concurrent=2
        )
        for fake_ip in (b"1.1.1.1", b"2.2.2.2"):
            status, _, _ = await request(
                guard, extra_headers=((b"x-forwarded-for", fake_ip),)
            )
            self.assertEqual(status, 200)

        status, headers, _ = await request(
            guard, extra_headers=((b"x-forwarded-for", b"3.3.3.3"),)
        )
        self.assertEqual(status, 429)
        self.assertIn(b"retry-after", headers)

        status, _, _ = await request(guard, peer="192.0.2.2")
        self.assertEqual(status, 200)
        status, _, _ = await request(guard, peer="192.0.2.3")
        self.assertEqual(status, 429)

    async def test_concurrency_limit_releases_slot(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_app(scope, receive, send):
            started.set()
            await release.wait()
            await cheap_app(scope, receive, send)

        guard = ResourceGuardMiddleware(
            slow_app, per_client_per_minute=10, global_per_minute=10, max_concurrent=1
        )
        first = asyncio.create_task(request(guard))
        await started.wait()
        status, headers, _ = await request(guard, peer="192.0.2.2")
        self.assertEqual(status, 503)
        self.assertIn(b"retry-after", headers)
        release.set()
        self.assertEqual((await first)[0], 200)
        self.assertEqual((await request(guard, peer="192.0.2.2"))[0], 200)

    async def test_admin_requires_origin_password_and_bearer_token(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = AdminManager(
                hash_password("strong-test-password"),
                Path(directory) / "manual-refresh.request",
                Path(directory) / "crawl_status.json",
            )
            previous = app.state.admin_manager
            app.state.admin_manager = manager
            try:
                login_body = json.dumps({"password": "strong-test-password"}).encode()
                base_headers = ((b"content-type", b"application/json"),)
                status, _, _ = await request(
                    app, "/api/admin/login", method="POST", body=login_body,
                    extra_headers=base_headers,
                )
                self.assertEqual(status, 403)

                headers = (*base_headers, (b"origin", b"https://testserver"))
                status, _, _ = await request(
                    app, "/api/admin/login", method="POST",
                    body=b'{"password":"incorrect"}', extra_headers=headers,
                )
                self.assertEqual(status, 401)

                status, response_headers, response_body = await request(
                    app, "/api/admin/login", method="POST", body=login_body,
                    extra_headers=headers,
                )
                self.assertEqual(status, 200)
                self.assertEqual(response_headers[b"cache-control"], b"no-store")
                token = json.loads(response_body)["token"]

                status, _, _ = await request(app, "/api/admin/refresh", method="POST")
                self.assertEqual(status, 403)
                auth_headers = (*headers, (b"authorization", f"Bearer {token}".encode()))
                status, _, _ = await request(
                    app, "/api/admin/refresh", method="POST", extra_headers=auth_headers,
                )
                self.assertEqual(status, 202)
                self.assertTrue(manager.marker.exists())
                status, response_headers, _ = await request(
                    app, "/api/admin/refresh", method="POST", extra_headers=auth_headers,
                )
                self.assertEqual(status, 429)
                self.assertIn(b"retry-after", response_headers)
                status, response_headers, _ = await request(
                    app, "/api/admin/status", extra_headers=((b"authorization", f"Bearer {token}".encode()),),
                )
                self.assertEqual(status, 200)
                self.assertEqual(response_headers[b"cache-control"], b"no-store")
            finally:
                app.state.admin_manager = previous

    async def test_admin_body_is_bounded(self):
        status, _, _ = await request(
            app, "/api/admin/login", method="POST", body=b"x" * 1100,
        )
        self.assertEqual(status, 413)

    async def test_admin_posts_have_separate_concurrency_cap(self):
        started = asyncio.Event()
        release = asyncio.Event()
        active = 0

        async def slow_admin(scope, receive, send):
            nonlocal active
            active += 1
            if active == 2:
                started.set()
            await release.wait()
            await cheap_app(scope, receive, send)

        guard = ResourceGuardMiddleware(slow_admin, max_concurrent=10)
        first = asyncio.create_task(request(guard, "/api/admin/login", method="POST"))
        second = asyncio.create_task(request(guard, "/api/admin/login", method="POST"))
        await started.wait()
        status, _, _ = await request(guard, "/api/admin/login", method="POST")
        self.assertEqual(status, 503)
        release.set()
        self.assertEqual((await first)[0], 200)
        self.assertEqual((await second)[0], 200)


class AdminCredentialTests(unittest.TestCase):
    def test_password_file_and_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "admin.env"
            password = write_password_file(path)
            self.assertIsNotNone(password)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            encoded = path.read_text().strip().split("=", 1)[1]
            self.assertTrue(verify_password(password, encoded))
            self.assertFalse(verify_password("wrong", encoded))
            self.assertIsNone(write_password_file(path))
            rotated = write_password_file(path, rotate=True)
            self.assertNotEqual(password, rotated)
            self.assertTrue(verify_password(rotated, path.read_text().strip().split("=", 1)[1]))

    def test_login_rate_limit_and_logout(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = AdminManager(hash_password("correct"), Path(directory) / "request", Path(directory) / "status")
            for _ in range(5):
                self.assertEqual(manager.login("wrong")[0], 401)
            self.assertEqual(manager.login("correct")[0], 429)
            manager._failures.clear()
            status, token = manager.login("correct")
            self.assertEqual(status, 200)
            self.assertTrue(manager.authorized(token))
            manager.logout(token)
            self.assertFalse(manager.authorized(token))

    def test_admin_origin_restrictions(self):
        self.assertTrue(valid_admin_origin("https://aiprice.example", "aiprice.example"))
        self.assertFalse(valid_admin_origin("http://aiprice.example", "aiprice.example"))
        self.assertFalse(valid_admin_origin("https://evil.example", "aiprice.example"))
        self.assertTrue(valid_admin_origin("http://localhost:5173", "127.0.0.1:8000"))

    def test_crawler_status_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            with patch.object(run_all, "DATA_DIR", data_dir):
                run_all.write_status("running", "2026-09-24T00:00:00+00:00")
                run_all.write_status("success", "2026-09-24T00:00:00+00:00", [
                    {"platform": "chatgpt", "status": "✅ success", "plans": 2, "price_changed": 0}
                ])
            saved = json.loads((data_dir / "crawl_status.json").read_text())
            self.assertEqual(saved["state"], "success")
            self.assertEqual(saved["platforms"][0]["platform"], "chatgpt")
            self.assertIsNotNone(saved["finished_at"])


class CrawlerBoundaryTests(unittest.TestCase):
    def test_gemini_only_fetches_expected_google_script_urls(self):
        html = (
            '<script src="https://127.0.0.1/about/assets/d/private.js"></script>'
            '<script src="//example.com/about/assets/d/foreign.js"></script>'
            '<script src="/about/assets/d/pricing.js"></script>'
        )

        class FakeResponse:
            status_code = 200

            def __init__(self, text):
                self.text = text

            def raise_for_status(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def iter_content(self, chunk_size):
                yield b'const feed="pricing_2026_08_01.json"'

        class FakeSession:
            def __init__(self):
                self.urls = []

            def get(self, url, **kwargs):
                self.urls.append(url)
                return FakeResponse(html if len(self.urls) == 1 else "")

        crawler = GeminiPricingCrawler(country_code="TW")
        crawler.session = FakeSession()
        self.assertEqual(crawler._discover_feed_filename(), "pricing_2026_08_01.json")
        self.assertEqual(
            crawler.session.urls,
            [crawler.plans_page_url, "https://one.google.com/about/assets/d/pricing.js"],
        )


if __name__ == "__main__":
    unittest.main()
