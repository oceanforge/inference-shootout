---
title: "I raced six models against each other on DigitalOcean Inference. The cheapest one won."
published: false
tags: showdev, ai, python, digitalocean
canonical_url:
---

I keep having the same argument with myself. Some endpoint needs a model
behind it, and I have to pick one. And the honest basis for that decision
is usually: a benchmark someone else ran, on a prompt that isn't mine, six
months ago.

So I spent a weekend building the thing that answers it properly. One
prompt, fired at several models at once, streaming side by side, with time
to first token and cost per run underneath each column.

It's about 390 lines of Python. The code is
[on GitHub](https://github.com/oceanforge/inference-shootout), MIT, fork
it and point it at your own key.

This is what happened when I actually ran it.

## The integration is two lines and I want to be upfront that that's the boring part

DigitalOcean's inference endpoint is OpenAI-compatible, so:

```python
client = OpenAI(
    base_url="https://inference.do-ai.run/v1/",
    api_key=os.environ["DIGITAL_OCEAN_MODEL_ACCESS_KEY"],
)
```

That's the whole provider-specific surface area. No SDK, no adapter layer,
no per-provider request shaping. Every model in this post — Llama,
DeepSeek, Mistral, Qwen, OpenAI's open-weight `gpt-oss` line — goes
through that one client with nothing but the model string changing.

Which is genuinely the pitch, and it's also the least interesting thing I
learned. The interesting things all came from running it.

One thing worth flagging before you copy that snippet: the credential is a
**model access key**, made under the Gradient AI Platform, not a
DigitalOcean API token from Settings → API. They look similar and they are
not the same object. (Though — see below — the enforcement is looser than
the docs imply.)

## Racing them concurrently, without an event loop

Six models, six concurrent streams, six columns filling at once. The
obvious approach is one endpoint that fans out server-side and multiplexes
the responses back. I didn't do that.

Instead the browser opens **one `EventSource` per model**:

```
GET /stream?model=<id>&prompt=<text>
```

Each connection runs its own completion and streams its own tokens. No
merging, no shared buffer, no async orchestration. Flask stays
synchronous. The whole streaming path is about 40 lines.

The payoff is failure isolation, and I'll show you in a minute why that
turned out to matter far more than I expected.

## Where I lost an hour

Six concurrent SSE connections against gunicorn's default sync worker do
not work. I knew that going in — a sync worker holds one connection per
worker, and streaming connections are held open for their entire life.

What I got wrong was the symptom.

I predicted a hang. What actually happens is worse, because nothing looks
broken. First-token times across six concurrent streams, one worker:

| model | first token |
| --- | --- |
| mistral-3-14B | 1250 ms |
| openai-gpt-oss-120b | 5326 ms |
| openai-gpt-oss-20b | 7278 ms |
| deepseek-3.2 | 8347 ms |
| llama-4-maverick | 9147 ms |

Look at the stagger. Each stream's first token arrives roughly when the
previous one finished. That's serialization. Every request succeeded, no
timeouts, no errors, correct responses throughout — just one at a time,
10.7 seconds wall clock.

Same load with threaded workers:

```
web: gunicorn --worker-class gthread --threads 16 --timeout 120 'app:create_app()'
```

Four of the six first tokens now land inside a 1.4-second window instead
of marching across a ten-second one. Wall clock 6.4 s.

The reason I'm writing this down: if you shipped the sync-worker version,
you would not file a bug. Your page works. The columns fill in one after
another and you conclude the models are slow. An outright stall would have
been *easier* to catch, because a stall makes you look at your server.

## The catalog will lie to you

The app builds its model picker from `GET /v1/models`, because hardcoding
a model list is how you end up shipping a dead one.

That call returns **72 models**. My account can call **six**.

Every Anthropic model, plus GPT-4o and o3, returns:

```
403 - {'error': {'message': 'this model is not available for your
subscription tier', 'type': 'forbidden_error'}}
```

And nothing in the `/v1/models` payload distinguishes them. No `available`
flag, no tier field, nothing. The only way to find out a model is
off-limits is to call it and read the 403.

This bit me in the most embarrassing way possible: my own default model
list shipped with `anthropic-claude-haiku-4.5` in it, because it's in the
published catalog and on the pricing page. First real run, that column
went red.

It also accidentally justified the architecture. Because each column is
its own connection, the dead model showed its own 403 and the other five
kept streaming. I built that isolation for hypothetical failures. The
first real one arrived within a minute of first contact.

If you build a model picker from that endpoint — and DigitalOcean's docs
point you straight at it — assume most of what it returns is unreachable.

## A DigitalOcean API token works on the inference endpoint

Small thing, but it cost me a confused minute. The docs are firm that a
model access key and an API token are different credentials. They are. But
a `dop_v1_...` API token authenticates fine against
`inference.do-ai.run` — I tested it against both that and
`api.digitalocean.com/v2/account`, and it works on both.

Use the narrow one anyway. A leaked model access key costs you inference
spend. A leaked API token costs you the account.

## The numbers

Three prompt shapes — short factual, long explanation, code generation —
across six models, three runs each. 54 calls, `max_tokens=512`, `nyc`
region, one evening in August, run from a laptop in Europe.

Medians across all nine runs per model:

| model | TTFT | total | cost | runs with no text |
| --- | --- | --- | --- | --- |
| mistral-3-14B | **533 ms** | 3.3 s | **$0.000108** | 0/9 |
| llama-4-maverick | 676 ms | 17.9 s | $0.000362 | 0/9 |
| deepseek-3.2 | 869 ms | 5.4 s | $0.000416 | 0/9 |
| openai-gpt-oss-20b | 1792 ms | 4.6 s | $0.000235 | 2/9 |
| openai-gpt-oss-120b | 4797 ms | 16.7 s | $0.000367 | 0/9 |
| qwen3.5-397b-a17b | 9332 ms | 32.0 s | $0.000995 | **7/9** |

Three things.

**The cheapest model was also the fastest.** Mistral 14B: quickest to
first token, quickest overall, cheapest per run, and it answered every
time. There's no trade-off curve here to sit on. On this workload the
expensive options bought nothing.

**Time to first token spread 17x**, from 533 ms to 9.3 seconds. If you're
putting a model behind anything interactive, that difference is the
difference between usable and not, and you cannot guess it.

**And then look at the last column.**

## Zero errors, and nine runs that returned nothing

All 54 calls succeeded. No exceptions, no non-200s, no timeouts. A
benchmark measuring latency and error rate would report a flawless run.

Nine of those calls returned no readable text whatsoever, and billed in
full.

`qwen3.5-397b-a17b` did it seven times out of nine. It was also, by some
distance, the most expensive model in the race — roughly 9x Mistral — and
the slowest at 32 seconds. Thirty-two seconds, top of the bill, empty box.

It's a reasoning model. It spent 487 of its 512 token budget thinking, ran
out before writing a single word of answer, and streamed its reasoning in
`delta.reasoning_content` — a field that isn't in the OpenAI schema, so a
client reading `delta.content` (which is every OpenAI-compatible client,
including mine) sees precisely nothing.

```
completion_tokens: 512
reasoning_tokens:  487
content:           0 characters
```

You can pay full freight for silence, and your monitoring will call it a
success.

I patched the app to say so — a column with no content but non-zero
`reasoning_tokens` now explains itself instead of sitting there looking
broken. But the general lesson is bigger than my app: **if your evaluation
only looks at latency and status codes, it cannot see this failure.** You
have to look at the output. Which, it turns out, is the argument for
building a tool that puts the output next to the numbers in the first
place.

## What the whole thing cost

**$0.0185.** Eighteen tenths of a cent, for all 54 calls.

I spent longer reading the pricing page than the experiment cost to run.
That's the actual takeaway about picking models by measurement instead of
by reputation: at these prices, the reason nobody does it isn't cost.
It's that nobody's built the thing. So I built the thing.

## Would I use it

For picking a model for a specific job, yes — that's exactly what it's
for, and I now have opinions about Mistral 14B I didn't have on Friday.

The friction was real but small: a catalog that advertises models you
can't call, a credential distinction the docs enforce less strictly than
they describe, and a worker-config trap that any streaming app on any
provider would hit. None of that is specific to DigitalOcean except the
first, and the first is the one I'd most like to see fixed — an
`available` flag on `/v1/models` would take an afternoon and save everyone
that 403.

What I'd genuinely recommend is the one-key-one-URL part. Not because
it's clever, but because "compare four providers" normally means four
SDKs, four keys, four dashboards and four invoices, and here it meant
changing a string in a list.

**Caveats, stated plainly:** n=3, one region, one evening, one account
tier, one set of prompts. This is not a benchmark. It's one developer's
Tuesday. The point was never to publish authoritative numbers — it was to
make it cheap enough for you to get your own, on your prompts.

---

Code: **[github.com/oceanforge/inference-shootout](https://github.com/oceanforge/inference-shootout)**
· `NOTES.md` has the raw build log including the bits that went wrong,
and `docs/measurements.json` has all 54 runs.

Part of [oceanforge](https://github.com/oceanforge) — small
deploy-it-yourself apps for the DigitalOcean cloud. Not affiliated with
DigitalOcean; just a fan of shipping small things on it.
