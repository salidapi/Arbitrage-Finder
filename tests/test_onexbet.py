"""Synthetic 1XBet dashboard contracts; no captured user source is bundled."""
import builtins
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html import escape
import json
from unittest.mock import AsyncMock

from bs4.element import Tag
import pytest

from arbscanner.connectors.base import SourceConfigurationError
from arbscanner.connectors import fetch_source
from arbscanner.connectors.onexbet import parse_onexbet_dashboard


NOW = datetime(2026, 11, 3, 21, tzinfo=timezone.utc)
START = datetime(2026, 11, 4, 17, 45, tzinfo=timezone.utc)
BASE = "https://al-1xbet.com/en"
ROUTE = "/en/line/football/123-example-league/456-alpha-fc-beta-fc"
KEY = "normalizedDataItems-betting/home/line/dashboardStore-games"


def config(**constants):
    return {"allowed_hosts": ["al-1xbet.com"], "constants": {
        "rules": "regulation", "period": "full_time", "currency": "EUR", **constants}}


def metadata(**changes):
    record = {"id": 987, "permanentId": 456, "gameIdForUrl": "456",
              "sportName": "Football", "sportNameForUrl": "football",
              "champName": "Example League", "champNameForUrl": "123-example-league",
              "firstOpponentName": "Alpha FC", "secondOpponentName": "Beta FC",
              "gameNameForUrl": "456-alpha-fc-beta-fc",
              "startUnixTimestamp": int(START.timestamp()), "startTimestamp": int(START.timestamp() * 1000),
              "isNotStarted": True, "isGameOver": False, "isLong": False,
              "isSubGame": False, "isDummy": False, "sectionType": 3,
              "markets": [], "additionalMarkets": [], "marketGroups": {}}
    record.update(changes)
    return record


def ld_metadata(**changes):
    record = {"@context": "https://schema.org", "@type": "SportsEvent",
              "name": "Alpha FC - Beta FC", "url": "https://al-1xbet.com" + ROUTE,
              "startDate": START.isoformat().replace("+00:00", "Z"),
              "organizer": {"name": "Example League", "sport": "Football"},
              "homeTeam": {"name": "Alpha FC", "sport": "Football"},
              "awayTeam": {"name": "Beta FC", "sport": "Football"}}
    record.update(changes)
    return record


def hydration(records=None, nested=True):
    payload = json.dumps({KEY: records if records is not None else [metadata()]})
    inner = "window.__BETTING_APP__=(function(){return " + payload + ";})();"
    script = "window.__V3_HOST_APP__=(function(){return " + json.dumps(inner) + ";})();" if nested else inner
    return "<script>" + script + "</script>"


def jsonld(records=None):
    return '<script type="application/ld+json">' + json.dumps(records if records is not None else [ld_metadata()]) + "</script>"


def row(route=ROUTE, home="Alpha FC", away="Beta FC", islive="false", labels=("W1", "X", "W2"),
        prices=("2.601", "3.60", "2.95"), cell_attrs=None):
    attrs = cell_attrs or {}
    cells = []
    for index, (label, price) in enumerate(zip(labels, prices)):
        cell_class, button_attrs = attrs.get(index, ("", ""))
        cells.append(f'<span class="dashboard-markets__market {cell_class}">'
                     f'<button class="ui-market__toggle" aria-label="{escape(label)}" {button_attrs}>'
                     f'<span class="ui-market__value">{escape(price)}</span></button></span>')
    return (f'<li class="dashboard-game"><div class="dashboard-game-action-bar" islive="{escape(islive)}"></div>'
            f'<a class="dashboard-game-block__link" href="{escape(route)}">'
            f'<span data-test="betting-dashboard-game-first-team"><b class="dashboard-game-team-info__name">{escape(home)}</b></span>'
            f'<span data-test="betting-dashboard-game-second-team"><b class="dashboard-game-team-info__name">{escape(away)}</b></span></a>'
            '<span class="dashboard-game-info__date">04/11</span><span class="dashboard-game-info__time">18:45</span>'
            '<div class="dashboard-markets__group">' + "".join(cells) + "</div></li>")


@pytest.mark.parametrize("schedule", [jsonld(), hydration(), hydration(nested=False)])
def test_exact_metadata_join_preserves_price_precision_and_unknown_freshness(schedule):
    quotes, rejected = parse_onexbet_dashboard(schedule + row(), config(), observed_at=NOW)
    assert rejected == 0 and len(quotes) == 3
    assert [quote.outcome for quote in quotes] == ["home", "draw", "away"]
    assert [quote.odds for quote in quotes] == [Decimal("2.601"), Decimal("3.60"), Decimal("2.95")]
    assert {quote.event_id for quote in quotes} == {"456"}  # Not temporary hydration ID 987.
    assert all(quote.starts_at == START and quote.observed_at == NOW and quote.source_updated_at is None for quote in quotes)
    assert all(quote.sport == "soccer" and quote.market == "h2h_3way" and quote.period == "full_time" for quote in quotes)
    assert quotes[0].url == "https://al-1xbet.com" + ROUTE


