# NOTES

**No measurements have been taken yet.** Everything below is a template —
headings and the exact commands to run — waiting to be filled in against a
real deployment with a real `DIGITAL_OCEAN_MODEL_ACCESS_KEY`. The
deployment config and docs were written without a key or a DigitalOcean
account to hand, so none of it has been exercised. Nothing here should be
read as a result until someone has actually run the commands and replaced
the blanks.

Log friction the moment it happens, with a timestamp. This is the raw
material for the write-up's verdict section, and it can't be reconstructed
after the fact — two days later the irritation is gone and so is the
specific detail that made it worth writing down.

---

## Concurrency verification

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

> Caveat for whoever runs this: `app.py` has no module-level
> `app` object (see the Procfile note below), so
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
up as claimed? If the naive config didn't actually stall the way it was
expected to, say that here — the write-up gets built from whatever this
file actually says, not from what was predicted.)

---

## Deploy to App Platform

Log anything that cost more than five minutes: confusing docs, unclear
error messages, build failures, env var gotchas, health check behavior,
anything else. Timestamp each entry — this is the raw material for the
write-up's verdict section and can't be reconstructed after the fact.

Steps:

1. Fork this repo to `oceanforge/inference-shootout` (or push this branch
   there if the org repo already exists) and make sure the branch App
   Platform will track has the deploy config: `.do/app.yaml`, `Procfile`,
   `requirements.txt` / equivalent.
2. In the DigitalOcean control panel: **Create → Apps → From Source Code**,
   point it at `oceanforge/inference-shootout`, and let it pick up
   `.do/app.yaml` (or import it explicitly if the UI doesn't autodetect —
   note which one happened).
3. Before the first deploy completes, set `DIGITAL_OCEAN_MODEL_ACCESS_KEY`
   as an app-level environment variable with scope **Encrypted** (not
   plaintext, not a build-time var). Confirm in the UI that it shows as
   `SECRET`/encrypted after saving.
4. Let the build and deploy run. Hit the deployed URL's `/` and confirm the
   page loads, then run one manual race from the browser to confirm the
   key actually works end to end before moving to the billing alert.

**Timestamp / entry log (fill in as it happens):**
-
-
-

**Anything that didn't match this runbook (repo already existed under a
different name, `.do/app.yaml` needed hand edits, health check failed on
first deploy, etc.):**
-

---

## Billing alert

**Why this matters, explicitly:** `guards.py`'s `RateLimiter` and
`DailyBudget` are deliberately in-memory — no Redis, no database, per the
comment at the top of that file. Both live in one process's memory, which
means both **reset to zero on every redeploy** (and on every worker
restart). They cannot be trusted as the only spend control for a
publicly-linked demo that gets redeployed more than once. A DigitalOcean
billing alert is the only guard that survives a redeploy, so it is not
optional polish — it's the actual backstop.

Steps: DigitalOcean control panel → **Billing → Alerts** (or **Settings →
Billing** depending on current UI) → add a spend alert. Set the threshold
low enough that it would actually catch a stuck/looping demo before it
became a real bill — this app calls a metered inference endpoint per
token streamed, so a stale/duplicate stream (see the known issue logged
under Browser checks below) can run up cost quietly.

**Threshold set, and when:**
-

**Notification channel confirmed working (test alert or equivalent):**
-

---

## Browser checks (need a running app)

These came out of reading the code, not out of running it, so none of them
are confirmed. Check each against the real deployed app and record what
you actually saw — don't just tick the box.

- [ ] **Columns start together and interleave.** Load the page, kick off a
  race across all default models, and watch whether the columns genuinely
  begin streaming at roughly the same time and interleave tokens as they
  arrive, rather than one column filling completely before the next one
  starts. Record what you saw:
  -

