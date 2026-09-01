<!-- DigitalOcean Community Q&A — SELF-ANSWER
     Post as an answer to your own question, then mark it accepted. -->

Answering my own question, since I worked it out and the search results
that would have saved me an hour didn't exist.

Not App Platform. Not the upstream. It was gunicorn's default worker.

## Cause

gunicorn defaults to the `sync` worker. That worker handles **one
connection per process** and holds it until the response is finished,
which for ordinary requests lasting 40 ms is completely fine and something
you will never once think about, but a streaming response stays open for
its entire life, so each open stream sits on a whole worker for ten
seconds, a minute, however long it runs, while everything else waits its
turn in line behind it.

The requests don't fail. They queue.

That's why the timings look like a staircase. Each stream's first byte
arrives right about when the previous one finished. Slow upstreams give
you a cluster of roughly similar times instead, so the even spacing is the
thing to look for.

## Fix

Threaded workers, in the `Procfile`:

```
web: gunicorn --worker-class gthread --threads 16 --timeout 120 --bind 0.0.0.0:8080 'myapp:create_app()'
```

Same app, same six concurrent streams, after the change:

```
stream 1   1005 ms
stream 2   1084 ms
stream 3   1566 ms
stream 4   2367 ms
```

Four first bytes inside a 1.4 second window rather than strung across ten,
and total wall clock went from 10.7 s to 6.4 s.

Notes on the flags:

- `--threads` should cover the concurrent streams you expect, with room on
top. They are cheap. Streaming threads sit blocked on I/O almost the whole
time, so 16 is a reasonable start even on a small instance.
- `--timeout` needs to be longer than your longest expected stream.
  Otherwise gunicorn kills the worker mid-response and you've traded one
  confusing bug for another.

`gevent` also works, and `uvicorn` if your app is async. `gthread` is just
the smallest change for synchronous Flask or Django.

## Why local testing missed it

`flask run` and `app.run()` are threaded by default. Which means the
streams overlap perfectly on your laptop, sail through review, and then
serialize the moment they are behind gunicorn in production, which is
about the worst available place to learn this. Test against the same
command your `Procfile` uses. Not the dev server.

## Two App Platform specifics

If you don't commit a `Procfile`, the Python buildpack picks a start
command for you and it won't be tuned for streaming. Commit one so the
worker class is a decision you made rather than a default you inherited.

Also, if you use an application factory, the target needs the parentheses:
`'myapp:create_app()'`, not `myapp:app`. Getting that wrong gives you
`Failed to find application object`, which reads like an import problem
and sends you off in the wrong direction entirely.

---

Numbers above are from a real App Platform deploy in `nyc`, measured while
building a small open-source app that streams several model responses side
by side: https://github.com/oceanforge/inference-shootout
