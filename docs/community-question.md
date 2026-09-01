<!-- DigitalOcean Community Q&A — QUESTION
     Post at: https://www.digitalocean.com/community/questions/new
     Tags: App Platform, Python, Deployment -->

TITLE
=====
Concurrent SSE streams run one after another on App Platform instead of overlapping

BODY
====
I have a Python (Flask) app on App Platform that streams responses over
Server-Sent Events. The page opens several streams at once, one per
upstream call, and renders them side by side as they arrive.

One stream on its own is fine. As soon as the page opens six at once they
stop overlapping. The first finishes, then the second starts, then the
third. The last stream doesn't produce a byte until about nine seconds in.

Nothing errors. Every request returns a correct, complete response. No
timeouts, no 5xx, nothing in the logs. It just looks like the upstream is
slow, which is where I wasted an hour.

Time to first byte, six concurrent requests:

```
stream 1   1250 ms
stream 2   5326 ms
stream 3   7278 ms
stream 4   8347 ms
stream 5   9147 ms
```

Locally with `flask run` the same page works perfectly and all six
overlap, so I didn't catch it until it was deployed.

What I'm running on App Platform is the Python buildpack with a `Procfile`:

```
web: gunicorn --bind 0.0.0.0:8080 'myapp:create_app()'
```

Is this an App Platform limit on concurrent connections, or something in
my own setup? Scaling to more instances feels like the wrong fix for six
requests.
