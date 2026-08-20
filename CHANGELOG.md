# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08-20

### Added

- Race a prompt across multiple DigitalOcean-hosted models concurrently,
  streamed side by side over Server-Sent Events (`/stream`).
- Live model catalog fetched from the inference endpoint at boot
  (`GET /api/models`) — never hardcoded, so a retired model degrades to
  "not selected" instead of a crash.
- Per-run metrics: time-to-first-token, total duration, output tokens, and
  estimated cost, computed from `prices.json` with separate input/output
  rates.
- Cost estimates render an em dash for any model missing from
  `prices.json`, never a fabricated `$0.00`.
- Per-IP rate limiting (`RATE_LIMIT_PER_MINUTE`) and a daily spend ceiling
  (`DAILY_BUDGET_USD`), both in-memory and disableable by setting either to
  `0`.
- Server-side enforcement of `MAX_MODELS_PER_RUN` and `MAX_OUTPUT_TOKENS`,
  independent of whatever the client sends.
- `Procfile` configured with threaded gunicorn workers
  (`--worker-class gthread --threads 16`), required because the SSE fan-out
  opens multiple concurrent long-lived connections per page load and the
  default sync worker would starve under that load.
- `.do/app.yaml` App Platform spec, pinned to `instance_count: 1` since the
  spend guards are per-process.
- Test suite (`tests/`) covering the SSE event sequence, guard enforcement,
  pricing fallbacks, and catalog selection, run entirely against a fake
  client with no network calls.

[0.1.0]: https://github.com/oceanforge/inference-shootout/releases/tag/v0.1.0
