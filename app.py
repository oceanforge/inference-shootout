"""Flask surface: one page, one catalog endpoint, one SSE stream per model."""

import datetime
import json
import os
import time

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

from guards import DailyBudget, RateLimiter
from inference import Catalog, make_client, stream_completion
from pricing import PriceTable

load_dotenv()

DEFAULT_MODELS = [
    "openai-gpt-oss-120b",
    "openai-gpt-oss-20b",
    "llama-4-maverick",
    "deepseek-3.2",
    "qwen3.5-397b-a17b",
    "mistral-3-14B",
]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _refusal(message: str) -> Response:
    """Guard rejections are 200 + an SSE error event.

    EventSource surfaces a non-200 response as an opaque onerror with no body,
    so the reader would see 'something broke' instead of the actual reason.
    """
    return Response(_sse("error", {"message": message}), mimetype="text/event-stream")


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def create_app(client=None, price_table=None, limiter=None, budget=None, config=None):
    app = Flask(__name__)
    # App Platform terminates TLS at an L7 proxy, so request.remote_addr is the
    # proxy's address: without this the "per-IP" rate limiter is one global
    # bucket shared by every visitor. Werkzeug ships with Flask — no new dep.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)

    settings = {
        "MAX_MODELS_PER_RUN": int(os.environ.get("MAX_MODELS_PER_RUN", 6)),
        "MAX_OUTPUT_TOKENS": int(os.environ.get("MAX_OUTPUT_TOKENS", 512)),
        "DEFAULT_MODELS": [
            m.strip()
            for m in os.environ.get("DEFAULT_MODELS", ",".join(DEFAULT_MODELS)).split(",")
            if m.strip()
        ],
    }
    settings.update(config or {})

    client = client or make_client()
    price_table = price_table or PriceTable.load("prices.json")
    if limiter is None:
        # RATE_LIMIT_PER_MINUTE is expressed in races, but the limiter counts
        # streams: one race is N concurrent /stream requests, one per model. So
        # the allowance handed to RateLimiter is races x models-per-race, or the
        # first click of a 6-model race would refuse half its own columns.
        # 0 stays 0 — disabled means disabled, not 0 x 6.
        races = int(os.environ.get("RATE_LIMIT_PER_MINUTE", 3))
        per_race = max(settings["MAX_MODELS_PER_RUN"], 1)
        limiter = RateLimiter(races * per_race if races > 0 else races, time.monotonic)
    if budget is None:
        budget = DailyBudget(float(os.environ.get("DAILY_BUDGET_USD", 5.00)), _utcnow)

    catalog = Catalog(client)

    @app.get("/")
    def index():
        return render_template("index.html", max_models=settings["MAX_MODELS_PER_RUN"])

    @app.get("/api/models")
    def api_models():
        return jsonify(
            models=catalog.ids(),
            defaults=catalog.select(settings["DEFAULT_MODELS"])[: settings["MAX_MODELS_PER_RUN"]],
            prices_last_verified=price_table.last_verified,
            max_models=settings["MAX_MODELS_PER_RUN"],
        )

    @app.get("/stream")
    def stream():
        model = request.args.get("model", "")
        prompt = request.args.get("prompt", "").strip()

        if not prompt:
            return _refusal("Give it a prompt first.")
        if model not in catalog.ids():
            return _refusal(f"{model!r} is not in the model catalog.")
        if not limiter.allow(request.remote_addr or "unknown"):
            return _refusal("Slow down — this demo allows a few runs a minute. Fork it to lift the limit.")
        if not budget.allow():
            return _refusal("The demo budget is spent for today. Fork it and run your own — it takes one env var.")

        max_tokens = settings["MAX_OUTPUT_TOKENS"]
        requested = request.args.get("max_tokens")
        if requested and requested.isdigit():
            max_tokens = min(int(requested), max_tokens)

        def generate():
            inp = out = None
            deltas = 0
            try:
                yield _sse("start", {"model": model})
                for event in stream_completion(client, model, prompt, max_tokens):
                    if event["event"] != "done":
                        if event["event"] == "token":
                            deltas += 1
                        yield _sse(event["event"], event["data"])
                        continue
                    data = dict(event["data"])
                    inp, out = data["input_tokens"], data["output_tokens"]
                    data["cost_usd"] = price_table.display_cost(model, inp, out)
                    yield _sse("done", data)
            finally:
                # Charging here, not in the `done` branch, is what makes the
                # ceiling real: a client that disconnects mid-stream raises
                # GeneratorExit at a `token` yield, so `done` never runs — yet
                # those tokens were generated and billed by the provider. The
                # generator is closed exactly once, so this charges once. If the
                # abort beat the usage chunk, bill the deltas we did stream.
                cost = price_table.budget_cost(model, inp, out if out is not None else deltas)
                if cost > 0:  # skips negatives and NaN, which are never a charge
                    budget.charge(cost)

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


if __name__ == "__main__":
    # No debug=True: the Werkzeug debugger is a remote shell for anyone who can
    # reach it. threaded=True stays — the SSE fan-out needs concurrent requests.
    create_app().run(host="127.0.0.1", port=8080, threaded=True)
