"""Fake OpenAI client. No network, no key, deterministic timing."""
import types


def _chunk(text=None, usage=None):
    delta = types.SimpleNamespace(content=text)
    choice = types.SimpleNamespace(delta=delta)
    return types.SimpleNamespace(choices=[choice] if text is not None else [], usage=usage)


class FakeStream:
    def __init__(self, texts, usage, clock=None, per_chunk=0.0, raise_after=None):
        self._texts = texts
        self._usage = usage
        self._clock = clock
        self._per_chunk = per_chunk
        self._raise_after = raise_after

    def __iter__(self):
        for i, text in enumerate(self._texts):
            if self._raise_after is not None and i == self._raise_after:
                raise RuntimeError("upstream exploded")
            if self._clock is not None:
                self._clock.advance(self._per_chunk)
            yield _chunk(text=text)
        yield _chunk(usage=self._usage)


class FakeClient:
    def __init__(self, model_ids=(), stream_factory=None):
        self._model_ids = list(model_ids)
        self._stream_factory = stream_factory
        self.models = types.SimpleNamespace(list=self._list_models)
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )
        self.calls = []

    def _list_models(self):
        data = [types.SimpleNamespace(id=i) for i in self._model_ids]
        return types.SimpleNamespace(data=data)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._stream_factory(**kwargs)