def test_jsonld_graph_and_agreeing_duplicate_metadata_are_supported():
    schedule = jsonld({"@context": "https://schema.org", "@graph": [ld_metadata()]}) + hydration()
    assert len(parse_onexbet_dashboard(schedule + row(), config(), observed_at=NOW)[0]) == 3


def test_current_observation_is_used_when_not_supplied(monkeypatch):
    from arbscanner.connectors import onexbet
    monkeypatch.setattr(onexbet, "utcnow", lambda: NOW)
    quotes, _ = parse_onexbet_dashboard(hydration() + row(), config())
    assert quotes[0].observed_at == NOW


@pytest.mark.parametrize("changes", [
    {"firstOpponentName": "Another FC"},
    {"firstOpponentName": "Beta FC", "secondOpponentName": "Alpha FC"},
    {"permanentId": 999, "gameIdForUrl": "999", "gameNameForUrl": "999-alpha-fc-beta-fc"},
    {"gameNameForUrl": "456-different-route"},
])
def test_wrong_identity_or_names_never_join(changes):
    quotes, rejected = parse_onexbet_dashboard(hydration([metadata(**changes)]) + row(), config(), observed_at=NOW)
    assert quotes == [] and rejected >= 1


def test_conflicting_metadata_rejects_even_if_one_candidate_matches():
    schedule = hydration([metadata(), metadata(firstOpponentName="Another FC")])
    quotes, rejected = parse_onexbet_dashboard(schedule + row(), config(), observed_at=NOW)
    assert quotes == [] and rejected == 1
    schedule = jsonld() + hydration([metadata(startUnixTimestamp=int(START.timestamp()) + 60,
                                               startTimestamp=int(START.timestamp() * 1000) + 60000)])
    assert parse_onexbet_dashboard(schedule + row(), config(), observed_at=NOW)[0] == []


@pytest.mark.parametrize("route", [
    "https://evil.example" + ROUTE, "//evil.example" + ROUTE,
    "https://al-1xbet.com.evil.example" + ROUTE,
    "https://user:secret@al-1xbet.com" + ROUTE,
    "https://al-1xbet.com:444" + ROUTE, ROUTE + "?fixture=999", ROUTE.replace("/line/", "/live/"),
])
def test_wrong_host_credentials_or_non_prematch_route_are_rejected(route):
    assert parse_onexbet_dashboard(hydration() + row(route=route), config(), observed_at=NOW)[0] == []


@pytest.mark.parametrize("labels", [("1", "X", "2"), ("W1", "W1", "W2"), ("W1", "W2"), ("W1", "X", "Over")])
def test_requires_exact_complete_three_way_labels(labels):
    quotes, rejected = parse_onexbet_dashboard(hydration() + row(labels=labels), config(), observed_at=NOW)
    assert quotes == [] and rejected == 1


@pytest.mark.parametrize("attributes", [
    ("ui-market--locked", ""), ("ui-market--empty", ""), ("", "disabled"),
    ("", 'disabled="false"'), ("", 'aria-disabled="true"'),
])
def test_unavailable_prices_are_not_read(monkeypatch, attributes):
    original = Tag.get_text

    def guarded_text(node, *args, **kwargs):
        if "ui-market__value" in node.get("class", []) and node.string == "DO-NOT-READ":
            raise AssertionError("An unavailable price was read")
        return original(node, *args, **kwargs)

    monkeypatch.setattr(Tag, "get_text", guarded_text)
    html = hydration() + row(prices=("DO-NOT-READ", "3.60", "2.95"), cell_attrs={0: attributes})
    quotes, rejected = parse_onexbet_dashboard(html, config(), observed_at=NOW)
    assert [quote.outcome for quote in quotes] == ["draw", "away"] and rejected == 1


@pytest.mark.parametrize("price", ["", "1.0", "NaN", "Infinity", "2,50", "5/2", "-150", "10000.01", "2 50"])
def test_only_valid_decimal_dom_prices_are_accepted(price):
    quotes, rejected = parse_onexbet_dashboard(hydration() + row(prices=(price, "3.60", "2.95")), config(), observed_at=NOW)
    assert len(quotes) == 2 and rejected == 1


