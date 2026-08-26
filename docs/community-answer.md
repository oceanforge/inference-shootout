# Why concurrent streaming responses appear to hang on App Platform

**Problem:** you have a Python app on DigitalOcean App Platform that
streams responses — SSE, chunked responses, an LLM proxy, anything
long-lived. It works fine when you test it alone. As soon as the page
opens several streams at once, they stop overlapping: the first finishes,
then the second starts, then the third. With six concurrent streams the
last one starts nine seconds in.

Nothing errors. That's what makes it hard to spot.

## Cause

gunicorn's default worker (`sync`) handles **one connection per worker
process** and holds it until the response completes. That's fine for
ordinary requests measured in milliseconds. A streaming response is held
open for its entire lifetime — seconds, sometimes minutes — so each open
stream occupies a whole worker for its full duration.

Concurrent streams therefore queue. They don't fail, they don't time out,
they just wait their turn.

## Reproducing it

Naive config, six concurrent streams:

```bash
gunicorn --workers 1 --bind 0.0.0.0:8080 'myapp:create_app()' &
for i in 1 2 3 4 5 6; do
  curl -sN "http://localhost:8080/stream?n=$i" &
done; wait
```

Measured on a real app, time-to-first-byte per stream:

```
stream 1   1250 ms
stream 2   5326 ms
stream 3   7278 ms
stream 4   8347 ms
stream 5   9147 ms
```

The signature is the **even stagger** — each stream's first byte arrives
about when the previous one finished. If your timings look like that, it's
serialization, not slow upstreams.

## Fix

Use threaded workers:

```
web: gunicorn --worker-class gthread --threads 16 --timeout 120 --bind 0.0.0.0:8080 'myapp:create_app()'
```

Same load, same app:

```
stream 1   1005 ms
stream 2   1084 ms
stream 3   1566 ms
stream 4   2367 ms
```

Four of the first bytes now land inside a 1.4-second window instead of
across a ten-second one, and wall clock drops from 10.7 s to 6.4 s.

Pick `--threads` to cover your expected concurrent streams with headroom.
Streaming threads are mostly blocked on I/O, so they're cheap; 16 is a
reasonable starting point for a small instance. Raise `--timeout` above
your longest expected stream, or gunicorn will kill workers mid-response.

`gevent` or `uvicorn` with an async framework also solve it. `gthread` is
the smallest change if your app is synchronous Flask or Django.

## Why you probably won't catch this locally

`flask run` and `app.run()` in debug mode are threaded by default, so
concurrent streams overlap correctly on your laptop and serialize only in
production. Test streaming concurrency against the same gunicorn command
your `Procfile` uses, not the dev server.

## One App Platform detail

App Platform's buildpack will start your app for you if you don't specify,
and the default won't be tuned for streaming. Commit an explicit
`Procfile` so the worker class is yours to control rather than inherited.

Also: if you use an app factory, the target is `'myapp:create_app()'` with
the parentheses, not `myapp:app`. A missing module-level `app` object
fails with `Failed to find application object`, which reads like a
different problem entirely.

---

Measured while building a small open-source app that streams several LLM
responses side by side; numbers above are from a real run on App Platform
in `nyc`. Code, if useful:
[github.com/oceanforge/inference-shootout](https://github.com/oceanforge/inference-shootout)
