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
    content_chars = 0
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
                content_chars += len(text)
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
            "content_chars": content_chars,
            "reasoning_tokens": _reasoning_tokens(usage),
        },
    }


def _reasoning_tokens(usage):
    """Tokens a reasoning model spent thinking rather than answering, if reported.

    Reasoning models stream their thinking in `delta.reasoning_content`, which
    is outside the OpenAI schema, so a client reading `delta.content` sees
    nothing while the model bills in full.

    This only ever LABELS that failure. It must not be what detects it: a
    provider that bills the reasoning without reporting a count, or reports it
    under another name, would produce the same silent column and this would
    return None. Detection belongs on `content_chars` against `output_tokens`,
    which holds whatever the cause turns out to be. Credit to Vinh Nguyen for
    pointing out that the original check inherited the shape of the bug it
    was meant to explain.
    """
    details = getattr(usage, "completion_tokens_details", None)
    return getattr(details, "reasoning_tokens", None) if details else None