@pytest.mark.parametrize("changes", [
    {"isNotStarted": False}, {"isNotStarted": "true"}, {"isLive": True}, {"isGameOver": True},
    {"isLong": True}, {"isSubGame": True}, {"isDummy": True}, {"sectionType": 1},
    {"sportName": "Ice Hockey"}, {"sportName": "American Football"},
    {"firstOpponentName": "Home", "secondOpponentName": "Away"},
    {"firstOpponentName": "Home Special Bets", "secondOpponentName": "Away Special Bets"},
    {"gameNameForUrl": "456-alpha-beta-aggregate"},
])
def test_unsupported_status_sport_and_synthetic_events_fail_closed(changes):
    with pytest.raises(SourceConfigurationError, match="No usable 1XBet fixture metadata"):
        parse_onexbet_dashboard(hydration([metadata(**changes)]) + row(), config(), observed_at=NOW)


@pytest.mark.parametrize("islive", ["true", "", "False"])
def test_dom_must_explicitly_mark_prematch(islive):
    assert parse_onexbet_dashboard(hydration() + row(islive=islive), config(), observed_at=NOW)[0] == []


@pytest.mark.parametrize("observed", [START, START + timedelta(seconds=1), datetime(2026, 11, 5, tzinfo=timezone.utc)])
def test_historical_snapshot_is_not_accepted_as_a_current_prematch_quote(observed):
    quotes, rejected = parse_onexbet_dashboard(hydration() + row(), config(), observed_at=observed)
    assert quotes == [] and rejected == 1


@pytest.mark.parametrize("remove", ["startUnixTimestamp", "startTimestamp"])
def test_one_explicit_unix_timestamp_with_known_units_is_sufficient(remove):
    item = metadata()
    del item[remove]
    assert len(parse_onexbet_dashboard(hydration([item]) + row(), config(), observed_at=NOW)[0]) == 3


@pytest.mark.parametrize("changes", [
    {"startUnixTimestamp": None}, {"startTimestamp": "1793814300000"}, {"startUnixTimestamp": True},
    {"startTimestamp": 1}, {"startUnixTimestamp": 0}, {"startTimestamp": float("nan")},
])
def test_invalid_or_disagreeing_timestamps_are_rejected(changes):
    with pytest.raises(SourceConfigurationError):
        parse_onexbet_dashboard(hydration([metadata(**changes)]) + row(), config(), observed_at=NOW)


def test_no_inference_from_visible_day_month_time_or_fake_freshness():
    item = metadata()
    del item["startTimestamp"], item["startUnixTimestamp"]
    with pytest.raises(SourceConfigurationError, match="full start timestamps"):
        parse_onexbet_dashboard(hydration([item]) + row(), config(), observed_at=NOW)
    with pytest.raises(SourceConfigurationError):
        parse_onexbet_dashboard(jsonld([ld_metadata(startDate="2026-11-04T18:45:00")]) + row(), config(), observed_at=NOW)


def test_conflicting_invalid_hydration_cannot_be_rescued_by_valid_jsonld():
    html = jsonld() + hydration([metadata(startTimestamp=1)]) + row()
    quotes, rejected = parse_onexbet_dashboard(html, config(), observed_at=NOW)
    assert quotes == [] and rejected == 2


def test_league_constant_filters_metadata_instead_of_relabelling_it():
    html = hydration() + row()
    assert parse_onexbet_dashboard(html, config(league="Other League"), observed_at=NOW)[0] == []
    quotes, _ = parse_onexbet_dashboard(html, config(league=" EXAMPLE   LEAGUE "), observed_at=NOW)
    assert quotes[0].league == "Example League"


@pytest.mark.parametrize("constants", [{"rules": ""}, {"rules": "  "}, {"rules": None}, {"period": "first_half"}, {"sport": "basketball"}])
def test_adapter_requires_explicit_rules_and_supported_contract(constants):
    with pytest.raises(SourceConfigurationError):
        parse_onexbet_dashboard(hydration() + row(), config(**constants), observed_at=NOW)


def test_wrong_profile_or_naive_observation_is_a_safe_configuration_error():
    with pytest.raises(SourceConfigurationError):
        parse_onexbet_dashboard(hydration() + row(), {**config(), "allowed_hosts": ["evil.example"]}, observed_at=NOW)
    with pytest.raises(SourceConfigurationError):
        parse_onexbet_dashboard(hydration() + row(), config(), url="https://evil.example/en", observed_at=NOW)
    with pytest.raises(SourceConfigurationError):
        parse_onexbet_dashboard(hydration() + row(), config(), observed_at=NOW.replace(tzinfo=None))


