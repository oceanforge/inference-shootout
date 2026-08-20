import json

import pytest

from pricing import FALLBACK_INPUT_PER_M, FALLBACK_OUTPUT_PER_M, PriceTable


@pytest.fixture
def table(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text(json.dumps({
        "last_verified": "2026-08-20",
        "models": {"cheap-model": {"input_per_m": 0.10, "output_per_m": 0.40}},
    }))
    return PriceTable.load(str(path))


def test_cost_prices_input_and_output_separately(table):
    # 1000 input at $0.10/M = $0.0001; 2000 output at $0.40/M = $0.0008
    assert table.display_cost("cheap-model", 1000, 2000) == pytest.approx(0.0009)


def test_unknown_model_displays_nothing_rather_than_zero(table):
    assert table.display_cost("who-is-this", 1000, 2000) is None


def test_missing_usage_displays_nothing_rather_than_guessing(table):
    assert table.display_cost("cheap-model", None, 2000) is None
    assert table.display_cost("cheap-model", 1000, None) is None


def test_unknown_model_still_charges_the_budget_pessimistically(table):
    """A gap in the price table must not become a gap in the spend ceiling."""
    charged = table.budget_cost("who-is-this", 1000, 2000)
    expected = (1000 * FALLBACK_INPUT_PER_M + 2000 * FALLBACK_OUTPUT_PER_M) / 1_000_000
    assert charged == pytest.approx(expected)
    assert charged > table.budget_cost("cheap-model", 1000, 2000)


def test_missing_usage_charges_the_budget_zero_for_that_component(table):
    assert table.budget_cost("cheap-model", None, None) == 0.0


def test_last_verified_is_exposed_for_the_ui(table):
    assert table.last_verified == "2026-08-20"


def test_shipped_price_table_parses_and_is_dated():
    real = PriceTable.load("prices.json")
    assert real.last_verified
    assert real.display_cost("openai-gpt-oss-120b", 1000, 1000) is not None


def test_no_shipped_rate_is_zero():
    """A zero rate would display as $0.00 — forbidden — and would charge the
    daily budget nothing, turning a price-table gap into a spend-ceiling gap."""
    data = json.loads(open("prices.json").read())
    for model, entry in data["models"].items():
        assert entry["input_per_m"] > 0, model
        assert entry["output_per_m"] > 0, model
