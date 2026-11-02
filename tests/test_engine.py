"""Synthetic fixtures verify arithmetic and false-positive rejection, not live feeds."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
import random

import pytest

from arbscanner.engine import contract_key, normalized, rounded_plan, scan_quotes
from arbscanner.models import Quote, Settings


NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)


def quote(outcome="home", odds="2.2", bookmaker="book-a", **changes):
    data = dict(event_id="source:123", sport="tennis", league="Test league", home="Player A", away="Player B",
                starts_at=NOW + timedelta(hours=2), bookmaker=bookmaker, market="h2h_2way",
                outcome=outcome, odds=odds, observed_at=NOW, source_updated_at=NOW,
                source="fixture", currency="EUR")
    data.update(changes)
    return Quote(**data)


def pair(**changes):
    return [quote("home", bookmaker="book-a", **changes), quote("away", bookmaker="book-b", **changes)]


def scan(rows, **settings):
    return scan_quotes(rows, Settings(**settings), now=NOW)


def assert_accounting(opportunity, budget=Decimal("100")):
    stakes = [Decimal(leg["stake"]) for leg in opportunity["legs"]]
    payouts = [(stake * Decimal(leg["odds"])).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
               for stake, leg in zip(stakes, opportunity["legs"])]
    total = sum(stakes)
    assert all(stake > 0 and stake == stake.quantize(Decimal("0.01")) for stake in stakes)
    assert total == Decimal(opportunity["total_stake"])
    assert total <= budget
    assert min(payouts) - total == Decimal(opportunity["worst_profit"])
    assert opportunity["roi_percent"] == pytest.approx(float((min(payouts) - total) / total * 100))


def test_two_way_arbitrage_and_profit_accounting():
    result = scan(pair())
    opportunity, = result["opportunities"]
    assert opportunity["roi_percent"] == pytest.approx(10)
    assert opportunity["worst_profit"] == "10.00"
    assert [leg["stake"] for leg in opportunity["legs"]] == ["50.00", "50.00"]
    assert opportunity["warnings"]
    assert_accounting(opportunity)


def test_three_way_requires_all_outcomes_and_allocates_stakes():
    rows = [quote(outcome, "3.4", f"book-{outcome}", market="h2h_3way", sport="football")
            for outcome in ("home", "draw", "away")]
    opportunity, = scan(rows)["opportunities"]
    assert len(opportunity["legs"]) == 3
    assert opportunity["roi_percent"] > 13
    assert_accounting(opportunity)
    assert not scan(rows[:-1])["opportunities"]
    assert scan(rows[:-1])["rejected"]["incomplete_market"] == 1


@pytest.mark.parametrize("odds", ["1.9", "2.0"])
def test_nonprofitable_or_break_even_prices_are_not_opportunities(odds):
    result = scan([quote("home", odds), quote("away", odds, "book-b")], minimum_profit=0)
    assert not result["opportunities"]
    assert result["rejected"]["no_arbitrage"] == 1


def test_threshold_is_return_on_actual_rounded_total_stake():
    assert scan(pair(), minimum_profit=10)["opportunities"]
    rejected = scan(pair(), minimum_profit=10.001)
    assert not rejected["opportunities"]
    assert rejected["rejected"]["below_threshold_after_rounding"] == 1


def test_penny_rounding_can_remove_theoretical_profit():
    rows = [quote("home", "2.001"), quote("away", "2.001", "book-b")]
    result = scan(rows, bankroll="1", minimum_profit=0)
    assert not result["opportunities"]
    assert result["rejected"]["below_threshold_after_rounding"] == 1


def test_best_price_per_outcome_selected_across_books():
    rows = pair() + [quote("home", "2.1", "book-c"), quote("away", "2.05", "book-a")]
    opportunity, = scan(rows)["opportunities"]
    assert [leg["bookmaker"] for leg in opportunity["legs"]] == ["book-a", "book-b"]
    assert_accounting(opportunity)


@pytest.mark.parametrize("changes", [
    {"sport": "basketball"}, {"league": "Different league"},
    {"home": "Player A Women"}, {"away": "Player B U21"},
    {"starts_at": NOW + timedelta(hours=2, seconds=1)},
    {"period": "first_half"}, {"rules": "includes_overtime"},
])
def test_different_event_or_settlement_contracts_never_merge(changes):
    rows = [quote("home"), quote("away", bookmaker="book-b", **changes)]
    result = scan(rows)
    assert not result["opportunities"]
    assert result["rejected"]["incomplete_market"] == 2


def test_home_away_orientation_is_not_guessed():
    rows = [quote("home"), quote("away", bookmaker="book-b", home="Player B", away="Player A")]
    assert not scan(rows)["opportunities"]


def test_name_matching_only_normalizes_case_space_and_unicode_width():
    left = quote("home", home="  PLAYER   A ")
    right = quote("away", bookmaker="book-b", home="Player A", event_id="different-source-event-id")
    assert contract_key(left) == contract_key(right)
    assert scan([left, right])["opportunities"]
    assert normalized("São Paulo") != normalized("Sao Paulo")
    assert normalized("A-B") != normalized("A B")


@pytest.mark.parametrize("market,line,outcomes", [
    ("totals", "2.5", ("over", "under")), ("spreads", "-1.5", ("home", "away")),
])
def test_identical_half_line_markets_are_calculated(market, line, outcomes):
    rows = [quote(outcome, bookmaker=f"book-{index}", market=market, line=line)
            for index, outcome in enumerate(outcomes)]
    opportunity, = scan(rows)["opportunities"]
    assert opportunity["line"] == line
    assert_accounting(opportunity)


def test_different_half_lines_are_never_combined():
    rows = [quote("over", market="totals", line="2.5"),
            quote("under", bookmaker="book-b", market="totals", line="3.5")]
    assert not scan(rows)["opportunities"]


@pytest.mark.parametrize("changes,reason", [
    ({"starts_at": NOW}, "already_started"),
    ({"starts_at": NOW - timedelta(seconds=1)}, "already_started"),
    ({"observed_at": NOW + timedelta(seconds=1)}, "future_timestamp"),
    ({"observed_at": NOW - timedelta(seconds=121), "source_updated_at": NOW - timedelta(seconds=121)}, "stale_observation"),
    ({"source_updated_at": NOW - timedelta(seconds=121)}, "stale_source"),
    ({"source_updated_at": None}, "unknown_source_age"),
    ({"currency": "USD"}, "currency_mismatch"),
])
def test_ineligible_quote_reasons_are_explicit(changes, reason):
    result = scan(pair(**changes))
    assert not result["opportunities"]
    assert result["rejected"][reason] == 2


def test_freshness_limit_is_inclusive():
    rows = pair(observed_at=NOW - timedelta(seconds=120), source_updated_at=NOW - timedelta(seconds=120))
    assert scan(rows, max_age_seconds=120)["opportunities"]


def test_source_age_opt_out_makes_uncertainty_visible():
    opportunity, = scan(pair(source_updated_at=None), require_source_timestamps=False)["opportunities"]
    assert any("unknown" in warning for warning in opportunity["warnings"])
    assert all(leg["source_updated_at"] is None for leg in opportunity["legs"])


def test_source_timestamp_skew_rejected_even_when_both_quotes_are_fresh():
    rows = [quote("home"), quote("away", bookmaker="book-b", source_updated_at=NOW - timedelta(seconds=61))]
    result = scan(rows, source_skew_seconds=60)
    assert not result["opportunities"]
    assert result["rejected"]["quote_time_skew"] == 1


def test_lower_price_coherent_snapshot_is_used_when_global_best_is_too_far_apart():
    rows = [quote("home", "2.3", "book-a"),
            quote("home", "2.1", "book-c", source_updated_at=NOW - timedelta(seconds=60)),
            quote("away", "2.2", "book-b", source_updated_at=NOW - timedelta(seconds=61))]
    result = scan(rows, source_skew_seconds=60)
    opportunity, = result["opportunities"]
    assert {leg["bookmaker"] for leg in opportunity["legs"]} == {"book-c", "book-b"}
    assert opportunity["roi_percent"] > 7
    assert_accounting(opportunity)


def test_quote_skew_uses_observation_when_source_age_opted_out():
    rows = [quote("home", source_updated_at=None),
            quote("away", bookmaker="book-b", source_updated_at=None, observed_at=NOW - timedelta(seconds=61))]
    result = scan(rows, require_source_timestamps=False)
    assert result["rejected"]["quote_time_skew"] == 1


def test_single_bookmaker_never_counts_as_cross_book_arbitrage():
    result = scan([quote("home"), quote("away", bookmaker="BOOK-A")])
    assert not result["opportunities"]
    assert result["rejected"]["single_bookmaker"] == 1


def test_same_time_conflicting_prices_are_discarded():
    result = scan(pair() + [quote("home", "2.3")])
    assert not result["opportunities"]
    assert result["rejected"]["conflicting_quotes"] == 1
    assert result["rejected"]["incomplete_market"] == 1


def test_a_newer_quote_supersedes_old_price_rather_than_selecting_stale_maximum():
    old = quote("home", "10", observed_at=NOW - timedelta(seconds=1), source_updated_at=NOW - timedelta(seconds=1))
    current = quote("home", "1.5")
    result = scan([old, current, quote("away", "2.2", "book-b")])
    assert not result["opportunities"]
    assert result["rejected"]["no_arbitrage"] == 1


def test_newer_quote_resolves_a_previous_conflict_in_either_input_order():
    old = dict(observed_at=NOW - timedelta(seconds=1), source_updated_at=NOW - timedelta(seconds=1))
    rows = [quote("home", "1.4", **old), quote("home", "1.5", **old), quote("home", "2.2"),
            quote("away", "2.2", "book-b")]
    for permutation in (rows, list(reversed(rows))):
        assert scan(permutation)["opportunities"]


def test_filters_use_case_insensitive_substrings():
    assert scan(pair(), sports_filter="TENN", leagues_filter="TEST")["opportunities"]
    assert scan(pair(), sports_filter="football")["rejected"]["sport_filter"] == 2
    assert scan(pair(), leagues_filter="not this league")["rejected"]["league_filter"] == 2


def test_results_sorted_by_rounded_return():
    rows = pair() + pair(home="Other A", away="Other B", odds="2.4")
    opportunities = scan(rows)["opportunities"]
    assert [row["roi_percent"] for row in opportunities] == sorted(
        [row["roi_percent"] for row in opportunities], reverse=True)


def test_randomized_rounded_plans_preserve_budget_and_settlement_accounting():
    rng = random.Random(20261102)
    for count in (2, 3):
        for _ in range(100):
            market = "h2h_2way" if count == 2 else "h2h_3way"
            outcomes = ("home", "away") if count == 2 else ("home", "draw", "away")
            rows = [quote(outcome, str(Decimal(rng.randrange(110, 1000)) / 100), f"book-{index}", market=market)
                    for index, outcome in enumerate(outcomes)]
            budget = Decimal(rng.randrange(100, 100001)) / 100
            plan = rounded_plan(rows, budget)
            assert plan is not None
            roi, profit, total, stakes, payouts = plan
            assert total <= budget
            assert total == sum(stakes)
            assert all(stake > 0 and stake == stake.quantize(Decimal("0.01")) for stake in stakes)
            assert payouts == [(stake * q.odds).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
                               for stake, q in zip(stakes, rows)]
            assert profit == min(payouts) - total
            assert roi == profit / total * 100
