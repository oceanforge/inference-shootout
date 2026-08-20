# Contributing

Issues and PRs welcome.

## Set up

```bash
git clone https://github.com/oceanforge/inference-shootout.git
cd inference-shootout

python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
```

No API key needed for development. The test suite runs entirely against a
fake OpenAI-shaped client (`tests/conftest.py`) — no network calls, no key,
deterministic timing.

## Run the checks

```bash
pytest -v
ruff check .
```

CI (`.github/workflows/ci.yml`) runs the same two commands on every push
and PR. Both must pass before merge.

## pre-commit

This repo uses [pre-commit](https://pre-commit.com/) to run ruff (lint +
format) before each commit — the same check CI enforces, so failures show
up locally instead of in CI. Enable it once after cloning:

```bash
pip install pre-commit
pre-commit install
```

## Opening a PR

- Keep `app.py` readable — it's meant to be read in one sitting; if a
  change grows it substantially, consider whether it belongs in
  `guards.py`, `inference.py`, or `pricing.py` instead.
- Add a line to `CHANGELOG.md` for any user-facing change.
- The [PR template](.github/PULL_REQUEST_TEMPLATE.md) checklist
  (`pytest`, `ruff check .`, no secrets in the diff) is the bar for review.
