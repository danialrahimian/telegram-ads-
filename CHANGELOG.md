# Changelog

## v2.0.0 — Telegram Ads Manager

A rebuild of the project as a multi-account Telegram Ads manager.

**New**
- Several Telegram Ads accounts, each with its own route (`/accounts/<slug>`), dashboard, ads, rules, texts, sales and Claude analysis.
- Connections are entered in the dashboard: Telegram Ads token and the sales-bot API (base URL, bot username, per-bot API key), each with a health check. Secrets are stored encrypted (Fernet) and never shown in full.
- Sales-bot integration ("VPN Bot — Admin API", subscription edition): bot stats, transactions and referral users. Per-ad sales attribution through referral tags (`?start=` invite links of separate referrer accounts) with cost per customer per ad, per tag and per text.
- Periodic sync per account with configurable intervals (ads/balance, daily stats, sales bot), exponential backoff, an immediate re-sync when credentials change, and a live "today" view; the dashboard polls every few seconds (configurable).
- Text library: manual editing with versioning, Claude analysis (score, strengths, issues) and rewrites that can be edited before saving; performance of each text.
- New React frontend: Vite, TypeScript, Tailwind v4, shadcn/ui (Radix), TanStack Query, Recharts; Persian RTL, Shamsi dates, dark mode, fully responsive (tables become cards on mobile).
- New backend layout: FastAPI with layered app (core, models, schemas, services, integrations, api/v1, workers), SQLAlchemy 2 async, Alembic migrations, Pydantic v2 settings, CSRF-protected session auth with login rate limiting.
- Installer renamed to `tgads` (`/opt/tgads`): asks only for a domain and a password, generates the session secret and encryption key, migrates v1 (`psychonet-ads`) automatically; new `tgads password` command; backups include the encryption key.
- Tests: pytest with mocked APIs, Playwright end-to-end tests (desktop and mobile, no horizontal overflow), Vitest unit tests, a stubbed installer test; CI builds and smoke-tests a multi-arch image.

**Removed**
- The CSV/API purchase import of v1 (replaced by the bot API) and the server-rendered templates.

## v1.0.0
- Sync of all ads and daily stats from the Telegram Ads API, hourly.
- Rules with proposals: withdraw idle budget, stop expensive ads, top up good ads, refresh tired ads.
- Approval-based execution queue with idempotency keys and top-up caps.
- New ads with tracking links, text library and A/B assignment.
- Export bundle for analysis with Claude; optional Claude API analysis.
- Persian RTL web panel; one-line installer and `psychonet-ads` command.
