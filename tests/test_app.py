import datetime
import json
import types
import pytest
from conftest import FakeClient, FakeStream
from app import create_app
from pricing import PriceTable
from guards import RateLimiter, DailyBudget

FIXED_DAY = datetime.datetime(2026, 8, 20, tzinfo=datetime.timezone.utc)


def sse_events(response):
    """Parse an SSE body into [(event, data_dict), ...]."""
    out = []
    for block in response.data.decode().split("\n\n"):
        if not block.strip():
            continue
        name = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        out.append((name, data))
    return out


@pytest.fixture
def price_table(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text(json.dumps({
        "last_verified": "2026-08-20",
        "models": {"m1": {"input_per_m": 1.0, "output_per_m": 2.0}},
    }))
    return PriceTable.load(str(path))


def build(price_table, model_ids=("m1", "m2"), texts=("hi",), config=None,
          limiter=None, budget=None):
    """Returns (app, client). The client comes back so tests can inspect the
    calls made to it without production code stashing a reference for them."""
    usage = types.SimpleNamespace(prompt_tokens=10, completion_tokens=20)
    client = FakeClient(
        model_ids=list(model_ids),
        stream_factory=lambda **kw: FakeStream(list(texts), usage),
    )
    settings = {
        "MAX_MODELS_PER_RUN": 6,
        "MAX_OUTPUT_TOKENS": 512,
        "DEFAULT_MODELS": ["m1"],
    }
    settings.update(config or {})
    app = create_app(
        client=client,
        price_table=price_table,
        limiter=limiter or RateLimiter(0, lambda: 0.0),
        budget=budget or DailyBudget(0, lambda: FIXED_DAY),
        config=settings,
    )
    app.config["TESTING"] = True
    return app, client


def test_index_renders(price_table):
    app, _ = build(price_table)
    assert app.test_client().get("/").status_code == 200


def test_api_models_returns_catalog_and_defaults(price_table):
    app, _ = build(price_table)
    body = app.test_client().get("/api/models").get_json()
    assert body["models"] == ["m1", "m2"]
    assert body["defaults"] == ["m1"]
    assert body["prices_last_verified"] == "2026-08-20"


def test_api_models_drops_retired_defaults(price_table):
    app, _ = build(price_table, model_ids=("m2",), config={"DEFAULT_MODELS": ["m1", "m2"]})
    assert app.test_client().get("/api/models").get_json()["defaults"] == ["m2"]


def test_stream_emits_start_tokens_then_done_with_cost(price_table):
    app, _ = build(price_table)
    events = sse_events(app.test_client().get("/stream?model=m1&prompt=hi"))
    assert events[0][0] == "start"
    assert ("token", {"text": "hi"}) in events
    name, data = events[-1]
    assert name == "done"
    # 10 input at $1/M + 20 output at $2/M
    assert data["cost_usd"] == pytest.approx((10 * 1.0 + 20 * 2.0) / 1_000_000)


def test_stream_reports_no_cost_for_unpriced_model(price_table):
    app, _ = build(price_table)
    events = sse_events(app.test_client().get("/stream?model=m2&prompt=hi"))
    assert events[-1][1]["cost_usd"] is None


def test_unknown_model_is_refused(price_table):
    app, _ = build(price_table)
    events = sse_events(app.test_client().get("/stream?model=nope&prompt=hi"))
    assert events[-1][0] == "error"


def test_empty_prompt_is_refused(price_table):
    app, _ = build(price_table)
    events = sse_events(app.test_client().get("/stream?model=m1&prompt=%20"))
    assert events[-1][0] == "error"


def test_guard_rejection_is_http_200_with_an_error_event(price_table):
    """EventSource cannot read a non-200 body, so refusals must be 200 + event."""
    app, _ = build(price_table, limiter=RateLimiter(per_minute=1, clock=lambda: 1000.0))
    client = app.test_client()
    client.get("/stream?model=m1&prompt=hi")
    resp = client.get("/stream?model=m1&prompt=hi")
    assert resp.status_code == 200
    assert sse_events(resp)[-1][0] == "error"


def test_budget_exhaustion_refuses_and_points_at_forking(price_table):
    budget = DailyBudget(limit_usd=0.01, clock=lambda: FIXED_DAY)
    budget.charge(1.0)
    app, _ = build(price_table, budget=budget)
    events = sse_events(app.test_client().get("/stream?model=m1&prompt=hi"))
    assert events[-1][0] == "error"
    assert "fork" in events[-1][1]["message"].lower()


def test_successful_run_charges_the_budget(price_table):
    budget = DailyBudget(limit_usd=1.00, clock=lambda: FIXED_DAY)
    app, _ = build(price_table, budget=budget)
    # buffered=True: /stream is a genuine incremental generator (production
    # streams it lazily to gunicorn), so the test client's default one-chunk
    # peek stops before the "done" event runs. Draining fully here is the
    # documented way to observe request-completion side effects without
    # weakening the production streaming behaviour itself.
    app.test_client().get("/stream?model=m1&prompt=hi", buffered=True)
    assert budget.remaining() < 1.00


def test_max_output_tokens_is_enforced_server_side(price_table):
    app, client = build(price_table, config={"MAX_OUTPUT_TOKENS": 64})
    app.test_client().get("/stream?model=m1&prompt=hi&max_tokens=99999", buffered=True)
    assert client.calls[0]["max_tokens"] == 64
