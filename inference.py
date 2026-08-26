"""The entire DigitalOcean-specific surface area of this app.

Note how little there is: an OpenAI client with a different base_url. That is
the argument the project exists to make.
"""

import os
import time
from openai import OpenAI

BASE_URL = "https://inference.do-ai.run/v1/"


def make_client() -> OpenAI:
    key = os.environ.get("DIGITAL_OCEAN_MODEL_ACCESS_KEY")
    if not key:
        raise RuntimeError(
            "DIGITAL_OCEAN_MODEL_ACCESS_KEY is not set. Create a model access key "
            "in the DigitalOcean control panel under the Gradient AI Platform — "
            "this is not the same thing as a DigitalOcean API token."
        )
    return OpenAI(base_url=BASE_URL, api_key=key)


class Catalog:
    """Live model list, fetched once and cached.

    Never hardcode the catalog: DigitalOcean's own starter kit still references
    llama3-8b-instruct, which has since been retired.
    """

    def __init__(self, client):
        self._client = client
        self._ids: list[str] | None = None

    def ids(self) -> list[str]:
        if self._ids is None:
            self._ids = sorted(model.id for model in self._client.models.list().data)
        return self._ids

    def select(self, requested: list[str]) -> list[str]:
        available = set(self.ids())
        return [model for model in requested if model in available]


def stream_completion(client, model, prompt, max_tokens, clock=time.monotonic):
    """Yield {"event": ..., "data": ...} dicts for one model's response.

    Errors are yielded as a terminal `error` event rather than raised, so one
    model failing cannot take down the request that produced it.
    """
    started = clock()
    ttft_ms = None
    usage = None
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        for chunk in stream:
            if getattr(chunk, "usage", None):
                usage = chunk.usage
            for choice in chunk.choices or []:
                text = getattr(choice.delta, "content", None)
                if not text:
                    continue
                if ttft_ms is None:
                    ttft_ms = round((clock() - started) * 1000)
                yield {"event": "token", "data": {"text": text}}
    except Exception as exc:  # noqa: BLE001 - surfaced to the reader, not swallowed
        yield {"event": "error", "data": {"message": str(exc)}}
        return

    yield {
        "event": "done",
        "data": {
            "ttft_ms": ttft_ms,
            "total_ms": round((clock() - started) * 1000),
            "input_tokens": getattr(usage, "prompt_tokens", None),
            "output_tokens": getattr(usage, "completion_tokens", None),
            "reasoning_tokens": _reasoning_tokens(usage),
        },
    }


def _reasoning_tokens(usage):
    """Tokens a reasoning model spent thinking rather than answering.

    Reasoning models stream their thinking in `delta.reasoning_content`, which
    is not part of the OpenAI schema, so a client reading `delta.content` sees
    nothing at all. With a low max_tokens the model can spend its entire budget
    reasoning and return zero visible output while still billing in full. The
    count is surfaced so an empty column can explain itself instead of just
    looking broken.
    """
    details = getattr(usage, "completion_tokens_details", None)
    return getattr(details, "reasoning_tokens", None) if details else None
