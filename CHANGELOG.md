# Changelog

## v1.0.0
- Sync of all ads and daily stats from the Telegram Ads API, hourly.
- Rules with proposals: withdraw idle budget, stop expensive ads (28-day and lifetime), top up good ads, refresh tired ads.
- Approval-based execution queue: pause, 11-minute wait, withdraw, top-up; idempotency keys, per-ad and daily top-up caps, pause-all switch.
- New ads with tracking links (`?start=code`), text library and balanced A/B assignment.
- Purchase tracking via API and CSV; cost per customer per ad and per text.
- Export bundle for analysis with Claude; optional Claude API analysis.
- Persian RTL web panel with Shamsi dates.
- One-line installer and `psychonet-ads` management command (update, rollback, backup, restore).
