# Concurrent streaming responses queue up on App Platform instead of overlapping

**Problem:** you have a Python app on App Platform that streams responses.
Server-Sent Events, chunked responses, an LLM proxy, anything long-lived.
Alone it's fine. Open several at once from the same page and they stop
overlapping. First one finishes, then the second starts, then the third.
With six concurrent streams the last one doesn't produce a byte for nine
seconds.

Nothing errors. That's the part that makes this hard to spot, and it's why
I spent an hour blaming the upstream API before I looked at my own server.

## What's happening

gunicorn's default worker is `sync`. A sync worker takes one connection
per process and holds it until the response is finished, which for normal
requests lasting 40 milliseconds is completely fine and something you will
never once think about, but a streaming response stays open for its entire
life, maybe ten seconds, maybe a minute, and for all of that time it is
sitting on a whole worker while everything else queues up behind it
waiting for a turn.

They don't fail. They queue.

## Confirming it

Naive config, six concurrent streams:

```bash
gunicorn --workers 1 --bind 0.0.0.0:8080 'myapp:create_app()' &
for i in 1 2 3 4 5 6; do
  curl -sN "http://localhost:8080/stream?n=$i" &
done; wait
```

Time to first byte per stream, measured on a real app:

```
stream 1   1250 ms
stream 2   5326 ms
stream 3   7278 ms
stream 4   8347 ms
stream 5   9147 ms
```

The tell is the even spacing. Each stream's first byte lands right about
when the one before it finished, which is not what slow upstreams look
like at all, because slow upstreams give you a cluster of roughly similar
times rather than a staircase where every step is exactly one response
tall. If you see the staircase, it's a queue.

## Fix

Threaded workers:

```
web: gunicorn --worker-class gthread --threads 16 --timeout 120 --bind 0.0.0.0:8080 'myapp:create_app()'
```

Same app, same load:

```
stream 1   1005 ms
stream 2   1084 ms
stream 3   1566 ms
stream 4   2367 ms
```

Four first bytes inside a 1.4 second window rather than strung out across
ten, and total wall clock drops from 10.7 s to 6.4 s.

Set `--threads` to cover the concurrent streams you expect, plus room.
They're cheap. Streaming threads spend nearly all their time blocked on
I/O, so 16 is a sane starting number even on a small instance. Push
`--timeout` past your longest expected stream while you're there, because
otherwise gunicorn kills the worker halfway through a response and you've
swapped one confusing bug for another one.

`gevent` works, and so does `uvicorn` if your app is async. `gthread` is
just the smallest diff if you're on synchronous Flask or Django.

## Why local testing misses it

`flask run` and `app.run()` are threaded by default. Which means your
streams overlap perfectly on your laptop, behave themselves through code
review, and then serialize the moment they're behind gunicorn in
production, which is roughly the worst available place to learn this. Test
concurrency against the same command your `Procfile` uses. Not the dev
server.

## Two App Platform specifics

If you don't give it a `Procfile`, the Python buildpack will pick a start
command for you, and it won't be tuned for streaming. Commit one so the
worker class is a decision you made.

Also, if you use an application factory, the target needs the parentheses:
`'myapp:create_app()'`, not `myapp:app`. Get that wrong and you get
`Failed to find application object`, which sounds like a completely
different problem and will send you off debugging your imports.

---

Numbers above are from a real App Platform deploy in `nyc`, measured while
building a small open-source app that streams several LLM responses side
by side. Code, if it's useful:
[github.com/oceanforge/inference-shootout](https://github.com/oceanforge/inference-shootout)
