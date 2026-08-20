"""Cost estimation for inference runs.

Two cost functions on purpose. `display_cost` is what the reader sees and it
refuses to guess: an unknown model renders an em dash, never $0.00, because a
confidently wrong number is worse than an absent one. `budget_cost` feeds the
spend ceiling and must never return zero for a model it does not recognise —
otherwise a gap in the price table silently becomes a gap in the ceiling.
"""

import json
import pathlib
from dataclasses import dataclass

# Deliberately above the most expensive model in the catalog. Guessing high
# costs a self-hoster nothing and protects the demo's owner from a model that
# shipped after prices.json was last verified.
FALLBACK_INPUT_PER_M = 15.00
FALLBACK_OUTPUT_PER_M = 75.00


@dataclass(frozen=True)
class Rate:
    input_per_m: float
    output_per_m: float


class PriceTable:
    def __init__(self, rates: dict[str, Rate], last_verified: str):
        self._rates = rates
        self.last_verified = last_verified

    @classmethod
    def load(cls, path: str) -> "PriceTable":
        data = json.loads(pathlib.Path(path).read_text())
        rates = {
            model: Rate(entry["input_per_m"], entry["output_per_m"])
            for model, entry in data["models"].items()
        }
        return cls(rates, data["last_verified"])

    def display_cost(self, model, input_tokens, output_tokens):
        """USD for the UI, or None when we cannot know."""
        if model not in self._rates or input_tokens is None or output_tokens is None:
            return None
        return self._cost(self._rates[model], input_tokens, output_tokens)

    def budget_cost(self, model, input_tokens, output_tokens):
        """USD for the spend accumulator. Always a number."""
        rate = self._rates.get(model, Rate(FALLBACK_INPUT_PER_M, FALLBACK_OUTPUT_PER_M))
        return self._cost(rate, input_tokens or 0, output_tokens or 0)

    @staticmethod
    def _cost(rate: Rate, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * rate.input_per_m + output_tokens * rate.output_per_m) / 1_000_000
