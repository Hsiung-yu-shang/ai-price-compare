# Architecture

## Production topology

The production target is one small systemd-based LXC.

```text
Client
  │
  └── :18080
        │
        ▼
     FastAPI / Uvicorn (1 worker)
        ├── /             frontend/dist (Vue static build)
        ├── /api/*        REST API
        └── data/pricing.db (SQLite)

systemd timer ── daily ── scripts/run_all.py ── official pricing sources
```

One Uvicorn worker is intentional: the workload is small and SQLite writes should remain serialized. The frontend calls relative `/api` URLs, so direct IP access and a reverse proxy or Cloudflare Tunnel use the same build.

## Application layers

### Crawlers

Every platform crawler extends `BasePricingCrawler` and follows `fetch → parse → validate → run`.

- ChatGPT: anonymous pricing configuration endpoint with `curl_cffi` fallback.
- Gemini: discovers and reads the Google One pricing feed.
- Claude: parses the public pricing page, with explicitly labelled fallback values.
- Perplexity: parses the public pricing page, with explicitly labelled fallback values.

A failed crawl is logged but does not overwrite the last known good plans.

### Storage

SQLAlchemy models:

- `platforms`
- `plans`
- `plan_features`
- `price_history`
- `crawl_logs`

`storage/diff.py` performs upserts and writes a history row only when monthly or annual pricing changes. The database file lives at `/opt/ai-price-compare/data/pricing.db` in production and is preserved by repeat deployments.

### API

`api/main.py` provides read-only platform, plan, comparison, history and health endpoints. No public route launches crawlers. Comparison tiers retain both `platform_id` and `plan_id`; plan identifiers are not assumed to be globally unique. `api/security.py` bounds request rates, concurrency and response headers; interactive OpenAPI documentation is disabled by default.

### Frontend

Vue 3 renders two views:

- comparison matrix grouped by market tier;
- complete plan cards filterable by platform.

Both views support monthly/annual pricing and price-history dialogs. `npm run build` writes `frontend/dist`, which FastAPI mounts only after all API routes are registered.

## Deployment lifecycle

`deploy/install.sh` is idempotent for application updates:

1. installs OS packages;
2. synchronizes source into `/opt/ai-price-compare`;
3. preserves the production database and logs;
4. creates the virtualenv and builds Vue;
5. installs the web service and crawler timer with CPU/memory limits and a read-only application tree;
6. verifies `/api/health`.

The initial public price snapshot in the repository makes the site usable immediately. A crawler refresh is queued after installation, and the timer keeps it current afterward.
