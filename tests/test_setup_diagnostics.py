"""Incomplete setup is actionable before acquisition; all pages here are synthetic."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest

from arbscanner.app import create_app
from arbscanner.connectors import scraper
from arbscanner.connectors.configuration import scraper_setup_issues


def partial_config(source_id):
    """Mirror the missing fields in the shared drafts without using captured pages."""
    config = {
        "mode": "browser",
        "url": "https://al-1xbet.com/en" if source_id == "1xbet" else "https://www.bet365.com/",
        "allowed_hosts": ["al-1xbet.com"] if source_id == "1xbet" else ["bet365.com"],
        "min_interval_seconds": 10,
        "max_pages": 1,
        "pages": [],
        "rules_confirmed": False,
        "event_selector": ".event",
        "quote_selector": ".quote",
        "inactive_selector": ".suspended",
        "mapping": {
            "home": {"selector": ".home", "scope": "event"},
            "away": {"selector": ".away", "scope": "event"},
            "odds": ".price",
        },
        "constants": {
            "sport": "soccer", "league": "Example League", "market": "h2h_3way",
            "period": "full_time", "rules": "", "currency": "EUR",
        },
    }
    if source_id == "1xbet":
        config["mapping"]["outcome"] = {
            "selector": ".selection", "attr": "aria-label",
            "values": {"W1": "home", "X": "draw", "W2": "away"},
        }
    return config


@pytest.fixture
def acquisition(monkeypatch):
    """Any acquisition call in a preflight test is a regression, even if caught."""
    browser = AsyncMock(side_effect=AssertionError("Unexpected browser acquisition"))
    public = AsyncMock(side_effect=AssertionError("Unexpected HTTP acquisition"))
    monkeypatch.setattr(scraper, "browser_html", browser)
    monkeypatch.setattr(scraper, "fetch_public_page", public)
    return browser, public


def assert_no_acquisition(acquisition):
    for request in acquisition:
        request.assert_not_awaited()


@pytest.mark.parametrize("source_id,missing", [
    ("1xbet", "Missing required fields: rules, starts_at."),
    ("bet365", "Missing required fields: outcome, rules, starts_at."),
])
async def test_shared_partial_drafts_explain_missing_fields_without_request(source_id, missing, acquisition):
    result = await scraper.fetch_scraper(source_id, partial_config(source_id))

    assert result.status == "unconfigured"
    assert result.quotes == []
    assert missing in result.message
    assert "rules_confirmed is false" in result.message
    assert "timezone" in result.message
    assert "No source request was made" in result.message
    assert result.metadata["request_made"] is False
    assert missing in result.metadata["setup_issues"]
    assert_no_acquisition(acquisition)


@pytest.mark.parametrize("source_id", ["1xbet", "bet365"])
async def test_confirmation_alone_cannot_make_partial_draft_ready(source_id, acquisition):
    config = partial_config(source_id)
    config["rules_confirmed"] = True

    result = await scraper.fetch_scraper(source_id, config)

    assert result.status == "unconfigured"
    assert "starts_at" in result.message
    assert "rules" in result.message
    assert "rules_confirmed is false" not in result.message
    assert_no_acquisition(acquisition)


async def test_confirmed_complete_generic_mapping_still_fetches_and_parses(acquisition):
    start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    config = partial_config("bet365")
    config.update(mode="html", rules_confirmed=True)
    config["constants"]["rules"] = "regulation"
    config["mapping"].update({
        "starts_at": {"scope": "event", "attr": "data-start"},
        "outcome": {"attr": "data-side"},
    })
    html = f'''<section class="event" data-start="{start}">
        <b class="home">Alpha</b><b class="away">Beta</b>
        <div class="quote" data-side="home"><b class="price">2.60</b></div>
        <div class="quote" data-side="draw"><b class="price">3.40</b><i class="suspended"></i></div>
    </section>'''
    browser, public = acquisition
    public.side_effect = None
    public.return_value = (config["url"], html)

    result = await scraper.fetch_scraper("bet365", config)

    assert result.status == "ok"
    assert len(result.quotes) == 1
    assert result.quotes[0].home == "Alpha"
    assert result.quotes[0].outcome == "home"
    assert result.quotes[0].odds == Decimal("2.60")
    assert result.quotes[0].starts_at.isoformat() == start
    assert result.quotes[0].source_updated_at is None
    assert result.metadata["source_timestamp_available"] is False
    assert result.metadata["rejected_rows"] == 1
    browser.assert_not_awaited()
    public.assert_awaited_once_with(config["url"], config["allowed_hosts"], 10)


async def test_dashboard_adapter_needs_rules_and_confirmation_not_css_fields(acquisition):
    config = {
        "url": "https://al-1xbet.com/en", "mode": "browser",
        "adapter": "1xbet_dashboard", "rules_confirmed": False, "constants": {"rules": ""},
    }

    result = await scraper.fetch_scraper("1xbet", config)

    assert result.status == "unconfigured"
    assert "constants.rules" in result.message
    assert "rules_confirmed is false" in result.message
    assert "Missing required fields" not in result.message
    assert "quote_selector" not in result.message
    assert_no_acquisition(acquisition)

    ready = deepcopy(config)
    ready["rules_confirmed"] = True
    ready["constants"]["rules"] = "regulation"
    assert scraper_setup_issues("1xbet", ready) == []


@pytest.mark.parametrize("source_id,changes,expected", [
    ("1xbet", {"adapter": "unsupported_example_adapter"}, "adapter is not supported"),
    ("bet365", {}, "adapter belongs to the 1XBet source"),
    ("1xbet", {"mode": "json"}, "adapter reads HTML; choose html or browser mode"),
])
async def test_adapter_misconfiguration_is_explicit_before_requests(source_id, changes, expected, acquisition):
    config = {
        "url": "https://al-1xbet.com/en", "mode": "browser", "adapter": "1xbet_dashboard",
        "rules_confirmed": True, "constants": {"rules": "regulation"},
    }
    config.update(changes)

    result = await scraper.fetch_scraper(source_id, config)

    assert result.status == "unconfigured"
    assert expected in result.message
    assert result.metadata["request_made"] is False
    assert_no_acquisition(acquisition)


def test_zero_quote_scan_promotes_named_source_diagnostics_without_key_leaks(tmp_path, acquisition):
    key = "synthetic_setup_diagnostics_api_key_12345"
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1:8000") as client:
        saved_key = client.put("/api/credentials/odds-api", json={"api_key": key})
        assert saved_key.status_code == 200
        for source_id in ("1xbet", "bet365"):
            saved = client.put(f"/api/sources/{source_id}", json={
                "enabled": True, "config": partial_config(source_id),
            })
            assert saved.status_code == 200

        response = client.post("/api/scan", json={})

        assert response.status_code == 200
        result = response.json()
        assert result["quote_count"] == 0
        assert result["opportunities"] == []
        assert result["quote_samples"] == []
        sources = {source["id"]: source for source in result["sources"]}
        assert set(sources) == {"1xbet", "bet365"}
        for source_id, name in (("1xbet", "1XBet"), ("bet365", "Bet365")):
            source = sources[source_id]
            assert source["status"] == "unconfigured"
            assert source["quote_count"] == 0
            assert source["metadata"]["request_made"] is False
            assert f"{name} [unconfigured]: {source['message']}" in result["warnings"]
        assert "Missing required fields: rules, starts_at." in sources["1xbet"]["message"]
        assert "Missing required fields: outcome, rules, starts_at." in sources["bet365"]["message"]
        assert key not in response.text
        assert key not in client.get("/api/state").text
        assert key not in client.get("/api/history").text
        assert_no_acquisition(acquisition)
