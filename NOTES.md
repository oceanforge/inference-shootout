# NOTES

**No measurements have been taken yet.** Everything below is a template —
headings and the exact commands to run — waiting to be filled in against a
real deployment with a real `DIGITAL_OCEAN_MODEL_ACCESS_KEY`. Task 7
(deployment config and docs) could not run any of this: it had neither a
model access key nor a DigitalOcean account available. Nothing in this file
should be read as a result until someone has actually run the commands and
replaced the blanks.

Per the design spec (`docs/superpowers/specs/2026-08-20-inference-shootout-design.md`,
section 11): log friction the moment it happens, with a timestamp. This is
the raw material for the write-up's verdict section and can't be
reconstructed after the fact.

---

## Concurrency verification (design spec section 4 / task 8, step "verify the concurrency claim")

The claim under test: the default gunicorn sync worker holds one connection
per worker, so N concurrent SSE streams will starve the pool and the page
will appear to hang, and the `Procfile`'s threaded (`gthread`) workers fix
it.

Run **both** halves against a real deployment (or locally with a real key)
and record what actually happens for each. If the naive config does *not*
stall, say so plainly below — do not write up a problem that wasn't
observed.

### A. Naive config — sync worker, single worker process

This is the brief's reproduction command, verbatim:

```bash
gunicorn --workers 1 --bind 0.0.0.0:8080 app:app &
for i in 1 2 3 4 5 6; do
  curl -sN "http://localhost:8080/stream?model=openai-gpt-oss-20b&prompt=count+to+twenty" &
done; wait
```

> Caveat for whoever runs this: as of task 7, `app.py` has no module-level
> `app` object (see the Procfile / controller ruling R3 note below), so
> `app:app` will not resolve at all — gunicorn will fail to boot with
> "Failed to find application object 'app' in 'app'" before any of the
> curls even run. To reproduce the *actual* naive-sync-worker stall, swap
> the target for the factory call used everywhere else in this repo:
> `gunicorn --workers 1 --bind 0.0.0.0:8080 'app:create_app()'`. Note this
> down if that's what you had to do.

**Observed (fill in):**
-
-
-

**Did it stall?**
- [ ] Yes — describe how it presented (hung curls? connection refused?
      timeout? which request(s)?) and how long it took to recover:
- [ ] No — describe what actually happened instead:

### B. Procfile config — threaded workers

Same load, against the app started the way `Procfile` starts it in
production:

```bash
gunicorn --worker-class gthread --threads 16 --timeout 120 --bind 0.0.0.0:8080 'app:create_app()' &
for i in 1 2 3 4 5 6; do
  curl -sN "http://localhost:8080/stream?model=openai-gpt-oss-20b&prompt=count+to+twenty" &
done; wait
```

**Observed (fill in):**
-
-
-

**Did all six streams complete without stalling?**
- [ ] Yes
- [ ] No — describe what happened:

### Verdict

(Fill in once both halves have been run: does the threaded-worker fix hold
up as claimed? If the naive config didn't actually stall the way the spec
assumed, say that here — the write-up's section 3 gets built from whatever
this file actually says, not from the spec's prediction.)

---

## Deploy friction (task 8, step 1 — App Platform deploy)

Log anything that cost more than five minutes: confusing docs, unclear
error messages, build failures, env var gotchas, health check behavior,
anything else.

**Timestamp / entry:**
-

---

## Billing alert (task 8, step 2)

Record the alert threshold set and when:

-

---

## Measurement set (task 8, step 3)

Three prompt shapes (short factual, long-form explanation, code
generation) across the default six models, three runs each. Record region
and wall-clock time of day alongside each run. Three runs is not
statistical significance — the write-up must say so, not imply otherwise.

Suggested table per prompt shape:

| Model | Run | TTFT (ms) | Total (ms) | Output tokens | Est. cost (USD) |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

**Region:**
**Time of day / date:**

---

## Assets captured (task 8, step 4)

- [ ] `docs/screenshot.png` — settled results table
- [ ] `docs/race.gif` — one run, columns filling at visibly different speeds

---

## Open questions / follow-ups

-
