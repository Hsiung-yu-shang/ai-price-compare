"""Exercise the public ASGI surface without binding a network port."""

import asyncio
import unittest

from api.main import app
from api.security import ResourceGuardMiddleware
from crawlers.gemini_crawler import GeminiPricingCrawler


async def request(
    target, path="/", method="GET", peer="192.0.2.1", extra_headers=(), query=b""
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
        return {"type": "http.request", "body": b"", "more_body": False}

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