- [ ] **Resubmitting "Run" mid-race does not leave stale state.** Start a
  race, then click Run again before it finishes (with a different or the
  same prompt). Check whether old columns are cleared cleanly and whether
  the earlier run's requests are still going in the background (browser
  devtools Network tab, filter on `/stream`, look for EventSource
  connections from the previous click still open/receiving data).

  **Known issue, logged here on purpose so it isn't lost:** `race()` in
  `templates/index.html` creates a fresh `EventSource` per model on every
  call but never closes the *previous* set — the only place an
  `EventSource` gets `close()`d is inside its own `done` handler, when
  that particular stream finishes on its own. If `race()` is invoked again
  before the prior run's streams have all reached `done`, the old
  `EventSource`s are simply orphaned (no reference kept, no `close()`
  called) and keep receiving — and keep the server-side generator running,
  which keeps consuming paid tokens — until they self-close. This should
  be treated as **worth fixing before the demo goes public**, e.g. by
  tracking open `EventSource`s in a module-level array and closing them
  all at the top of `race()`. Confirm live whether this actually happens
  (it should be visible as duplicate/overlapping network activity after a
  fast resubmit) and record it:
  -

- [ ] **Unpriced models show an em dash, never `$0.00`.** Confirm that for
  a model with no entry in the price table, the results row renders `—`
  in the cost column (this matches `d.cost_usd == null ? '—' : ...` in
  `templates/index.html`) and never `$0.00`, which would misleadingly
  imply the run was free. Record what you saw:
  -

- [ ] **Results table is usable on a real narrow viewport.** Load the app
  on an actual phone or with devtools responsive mode at a real mobile
  width (~375px), run a race, and check whether the results table is
  readable — not clipped, not requiring horizontal scroll to see the cost
  column, text not overlapping. Record what you saw:
  -

---

## The measurement set

Three prompt shapes — short factual, long-form explanation, code
generation — across the six default models, three runs each (54 rows
total). Record region and wall-clock time of day for the whole set, since
DigitalOcean inference latency can vary by both.

**Three runs is not statistical significance.** The write-up must say so
plainly and not imply otherwise — no error bars presented as if they mean
more than "here's the spread across three tries," no claims of a model
being "faster" from a difference that could just as easily be noise at
n=3.

**Region:**
**Wall-clock time of day / date (start–end):**

### Short factual prompt

Prompt used:

| Model | Run | TTFT (ms) | Total (ms) | Output tokens | Est. cost (USD) |
| --- | --- | --- | --- | --- | --- |
| | 1 | | | | |
| | 2 | | | | |
| | 3 | | | | |

### Long-form explanation prompt

Prompt used:

| Model | Run | TTFT (ms) | Total (ms) | Output tokens | Est. cost (USD) |
| --- | --- | --- | --- | --- | --- |
| | 1 | | | | |
| | 2 | | | | |
| | 3 | | | | |

### Code generation prompt

Prompt used:

| Model | Run | TTFT (ms) | Total (ms) | Output tokens | Est. cost (USD) |
| --- | --- | --- | --- | --- | --- |
| | 1 | | | | |
| | 2 | | | | |
| | 3 | | | | |

(Duplicate the model rows for all six default models within each table
above before filling in.)

---

## Assets captured

- [ ] `docs/screenshot.png` — the settled results table (after a race has
  finished, not mid-stream).
- [ ] `docs/race.gif` — screen recording of one run, columns filling at
  visibly different speeds. This is the hero asset for X and daily.dev, so
  it should actually show the race — pick a prompt/model mix where the
  speed difference between columns is visible, not one where every column
  finishes at nearly the same instant.

Neither file should exist in the repo until it's a capture of a real run.

---

## Then and only then: the writing

`docs/blog-post.md` and `docs/community-answer.md` get written **from
this file's contents**, once the sections above are actually filled in —
not before, and not from the plan or the spec's predictions. Specifically:

- The blog post's verdict section is built from the "Concurrency
  verification" section above and the measurement set, whatever they
  actually say — including if the naive sync-worker config didn't stall
  the way the spec predicted.
- **The community answer's topic depends on what actually went wrong.**
  It was planned around the gunicorn concurrency stall reproducing
  cleanly. If Concurrency verification's part A does *not* reproduce a
  stall, the community answer does not get forced into that shape anyway
  — it gets written about whatever real problem this log did turn up
  instead (the stale-`EventSource`-on-resubmit issue logged above is one
  candidate if nothing else surfaces, but only if it's confirmed live,
  not assumed from the code read).
- Do not draft either doc until the relevant sections above have real
  entries, not blanks.

---

## Open questions / follow-ups

-
