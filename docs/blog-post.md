---
title: "I raced six models against each other on DigitalOcean Inference. The cheapest one won."
published: false
tags: showdev, ai, python, digitalocean
canonical_url:
---

Every time I put a model behind an endpoint I make the same lazy decision.
I pick whatever I used last time, or whatever I read about most recently,
and I tell myself I'll benchmark it properly later, and later never
arrives because there is always something with an actual deadline on it
and comparing model latencies feels like procrastination even when it
isn't. I never do it. Not once.

So I built the thing that would make me do it. One prompt, fired at six
models at once, streaming side by side in columns, with time to first
token and cost per run underneath each one. About 390 lines of Python.
[Code's here](https://github.com/oceanforge/inference-shootout), MIT, take
it.

Then I ran it, and three things happened that I didn't plan for.

![Six models streaming answers to one prompt side by side, filling at different speeds](https://raw.githubusercontent.com/oceanforge/inference-shootout/main/docs/race.gif)

## The integration is two lines, and that's the least interesting part

DigitalOcean's inference endpoint speaks OpenAI, so this is the whole
thing:

```python
client = OpenAI(
    base_url="https://inference.do-ai.run/v1/",
    api_key=os.environ["DIGITAL_OCEAN_MODEL_ACCESS_KEY"],
)
```

Every model below goes through that one client. Llama, DeepSeek, Mistral,
Qwen, OpenAI's open-weight `gpt-oss` line. Only the model string changes.

That is the pitch, and it's real, and I'll move past it quickly because
you already knew an OpenAI-compatible endpoint would work like an OpenAI-
compatible endpoint. What I didn't know is everything that follows.

One footnote before you paste that snippet. The credential is a *model
access key*, created under the Gradient AI Platform. It is not the API
token from Settings, API. Different thing, different page. (Although, as I
found out later, the endpoint doesn't care nearly as much about that
distinction as the docs do.)

## Six streams, no event loop

I wanted the columns to fill simultaneously. Real racing, not six
sequential progress bars pretending.

The tidy way to do that is one endpoint that fans out server side and
multiplexes everything back down a single connection. I didn't do the tidy
way. The browser opens one `EventSource` per model instead:

```
GET /stream?model=<id>&prompt=<text>
```

Six models, six connections, six independent lifetimes. Nothing merges
anything. Flask stays synchronous, no async, no orchestration layer, and
the entire streaming path is about forty lines.

I did it that way because it's simpler, and I stand by that. But the
reason I'm glad I did it turned out to be different from the reason I
chose it, which I'll get to.

## I predicted the wrong bug

Here's the part where I lost an hour.

I knew gunicorn's default sync worker would be a problem. It handles one
connection per worker process and holds it until the response is done.
Fine for requests that last 40 milliseconds. Streaming responses stay open
for seconds, so six concurrent streams need six workers or they queue.

I predicted the page would hang. It doesn't hang. Here's what six
concurrent streams actually look like against one sync worker:

| model | first token |
| --- | --- |
| mistral-3-14B | 1250 ms |
| openai-gpt-oss-120b | 5326 ms |
| openai-gpt-oss-20b | 7278 ms |
| deepseek-3.2 | 8347 ms |
| llama-4-maverick | 9147 ms |

Look at the spacing. Each stream's first token shows up right about when
the previous stream finished. That's not slow models, that's a queue. Six
requests, one at a time, 10.7 seconds to get through all of them.

Switch to threaded workers:

```
web: gunicorn --worker-class gthread --threads 16 --timeout 120 'app:create_app()'
```

Now four of the six first tokens land inside a 1.4 second window instead
of marching across a ten second one, and the whole thing takes 6.4
seconds.

But go back and look at that first table again, because the interesting
part isn't the fix. Every one of those requests succeeded. Correct
responses, no timeouts, no errors, nothing in the logs. If I'd shipped the
broken version I would not have filed a bug against myself, I'd have
watched the columns fill in one after another, concluded the models were
slow, and gone off to write a caching layer for a problem that was sitting
in my Procfile the entire time. A hang would have been kinder. A hang
makes you look at your server.

## The catalog will lie to you

The model picker is built from `GET /v1/models`, because hardcoding a
model list is how you end up shipping a dead one.

That call returns 72 models. My account can call six.

Everything from Anthropic, plus GPT-4o and o3, comes back with:

```
403 - {'error': {'message': 'this model is not available for your
subscription tier', 'type': 'forbidden_error'}}
```

There is nothing in the `/v1/models` response that tells you which is
which. No availability flag, no tier field, no hint. You find out by
calling it and reading the 403.

Which is how I shipped a broken default. My preselected list had
`anthropic-claude-haiku-4.5` sitting right there in it, because it's in
the published catalog and it's on the pricing page with a real per-token
rate beside it, and at no point between reading those two documents and
writing that list did anything suggest I ought to check whether my own
account could call the thing. First real run, that column went red in
front of me.

Now, remember those six independent connections. The dead model threw its
403, showed the error in its own column, and the other five kept streaming
like nothing happened. I built that isolation for hypothetical failures.
The first real failure arrived about sixty seconds after first contact
with the API.

If you're building anything that populates a menu from that endpoint, and
DigitalOcean's docs point you right at it, assume most of what comes back
is unreachable.

## Small thing about credentials

The docs are firm that a model access key and an API token are different
credentials. They are. But a `dop_v1_...` API token authenticates fine
against `inference.do-ai.run`. I checked it against that and against
`api.digitalocean.com/v2/account` and it works on both.

Use the narrow one anyway. A leaked model access key costs you some
inference spend. A leaked API token costs you the account.

## What the numbers said

Three prompt shapes (short factual, long explanation, code generation),
six models, three runs each. 54 calls, `max_tokens=512`, `nyc` region, run
from a laptop in Europe at about ten at night.

![The finished run: six columns of output above a table of TTFT, total time, tokens and cost](https://raw.githubusercontent.com/oceanforge/inference-shootout/main/docs/screenshot.png)

Medians across all nine runs per model:

| model | TTFT | total | cost | runs with no text |
| --- | --- | --- | --- | --- |
| mistral-3-14B | **533 ms** | 3.3 s | **$0.000108** | 0/9 |
| llama-4-maverick | 676 ms | 17.9 s | $0.000362 | 0/9 |
| deepseek-3.2 | 869 ms | 5.4 s | $0.000416 | 0/9 |
| openai-gpt-oss-20b | 1792 ms | 4.6 s | $0.000235 | 2/9 |
| openai-gpt-oss-120b | 4797 ms | 16.7 s | $0.000367 | 0/9 |
| qwen3.5-397b-a17b | 9332 ms | 32.0 s | $0.000995 | **7/9** |

Mistral 14B won on every axis I measured. Fastest to first token, fastest
overall, cheapest per run, and it answered every single time. There's no
trade-off curve to position yourself on here. For this workload the
expensive models bought me nothing at all, which is not the result I
expected and not the result I'd have guessed if you'd asked me on Friday.

Time to first token ranged from 533 ms to 9.3 seconds. That's a 17x
spread. If a model is going behind anything a person waits on, that gap
decides whether the feature works, and there's no way to guess it from a
model card.

Then there's the last column.

## Nothing failed. Nine runs came back empty.

All 54 calls succeeded. No exceptions, no non-200s, no timeouts. Run this
through any monitoring you like and it's a clean sheet.

Nine of those calls returned no readable text at all. Full price.

`qwen3.5-397b-a17b` did it seven times out of nine. It was also the most
expensive model in the race, roughly 9x Mistral, and the slowest at 32
seconds. Thirty-two seconds, top of the bill, empty box.

It's a reasoning model. What happened is it spent 487 of its 512 token
budget thinking, ran out of room before writing a single word of the
actual answer, and streamed all that thinking into a field called
`delta.reasoning_content`, which is not part of the OpenAI schema and is
therefore invisible to every OpenAI-compatible client on earth, mine
included. So the request succeeds. The tokens get billed. The box stays
empty.

```
completion_tokens: 512
reasoning_tokens:  487
content:           0 characters
```

You can pay full price for silence and have your dashboards call it a
success.

I patched the app so a column with no content but non-zero
`reasoning_tokens` explains itself instead of just sitting there looking
broken. Raise `max_tokens` and Qwen does answer. Fine. But the general
version of this is worse than my particular bug: if your evaluation
watches latency and status codes, it is structurally incapable of seeing
this failure. You have to look at what came back.

Which is, awkwardly for me, the entire argument for building a tool that
puts the output next to the numbers. I did not set out to prove my own
premise. It just kept happening.

## The bill

$0.0185. For all 54 calls.

I spent longer reading the pricing page than the experiment cost to run.
That reframed the whole exercise for me. The reason nobody measures this
stuff before picking a model isn't cost, and it isn't really time either.
It's that there's nothing sitting there ready to run. So now there is one.

## Would I use it again

For picking a model for a specific job, yes. I have opinions about Mistral
14B now that I didn't have last week, and they came from data instead of
from a thread I skimmed.

The friction was real but small. A catalog that advertises models you
can't call. A credential distinction that's enforced less strictly than
it's described. A worker config trap that would bite any streaming app on
any platform. Only the first of those is really DigitalOcean's, and it's
the one I'd most like fixed. An `available` field on `/v1/models` is an
afternoon of work and it would save everybody that 403.

What I'd recommend is the boring part I skipped past at the top. Comparing
four providers normally means four SDKs with four different streaming
conventions, four keys in four places, four dashboards and four invoices
at the end of the month, and by the time that plumbing works you have
spent more effort on it than on the question you started with. Here it
meant editing a list of strings.

Caveats, plainly: n=3, one region, one evening, one account tier, one set
of prompts, and a laptop in Europe hitting a New York datacenter. This is
not a benchmark. It's one developer's Tuesday night. The point was never
to hand you authoritative numbers, it was to make it cheap enough that you
go and get your own, on your prompts, on your account.

---

Code: **[github.com/oceanforge/inference-
shootout](https://github.com/oceanforge/inference-shootout)**. `NOTES.md`
has the raw build log, including the parts that went wrong in real time,
and `docs/measurements.json` has all 54 runs if you want to argue with
them.

Part of [oceanforge](https://github.com/oceanforge), small deploy-it-
yourself apps for the DigitalOcean cloud. Not affiliated with
DigitalOcean, just a fan of shipping small things on it.