def test_cdn_resource_allowance_never_expands_fixture_or_document_hosts():
    settings = {**config(), "allowed_hosts": ["al-1xbet.com", "v3.traincdn.com"]}
    assert len(parse_onexbet_dashboard(hydration() + row(), settings, observed_at=NOW)[0]) == 3
    assert parse_onexbet_dashboard(hydration() + row(route="https://v3.traincdn.com" + ROUTE), settings, observed_at=NOW)[0] == []
    with pytest.raises(SourceConfigurationError):
        parse_onexbet_dashboard(hydration() + row(), settings, url="https://v3.traincdn.com/en", observed_at=NOW)
    with pytest.raises(SourceConfigurationError):
        parse_onexbet_dashboard(hydration() + row(), settings, source_id="custom", observed_at=NOW)


@pytest.mark.parametrize("schedule", [
    jsonld([ld_metadata(url="https://v3.traincdn.com" + ROUTE)]),
    hydration([metadata(url="https://v3.traincdn.com" + ROUTE)]),
])
def test_cdn_resource_allowance_cannot_authorize_cross_host_metadata(schedule):
    settings = {**config(), "allowed_hosts": ["al-1xbet.com", "v3.traincdn.com"]}
    with pytest.raises(SourceConfigurationError, match="No usable 1XBet fixture metadata"):
        parse_onexbet_dashboard(schedule + row(), settings, observed_at=NOW)


@pytest.mark.parametrize("changes", [{"isLive": True}, {"isGameOver": True}, {"isSubGame": True}, {"isNotStarted": False}])
def test_jsonld_explicit_started_or_partial_fixture_flags_are_rejected(changes):
    with pytest.raises(SourceConfigurationError):
        parse_onexbet_dashboard(jsonld([ld_metadata(**changes)]) + row(), config(), observed_at=NOW)


def test_malformed_metadata_error_does_not_echo_script_contents():
    secret = "sensitive-script-content"
    html = '<script type="application/ld+json">{' + secret + "}</script>" + row()
    with pytest.raises(SourceConfigurationError) as error:
        parse_onexbet_dashboard(html, config(), observed_at=NOW)
    assert secret not in str(error.value)


def test_nested_script_is_data_and_no_python_or_javascript_is_executed(monkeypatch):
    html = hydration() + '<script>window.__V3_HOST_APP__ = dangerousFunction();</script>' + row()

    def forbidden(*args, **kwargs):
        raise AssertionError("Executable evaluation was attempted")

    with monkeypatch.context() as context:
        context.setattr(builtins, "eval", forbidden)
        context.setattr(builtins, "exec", forbidden)
        quotes, rejected = parse_onexbet_dashboard(html, config(), observed_at=NOW)
    assert len(quotes) == 3 and rejected == 0


def test_invalid_metadata_record_is_counted_without_discarding_valid_records():
    html = hydration([None, metadata()]) + row()
    quotes, rejected = parse_onexbet_dashboard(html, config(), observed_at=NOW)
    assert len(quotes) == 3 and rejected == 1


def test_metadata_prices_are_ignored_in_favour_of_visible_dom_prices():
    item = metadata(markets=[{"odds": "999"}], source_updated_at="2030-01-01T00:00:00Z")
    quotes, _ = parse_onexbet_dashboard(hydration([item]) + row(), config(), observed_at=NOW)
    assert quotes[0].odds == Decimal("2.601") and quotes[0].source_updated_at is None


@pytest.mark.asyncio
async def test_browser_fetch_pipeline_uses_adapter_without_generic_field_mapping(monkeypatch):
    from arbscanner.connectors import onexbet, scraper

    settings = {**config(), "adapter": "1xbet_dashboard", "url": BASE,
                "mode": "browser", "rules_confirmed": True,
                "allowed_hosts": ["al-1xbet.com", "v3.traincdn.com"],
                "max_pages": 1, "min_interval_seconds": 10,
                "wait_selector": '.dashboard-game-action-bar[islive="false"]'}
    page = AsyncMock(return_value=(BASE, hydration() + row()))
    monkeypatch.setattr(scraper, "browser_html", page)
    monkeypatch.setattr(onexbet, "utcnow", lambda: NOW)
    result = await fetch_source("1xbet", settings)
    assert result.status == "ok" and len(result.quotes) == 3
    assert result.metadata["source_timestamp_available"] is False
    assert all(quote.event_id == "456" and quote.starts_at == START and quote.observed_at == NOW
               and quote.source_updated_at is None for quote in result.quotes)
    assert [quote.odds for quote in result.quotes] == [Decimal("2.601"), Decimal("3.60"), Decimal("2.95")]
    page.assert_awaited_once_with(BASE, settings, settings["allowed_hosts"])
