<!-- DigitalOcean Community post, same shape as the spaces-gallery one:
     a short framing post, then the real content as your own answer.
     Post at https://www.digitalocean.com/community/questions/new
     Tags: DigitalOcean App Platform, App Platform, AI/ML -->

TITLE
=====
Comparing model latency and cost on DigitalOcean Inference before you commit to one

POST BODY
=========
Every time I put a model behind an endpoint I make the same lazy decision.
I pick whatever I used last time, or whatever I read about most recently,
and I tell myself I'll benchmark it properly later. I never do.

So I built the thing that would make me do it: one prompt, fired at six
models at once, streaming side by side in columns, with time to first
token and cost per run underneath each one. It's Flask, about 390 lines,
no Dockerfile, and it deploys to App Platform on push. The code is on
GitHub under MIT: oceanforge/inference-shootout.

What I want to walk through here isn't really the app. It's the three
things that only showed up once I ran it against the live endpoint, none
of which I would have learned from reading the docs. If you're picking a
model for something right now, two of them will probably save you an
afternoon.


ANSWER (post as your own answer, then mark accepted)
====================================================

## The integration is two lines, and that's the boring part

DigitalOcean's inference endpoint speaks OpenAI, so the entire
provider-specific surface area of the app is this:

```python
client = OpenAI(
    base_url="https://inference.do-ai.run/v1/",
    api_key=os.environ["DIGITAL_OCEAN_MODEL_ACCESS_KEY"],
)
```

Every model below goes through that one client. Llama, DeepSeek, Mistral,
Qwen, OpenAI's open-weight gpt-oss line. Only the model string changes.
That is genuinely the pitch, and comparing four providers normally means
four SDKs, four keys and four invoices, so it is worth something. It is
also the least interesting thing I learned.

One thing to get right before you paste that: the credential is a **model
access key**, made under the Gradient AI Platform, not the API token from
Settings. Different object, different page.

## The catalog lists models your account can't call

The app builds its model picker from `GET /v1/models`, because hardcoding
a model list is how you end up shipping a dead one.

That call returned 72 models. My account could call six.

Everything from Anthropic, plus GPT-4o and o3, comes back with:

```
403 - {'error': {'message': 'this model is not available for your
subscription tier', 'type': 'forbidden_error'}}
```

Nothing in the `/v1/models` payload distinguishes them. No availability
flag, no tier field. You find out by calling it and reading the 403.

Which is how I shipped a broken default. My preselected list had
`anthropic-claude-haiku-4.5` in it, because it's in the catalog and it's
on the pricing page with a real per-token rate beside it. First live run,
that column went red. If you build a picker from that endpoint, assume
most of what comes back is unreachable and handle the 403 per model
rather than per page.

## Six concurrent streams need threaded workers

Worth knowing if you stream anything on App Platform, not just model
output.

gunicorn's default `sync` worker takes one connection per process and
holds it until the response finishes. Fine for a 40 ms request. A
streaming response stays open for its whole life, so six concurrent
streams sit on six workers, and with one worker they queue.

Time to first token, six streams, default config:

```
mistral-3-14B          1250 ms
openai-gpt-oss-120b    5326 ms
openai-gpt-oss-20b     7278 ms
deepseek-3.2           8347 ms
llama-4-maverick       9147 ms
```

Look at the spacing. Each stream's first token lands about when the
previous one finished. That's a queue, not slow models. The fix is one
line in the `Procfile`:

```
web: gunicorn --worker-class gthread --threads 16 --timeout 120 --bind 0.0.0.0:8080 'app:create_app()'
```

Same load, after: four of the six first tokens inside a 1.4 second window
instead of strung across ten, and wall clock down from 10.7 s to 6.4 s.

The reason I'm flagging it: nothing errors. Every request succeeds and
returns correct output. Ship the broken version and you'd conclude the
models are slow, never your own config. A hang would have been easier to
catch.

Two smaller App Platform notes. If you don't commit a `Procfile` the
buildpack picks a start command for you, and it won't be tuned for
streaming. And if you use an app factory the target needs the
parentheses, `'app:create_app()'`, not `app:app`, or you get `Failed to
find application object`, which reads like an import problem.

## What the numbers actually said

Three prompt shapes, six models, three runs each. 54 calls, max_tokens
512, `nyc` region. Medians:

```
model                  TTFT      total    cost         empty runs
mistral-3-14B          533 ms    3.3 s    $0.000108    0/9
llama-4-maverick       676 ms    17.9 s   $0.000362    0/9
deepseek-3.2           869 ms    5.4 s    $0.000416    0/9
openai-gpt-oss-20b     1792 ms   4.6 s    $0.000235    2/9
openai-gpt-oss-120b    4797 ms   16.7 s   $0.000367    0/9
qwen3.5-397b-a17b      9332 ms   32.0 s   $0.000995    7/9
```

Mistral 14B won on every axis I measured. Fastest to first token, fastest
overall, cheapest per run, and it answered every time. On this workload
the expensive options bought nothing, which is not what I expected going
in. Time to first token spread 17x across the six, so if a model is going
behind anything a person waits on, that gap decides whether the feature
works.

## The failure that doesn't look like a failure

Look at the last column again.

All 54 calls succeeded. No exceptions, no non-200s, no timeouts. Nine of
them returned no readable text at all and billed in full.

`qwen3.5-397b-a17b` did it seven times out of nine, while being the most
expensive model in the race and the slowest at 32 seconds. It's a
reasoning model. It spent 487 of its 512 token budget thinking, ran out
before writing a word of the answer, and streamed the thinking into
`delta.reasoning_content`, which is not part of the OpenAI schema and is
therefore invisible to any client reading `delta.content`:

```
completion_tokens: 512
reasoning_tokens:  487
content:           0 characters
```

You can pay full price for silence and have your monitoring call it a
success. Raise `max_tokens` and it does answer. The general version is
worse than my particular bug though: if your evaluation only watches
latency and status codes, it cannot see this failure at all. Check
`completion_tokens_details.reasoning_tokens` if you're putting a
reasoning model anywhere near a budget.

## Try it

The repo is github.com/oceanforge/inference-shootout. MIT, Flask, no
Dockerfile, deploys to App Platform from a fork with one encrypted
environment variable. `NOTES.md` has the raw build log including the parts
that went wrong, and `docs/measurements.json` has all 54 runs if you want
to argue with the numbers.

The whole experiment cost **$0.0185**. That reframed it for me: the reason
nobody measures this before picking a model isn't cost, and it isn't
really time either. It's that there's nothing sitting there ready to run.
So now there's one, and it takes your prompt rather than mine.
