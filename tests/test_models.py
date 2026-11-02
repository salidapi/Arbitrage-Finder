"""Contracts must reject ambiguous settlement data before it reaches matching."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from arbscanner.models import Quote, Settings


NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)


def quote_data(**changes):
    data = dict(event_id="source:123", sport="football", league="Test league", home="A", away="B",
                starts_at=NOW + timedelta(hours=2), bookmaker="book-a", market="h2h_3way",
                outcome="home", odds="3.5", observed_at=NOW, source_updated_at=NOW,
                source="fixture", currency="EUR")
    data.update(changes)
    return data


def test_quote_normalizes_timezone_to_utc_and_decimal_prices():
    quote = Quote(**quote_data(observed_at=NOW.astimezone(timezone(timedelta(hours=1)))))
    assert quote.observed_at == NOW
    assert quote.observed_at.tzinfo == timezone.utc
    assert quote.odds == Decimal("3.5")


@pytest.mark.parametrize("field", ["starts_at", "observed_at", "source_updated_at"])
def test_naive_timestamps_rejected(field):
    with pytest.raises(ValidationError, match="timezone"):
        Quote(**quote_data(**{field: NOW.replace(tzinfo=None)}))


@pytest.mark.parametrize("odds", ["NaN", "Infinity", "-Infinity", "1", "0", "-2", "10000.01"])
def test_invalid_decimal_odds_rejected(odds):
    with pytest.raises(ValidationError):
        Quote(**quote_data(odds=odds))


@pytest.mark.parametrize("market,outcome,line", [
    ("h2h_2way", "draw", None), ("h2h_3way", "over", None),
    ("totals", "home", "2.5"), ("spreads", "under", "-1.5"),
    ("h2h_2way", "home", "1.5"), ("totals", "over", None),
    ("totals", "over", "2"), ("totals", "over", "2.25"),
    ("totals", "over", "2.75"), ("totals", "over", "-0.5"),
    ("spreads", "home", "0"), ("spreads", "home", "-0.25"),
    ("spreads", "home", "NaN"), ("spreads", "home", "Infinity"),
    ("spreads", "home", "10000.5"),
])
def test_invalid_or_partial_return_market_contracts_rejected(market, outcome, line):
    with pytest.raises(ValidationError):
        Quote(**quote_data(market=market, outcome=outcome, line=line))


@pytest.mark.parametrize("market,outcome,line", [
    ("totals", "over", "0.5"), ("totals", "under", "2.5"),
    ("spreads", "home", "-1.5"), ("spreads", "away", "1.5"),
])
def test_simple_half_line_contracts_supported(market, outcome, line):
    quote = Quote(**quote_data(market=market, outcome=outcome, line=line))
    assert quote.line == Decimal(line)


def test_source_update_cannot_postdate_retrieval():
    with pytest.raises(ValidationError, match="later"):
        Quote(**quote_data(source_updated_at=NOW + timedelta(microseconds=1)))


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "data:text/html,test", "ftp://example.com/odds", "https:///broken",
    "https://user:secret@example.com/odds",
])
def test_source_links_reject_non_web_schemes_and_credentials(url):
    with pytest.raises(ValidationError):
        Quote(**quote_data(url=url))


def test_identical_participants_and_unexpected_fields_rejected():
    with pytest.raises(ValidationError, match="participants"):
        Quote(**quote_data(home="SAME", away="same"))
    with pytest.raises(ValidationError):
        Quote(**quote_data(secret="not a quote field"))


@pytest.mark.parametrize("changes", [
    {"bankroll": "NaN"}, {"bankroll": "Infinity"}, {"bankroll": "100.001"},
    {"bankroll": "0.99"}, {"bankroll": "1000000.01"},
    {"minimum_profit": float("nan")}, {"minimum_profit": float("inf")},
    {"minimum_profit": -1}, {"minimum_profit": 101},
    {"max_age_seconds": 4}, {"source_skew_seconds": 0},
    {"currency": "eur"}, {"mode": "automatic"},
])
def test_settings_reject_invalid_limits(changes):
    with pytest.raises(ValidationError):
        Settings(**changes)


def test_defaults_require_source_freshness_and_use_live_mode():
    settings = Settings()
    assert settings.mode == "live"
    assert settings.require_source_timestamps is True
    assert settings.bankroll == Decimal("100")
