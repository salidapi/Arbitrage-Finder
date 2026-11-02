"""Contract tests use synthetic pages; they do not claim live bookmaker support."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest

from arbscanner.connectors import fetch_source, get_profiles
from arbscanner.connectors.base import SourceBlocked, SourceConfigurationError
from arbscanner.connectors.network import detect_challenge, robots_allowed, validate_public_url
from arbscanner.connectors.odds_api import fetch_odds_api, parse_odds_api
from arbscanner.connectors.parsers import parse_html, parse_json, path_values

NOW = datetime.now(timezone.utc)
START = (NOW + timedelta(days=1)).isoformat()


def constants():
    return {"sport": "soccer", "league": "Example League", "period": "full_time", "rules": "regulation", "currency": "EUR", "market": "h2h_3way"}


def test_profiles_are_explicitly_unverified_with_regional_domains():
    profiles = {p["id"]: p for p in get_profiles()}
    assert profiles["bet105"]["domains"] == ["bet105.ag"]
    assert profiles["1xbet"]["domains"] == ["al-1xbet.com"]
    assert all(p["verified"] is False for p in profiles.values())
    assert all(p["default_config"]["rules_confirmed"] is False for p in profiles.values())


def test_flat_json_explicit_mapping_with_status_filter():
    config = {"items_path": "events", "active_path": "state", "active_values": ["open"], "constants": constants(),
              "mapping": {"home": "home", "away": "away", "starts_at": "start", "outcome": {"path": "side", "values": {"1": "home", "X": "draw", "2": "away"}}, "odds": "price", "source_updated_at": "updated"}}
    row = {"home": "Alpha", "away": "Beta", "start": START, "side": "1", "price": "2.60", "updated": NOW.isoformat(), "state": "open"}
    quotes, rejected = parse_json({"events": [row, dict(row, state="suspended")]}, config, "bet365", "https://www.bet365.com/", NOW)
    assert len(quotes) == rejected == 1
    assert quotes[0].odds == Decimal("2.60")
    assert quotes[0].outcome == "home"
    assert quotes[0].source_updated_at == NOW


def test_nested_json_event_market_quote_scopes():
    data = {"events": [{"name": {"home": "Alpha", "away": "Beta"}, "start": START,
                        "markets": [{"kind": "winner", "outcomes": [{"code": "1", "price": 2.5}, {"code": "X", "price": 3.5}]}]}]}
    config = {"events_path": "events", "markets_path": "markets", "outcomes_path": "outcomes", "constants": constants(),
              "mapping": {"home": "$event.name.home", "away": "$event.name.away", "starts_at": "$event.start", "outcome": {"path": "$quote.code", "values": {"1": "home", "X": "draw"}}, "odds": "$quote.price"}}
    quotes, rejected = parse_json(data, config, "stake", "https://stake.com/", NOW)
    assert len(quotes) == 2 and rejected == 0
    assert quotes[0].source_updated_at is None  # Never pretend retrieval is the source update.
    assert quotes[1].outcome == "draw"


def test_mapping_rejects_missing_timezone_and_ambiguous_outcomes():
    config = {"constants": dict(constants(), home="Alpha", away="Beta"), "mapping": {"starts_at": "start", "outcome": "side", "odds": "price"}}
    quotes, rejected = parse_json([{"start": "2030-01-01T12:00:00", "side": "home", "price": 2.5}, {"start": START, "side": "1", "price": 2.5}], config, "bet105", "https://bet105.ag/", NOW)
    assert quotes == [] and rejected == 2


def test_html_scoped_fields_and_suspension_filter():
    html = f'''<section class="event" data-start="{START}"><b class="home">Alpha</b><b class="away">Beta</b>
        <div class="quote" data-side="1"><span class="price">2.5</span></div>
        <div class="quote" data-side="X"><span class="price">3.6</span><i class="suspended"></i></div></section>'''
    config = {"event_selector": ".event", "quote_selector": ".quote", "inactive_selector": ".suspended", "constants": constants(),
              "mapping": {"home": {"selector": ".home", "scope": "event"}, "away": {"selector": ".away", "scope": "event"},
                          "starts_at": {"scope": "event", "attr": "data-start"}, "outcome": {"attr": "data-side", "values": {"1": "home", "X": "draw"}}, "odds": ".price"}}
    quotes, rejected = parse_html(html, config, "marathonbet", "https://www.marathonbet.com/en/", NOW)
    assert len(quotes) == rejected == 1
    assert quotes[0].home == "Alpha" and quotes[0].outcome == "home"


def test_path_language_has_no_code_execution():
    assert path_values({"a": [{"x": 1}, {"x": 2}]}, "a.*.x") == [1, 2]
    assert path_values({"a": [4]}, "a.0") == [4]
    assert path_values({}, "__import__('os').system('echo nope')") == []


@pytest.mark.parametrize("format_name,raw_prices,expected,rejected_count", [
    ("american", ["+150", "-200", "0", "+99", "-99", "suspended", "NaN", "Infinity"], [Decimal("2.5"), Decimal("1.5")], 6),
    ("fractional", ["5/2", "1/2", "0/1", "1/0", "-1/2", "1/-2", "suspended", "NaN/2"], [Decimal("3.5"), Decimal("1.5")], 6),
])
def test_explicit_odds_format_conversion_and_row_rejections(format_name, raw_prices, expected, rejected_count):
    config = {"constants": dict(constants(), home="Alpha", away="Beta", starts_at=START, outcome="home"),
              "mapping": {"odds": {"path": "price", "format": format_name}}}
    quotes, rejected = parse_json([{"price": price} for price in raw_prices], config, "bet105", "https://bet105.ag/", NOW)
    assert [quote.odds for quote in quotes] == expected
    assert rejected == rejected_count


def test_html_explicit_fractional_mapping_keeps_valid_rows_when_other_rows_invalid():
    config = {"quote_selector": ".quote", "constants": dict(constants(), home="Alpha", away="Beta", starts_at=START, outcome="home"),
              "mapping": {"odds": {"selector": ".price", "format": "fractional"}}}
    html = '<div class="quote"><span class="price">5/2</span></div><div class="quote"><span class="price">0/0</span></div>'
    quotes, rejected = parse_html(html, config, "bet105", "https://bet105.ag/", NOW)
    assert len(quotes) == rejected == 1
    assert quotes[0].odds == Decimal("3.5")


@pytest.mark.asyncio
async def test_scraper_remains_unconfigured_until_explicit_setup():
    result = await fetch_source("bet365", {})
    assert result.status == "unconfigured" and not result.quotes
    result = await fetch_source("bet365", {"url": "https://www.bet365.com/"})
    assert result.status == "unconfigured" and not result.quotes


@pytest.mark.asyncio
async def test_scraper_real_fetch_pipeline_uses_declared_mapping(monkeypatch):
    from arbscanner.connectors import scraper
    body = f'{{"events":[{{"home":"Alpha","away":"Beta","start":"{START}","side":"home","price":2.6}}]}}'
    page = AsyncMock(return_value=("https://bet105.ag/", body))
    monkeypatch.setattr(scraper, "fetch_public_page", page)
    config = {"url": "https://bet105.ag/", "mode": "json", "rules_confirmed": True, "items_path": "events", "constants": constants(), "mapping": {"home": "home", "away": "away", "starts_at": "start", "outcome": "side", "odds": "price"}}
    result = await fetch_source("bet105", config)
    assert result.status == "ok" and len(result.quotes) == 1
    assert result.metadata["source_timestamp_available"] is False
    page.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://example.com/", "https://localhost/", "https://127.0.0.1/", "https://user:pass@example.com/", "https://example.com:444/", "https://[::1]/"])
async def test_ssrf_rejects_nonpublic_and_credential_urls(url):
    with pytest.raises((SourceConfigurationError, SourceBlocked)):
        await validate_public_url(url)


@pytest.mark.asyncio
async def test_robots_disallow_stops_before_target(monkeypatch):
    from arbscanner.connectors import network
    request = AsyncMock(return_value=("https://example.com/robots.txt", 200, "User-agent: *\nDisallow: /odds\n"))
    monkeypatch.setattr(network, "_request", request)
    async with httpx.AsyncClient() as client:
        with pytest.raises(SourceBlocked, match="robots"):
            await robots_allowed(client, "https://example.com/odds", ["example.com"], 2)
    assert request.await_count == 1


def test_challenges_are_not_bypassed():
    with pytest.raises(SourceBlocked):
        detect_challenge("Please verify you are human")


def api_config():
    return {"sports": ["soccer_epl"], "bookmakers": ["onexbet"], "markets": ["h2h", "spreads"], "regions": ["eu"], "rules_confirmed": True, "rules_by_sport": {"soccer_epl": "regulation"}}


def api_payload():
    return [{"id": "e1", "sport_key": "soccer_epl", "sport_title": "EPL", "home_team": "Alpha", "away_team": "Beta", "commence_time": START,
             "bookmakers": [{"key": "onexbet", "last_update": NOW.isoformat(), "markets": [
                 {"key": "h2h", "outcomes": [{"name": "Alpha", "price": 2.5}, {"name": "Draw", "price": 3.5}, {"name": "Beta", "price": 3.0}]},
                 {"key": "spreads", "outcomes": [{"name": "Alpha", "price": 2.0, "point": -1.5}, {"name": "Beta", "price": 2.0, "point": 1.5}]}]}]}]


def test_odds_api_normalizes_3way_and_complementary_handicap():
    quotes, rejected = parse_odds_api(api_payload(), api_config(), NOW)
    assert len(quotes) == 5 and rejected == 0
    assert {q.market for q in quotes} == {"h2h_3way", "spreads"}
    assert {q.line for q in quotes if q.market == "spreads"} == {Decimal("-1.5")}
    assert {q.bookmaker for q in quotes} == {"1xbet"}


def test_odds_api_filters_unselected_books_and_unconfirmed_rules():
    assert parse_odds_api(api_payload(), dict(api_config(), bookmakers=["different"]), NOW)[0] == []
    assert parse_odds_api(api_payload(), dict(api_config(), rules_by_sport={}), NOW)[0] == []


@pytest.mark.asyncio
async def test_api_requires_key_and_never_defaults_to_all_sports():
    assert (await fetch_odds_api({}, None)).status == "unconfigured"
    assert (await fetch_odds_api({}, "not-a-real-key")).status == "unconfigured"


@pytest.mark.asyncio
async def test_api_limits_manual_calls_and_preserves_quota(monkeypatch):
    from arbscanner.connectors import odds_api
    read = AsyncMock(return_value=(200, api_payload(), {"x-requests-remaining": "100"}))
    monkeypatch.setattr(odds_api, "_json_get", read)
    config = dict(api_config(), sports=["soccer_epl", "soccer_other"], rules_by_sport={"soccer_epl": "regulation", "soccer_other": "regulation"}, max_requests=1)
    result = await fetch_odds_api(config, "not-a-real-key")
    assert result.status == "ok" and len(result.quotes) == 5
    assert result.metadata["requests"] == 1 and read.await_count == 1
    assert result.metadata["quota"]["x-requests-remaining"] == "100"


@pytest.mark.asyncio
async def test_api_never_echoes_key_or_remote_error_details(monkeypatch):
    from arbscanner.connectors import odds_api
    monkeypatch.setattr(odds_api, "_json_get", AsyncMock(side_effect=RuntimeError("apiKey=super-secret-key")))
    result = await fetch_odds_api(api_config(), "super-secret-key")
    assert result.status == "error"
    assert "super-secret-key" not in result.model_dump_json()
