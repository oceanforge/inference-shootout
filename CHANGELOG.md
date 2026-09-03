# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-09-03

### Fixed

- Silent billed responses were only detected when the provider reported
  `reasoning_tokens`, which is the same dependency that hid the failure in
  the first place. A provider that bills completion tokens without reporting
  a reasoning count left the same unexplained empty column. Detection now
  keys on `content_chars` against `output_tokens`, which holds whatever the
  cause turns out to be; `reasoning_tokens` only labels the cause when it is
  reported. Reported by Vinh Nguyen in the dev.to comments.

### Added

- `content_chars` in the `done` event, so "billed but returned nothing" is
  observable server-side and testable rather than inferred from the DOM.

## [0.2.0] - 2026-08-26

First run against the live endpoint. Everything here came from things that
only showed up once real traffic hit it.

### Added

- `reasoning_tokens` in the `done` event. Reasoning models stream their
  thinking in `delta.reasoning_content`, outside the OpenAI schema, so a
  client reading `delta.content` sees nothing; with a low `max_tokens`
  they can spend the whole budget thinking and return no answer while
  billing in full. Observed: qwen3.5-397b-a17b used 487 of 512 tokens
  reasoning in 7 of 9 runs. Such a column now explains itself rather than
  appearing broken.
- `docs/blog-post.md`, `docs/community-answer.md`, `docs/measurements.json`
  (all 54 measured runs), `docs/screenshot.png`, `docs/race.gif`.

### Fixed

- `DEFAULT_MODELS` contained `anthropic-claude-haiku-4.5`, which returns
  403 "not available for your subscription tier" on a standard account.
  The live catalog lists 72 models; 6 were callable. Nothing in the
  `/v1/models` response marks the difference. Replaced with
  `qwen3.5-397b-a17b`.

### Changed

- README no longer offers a hosted demo. One ran long enough to take the
  measurements, then was torn down — a shared demo answers someone else's
  question on someone else's account tier.

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
