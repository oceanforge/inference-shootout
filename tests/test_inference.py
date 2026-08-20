import types
import pytest
from conftest import FakeClient, FakeStream
from inference import BASE_URL, Catalog, make_client, stream_completion


class FakeClock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, delta):
        self.value += delta


def test_base_url_matches_digitalocean_exactly():
    assert BASE_URL == "https://inference.do-ai.run/v1/"


def test_make_client_fails_loudly_without_the_key(monkeypatch):
    monkeypatch.delenv("DIGITAL_OCEAN_MODEL_ACCESS_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DIGITAL_OCEAN_MODEL_ACCESS_KEY"):
        make_client()


def test_catalog_caches_the_model_list():
    client = FakeClient(model_ids=["b", "a"])
    catalog = Catalog(client)
    assert catalog.ids() == ["a", "b"]
    client._model_ids = ["totally", "different"]
    assert catalog.ids() == ["a", "b"]  # cached, not refetched


def test_catalog_drops_models_that_no_longer_exist():
    """DigitalOcean's own starter kit still names a retired model. A retired
    selection must degrade to 'not selected', never to a crash."""
    catalog = Catalog(FakeClient(model_ids=["live-model"]))
    assert catalog.select(["live-model", "llama3-8b-instruct"]) == ["live-model"]


def test_stream_emits_tokens_then_done():
    usage = types.SimpleNamespace(prompt_tokens=11, completion_tokens=22)
    client = FakeClient(stream_factory=lambda **kw: FakeStream(["Hel", "lo"], usage))
    events = list(stream_completion(client, "m", "hi", 512, clock=FakeClock()))
    assert [e["event"] for e in events] == ["token", "token", "done"]
    assert [e["data"]["text"] for e in events[:2]] == ["Hel", "lo"]
    assert events[-1]["data"]["input_tokens"] == 11
    assert events[-1]["data"]["output_tokens"] == 22


def test_ttft_measures_to_the_first_content_delta():
    clock = FakeClock()
    usage = types.SimpleNamespace(prompt_tokens=1, completion_tokens=2)
    client = FakeClient(
        stream_factory=lambda **kw: FakeStream(["a", "b"], usage, clock=clock, per_chunk=0.5)
    )
    done = list(stream_completion(client, "m", "hi", 512, clock=clock))[-1]
    assert done["data"]["ttft_ms"] == 500
    assert done["data"]["total_ms"] == 1000


def test_missing_usage_reports_none_rather_than_zero():
    client = FakeClient(stream_factory=lambda **kw: FakeStream(["x"], usage=None))
    done = list(stream_completion(client, "m", "hi", 512, clock=FakeClock()))[-1]
    assert done["data"]["input_tokens"] is None
    assert done["data"]["output_tokens"] is None


def test_upstream_failure_becomes_a_terminal_error_event():
    client = FakeClient(
        stream_factory=lambda **kw: FakeStream(["a", "b"], usage=None, raise_after=1)
    )
    events = list(stream_completion(client, "m", "hi", 512, clock=FakeClock()))
    assert events[0]["event"] == "token"
    assert events[-1]["event"] == "error"
    assert "exploded" in events[-1]["data"]["message"]


def test_max_tokens_is_passed_through():
    client = FakeClient(stream_factory=lambda **kw: FakeStream([], usage=None))
    list(stream_completion(client, "m", "hi", 128, clock=FakeClock()))
    assert client.calls[0]["max_tokens"] == 128
    assert client.calls[0]["stream"] is True
