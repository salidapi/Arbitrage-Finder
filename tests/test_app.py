"""End-to-end HTTP workflows run locally with mocked acquisition, never real bets."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Event

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

from arbscanner.app import create_app
from arbscanner.connectors.base import SourceResult
from arbscanner.demo import demo_quotes


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1:8000") as value:
        yield value


def settings(client, **changes):
    payload = client.get("/api/state").json()["settings"]
    payload.update(changes)
    response = client.put("/api/settings", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["settings"]


def test_default_live_scan_does_not_fabricate_odds(client):
    state = client.get("/api/state").json()
    assert state["settings"]["mode"] == "live"
    assert state["api_key_present"] is False
    assert state["last_scan"] is None
    assert {"bet365", "stake", "1xbet", "marathonbet", "bet105", "the_odds_api"} <= {row["id"] for row in state["sources"]}
    assert all(not row["enabled"] for row in state["sources"])
    response = client.post("/api/scan", json={})
    assert response.status_code == 200
    scan = response.json()
    assert scan["mode"] == "live"
    assert scan["quote_count"] == 0
    assert scan["opportunities"] == []
    assert scan["sources"] == []
    assert any("No live sources" in message for message in scan["warnings"])


def test_settings_persist_across_app_reopen(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1:8000") as first:
        settings(first, minimum_profit=3.25, bankroll="252.50", max_age_seconds=180, currency="USD")
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1:8000") as second:
        state = second.get("/api/state").json()["settings"]
        assert state["minimum_profit"] == 3.25
        assert state["bankroll"] == "252.50"
        assert state["max_age_seconds"] == 180
        assert state["currency"] == "USD"


def test_demo_scan_is_labeled_and_responds_to_profit_filter(client):
    settings(client, mode="demo", minimum_profit=0)
    result = client.post("/api/scan", json={}).json()
    assert result["mode"] == "demo"
    assert result["quote_count"] == 3
    assert len(result["opportunities"]) == 1
    assert any("synthetic" in warning for warning in result["warnings"])
    assert result["sources"] == []
    assert len(result["quote_samples"]) == 3
    assert all(q["source"] == "synthetic_demo" for q in result["quote_samples"])
    settings(client, minimum_profit=50)
    filtered = client.post("/api/scan", json={}).json()
    assert filtered["opportunities"] == []
    assert filtered["rejected"]["below_threshold_after_rounding"] == 1
    assert client.get("/api/state").json()["last_scan"]["id"] == filtered["id"]
    assert len(client.get("/api/history").json()["scans"]) == 2


def test_quote_import_validates_and_is_labeled_separately_from_live(client):
    rows = [quote.model_dump(mode="json") for quote in demo_quotes()]
    response = client.post("/api/import", json={"quotes": rows})
    assert response.status_code == 200
    result = response.json()
    assert result["mode"] == "import"
    assert result["quote_count"] == 3
    assert len(result["opportunities"]) == 1
    assert any("Imported data" in warning for warning in result["warnings"])
    rows[0]["odds"] = "NaN"
    assert client.post("/api/import", json={"quotes": rows}).status_code == 422
    assert client.post("/api/import", json={"quotes": []}).status_code == 422
    assert len(client.get("/api/history").json()["scans"]) == 1


def test_key_saved_deleted_and_never_echoed_or_stored_plaintext(client, tmp_path):
    key = "synthetic_test_api_key_12345"
    saved = client.put("/api/credentials/odds-api", json={"api_key": key})
    assert saved.status_code == 200
    assert saved.json() == {"saved": True, "api_key_present": True}
    assert key not in saved.text
    assert client.get("/api/state").json()["api_key_present"] is True
    client.post("/api/scan", json={})
    assert key not in client.get("/api/state").text
    assert key not in client.get("/api/history").text
    assert key.encode() not in (tmp_path / "scanner.sqlite3").read_bytes()
    deleted = client.delete("/api/credentials/odds-api")
    assert deleted.status_code == 200
    assert client.get("/api/state").json()["api_key_present"] is False


def test_invalid_key_validation_does_not_echo_supplied_value(client):
    value = "synthetic_secret_key_with_invalid_character!"
    response = client.put("/api/credentials/odds-api", json={"api_key": value})
    assert response.status_code == 422
    assert value not in response.text


@pytest.mark.parametrize("config", [
    {"api_key": "do-not-save"}, {"nested": {"Authorization": "do-not-save"}},
    {"array": [{"cookie": "do-not-save"}]},
    {"url": "https://example.com/feed?api_key=do-not-save"},
    {"url": "https://user:do-not-save@example.com/feed"},
    {"url": "https://example.com/feed?api%5fkey=do-not-save"},
])
def test_source_config_rejects_credentials(client, config):
    response = client.put("/api/sources/bet365", json={"enabled": False, "config": config})
    assert response.status_code == 422
    assert "do-not-save" not in response.text
    assert "do-not-save" not in client.get("/api/state").text


def test_source_configuration_update_and_unknown_id(client):
    config = {"mode": "json", "url": "https://example.com/fixture", "rules_confirmed": False}
    response = client.put("/api/sources/bet365", json={"enabled": True, "config": config})
    assert response.status_code == 200
    row = next(row for row in client.get("/api/state").json()["sources"] if row["id"] == "bet365")
    assert row["enabled"] is True
    assert row["config"] == config
    assert row["status"] == "unconfigured"
    assert client.put("/api/sources/not-real", json={"enabled": True, "config": {}}).status_code == 404


def test_bad_interval_configuration_isolated_as_source_error(client):
    response = client.put("/api/sources/bet365", json={"enabled": True, "config": {"min_interval_seconds": "invalid"}})
    if response.status_code == 422:
        return  # Validation at save time is also a supported, explicit correction.
    assert response.status_code == 200
    result = client.post("/api/scan", json={})
    assert result.status_code == 200
    assert result.json()["opportunities"] == []
    assert result.json()["sources"][0]["status"] in {"error", "unconfigured"}


def test_mock_source_executes_and_cooldown_prevents_second_request(tmp_path, monkeypatch):
    calls = []
    async def fake_fetch(source_id, config, api_key=None):
        calls.append(source_id)
        return SourceResult(source_id=source_id, status="ok", message="Fixture acquisition", quotes=demo_quotes())
    monkeypatch.setattr("arbscanner.connectors.fetch_source", fake_fetch)
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1:8000") as local:
        local.put("/api/sources/bet365", json={"enabled": True, "config": {"min_interval_seconds": 30}})
        first = local.post("/api/scan", json={}).json()
        assert first["sources"][0]["status"] == "ok"
        assert first["quote_count"] == 3
        assert first["opportunities"]
        second = local.post("/api/scan", json={}).json()
        assert second["sources"][0]["status"] == "cooldown"
        assert second["quote_count"] == 0
        assert calls == ["bet365"]


def test_source_failure_does_not_expose_injected_key_or_prevent_other_sources(tmp_path, monkeypatch):
    key = "synthetic_test_api_key_98765"
    seen = {}
    async def fake_fetch(source_id, config, api_key=None):
        seen[source_id] = api_key
        if source_id == "the_odds_api":
            raise ValueError("upstream request contained " + str(api_key))
        return SourceResult(source_id=source_id, status="ok", message="Fixture", quotes=demo_quotes())
    monkeypatch.setattr("arbscanner.connectors.fetch_source", fake_fetch)
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1:8000") as local:
        local.put("/api/credentials/odds-api", json={"api_key": key})
        for source_id in ("bet365", "the_odds_api"):
            local.put(f"/api/sources/{source_id}", json={"enabled": True, "config": {}})
        response = local.post("/api/scan", json={})
        assert response.status_code == 200
        assert seen == {"bet365": None, "the_odds_api": key}
        result = response.json()
        statuses = {row["id"]: row["status"] for row in result["sources"]}
        assert statuses == {"bet365": "ok", "the_odds_api": "error"}
        assert result["opportunities"]
        assert key not in response.text
        assert key not in local.get("/api/state").text
        assert key not in local.get("/api/history").text


def test_concurrent_manual_scan_receives_conflict(tmp_path, monkeypatch):
    entered = Event()
    async def fake_fetch(source_id, config, api_key=None):
        entered.set()
        await asyncio.sleep(0.4)
        return SourceResult(source_id=source_id, status="ok", message="Fixture", quotes=[])
    monkeypatch.setattr("arbscanner.connectors.fetch_source", fake_fetch)
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1:8000") as local:
        local.put("/api/sources/bet365", json={"enabled": True, "config": {}})
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(lambda: local.post("/api/scan", json={}))
            assert entered.wait(timeout=2)
            second = local.post("/api/scan", json={})
            assert second.status_code == 409
            assert local.put("/api/sources/bet365", json={"enabled": False, "config": {}}).status_code == 409
            assert local.put("/api/credentials/odds-api", json={"api_key": "synthetic_test_key_12345"}).status_code == 409
            assert local.delete("/api/credentials/odds-api").status_code == 409
            assert first.result(timeout=3).status_code == 200


@pytest.mark.parametrize("headers", [
    {"Host": "attacker.example"}, {"Origin": "https://attacker.example"},
    {"Origin": "http://localhost:8000"}, {"Sec-Fetch-Site": "cross-site"},
])
def test_cross_site_or_nonlocal_requests_are_rejected(client, headers):
    assert client.get("/api/state", headers=headers).status_code == 403
    assert client.post("/api/scan", json={}, headers=headers).status_code == 403


def test_same_origin_is_allowed_and_responses_have_local_security_headers(client):
    response = client.get("/api/state", headers={"Origin": "http://127.0.0.1:8000"})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_non_json_mutations_and_oversized_requests_rejected(client):
    assert client.post("/api/scan", content="{}").status_code == 415
    response = client.post("/api/scan", content=" " * (5 * 1024 * 1024 + 1), headers={"Content-Type": "application/json"})
    assert response.status_code == 413


def test_wrong_key_reports_absence_without_breaking_state_or_exposing_value(tmp_path):
    app = create_app(tmp_path)
    app.state.store.set_credential("odds-api", "synthetic_test_api_key_12345")
    app.state.store.keypath.write_bytes(Fernet.generate_key())
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1:8000") as local:
        response = local.get("/api/state")
        assert response.status_code == 200
        assert response.json()["api_key_present"] is False
        assert "synthetic_test_api_key" not in response.text
        assert local.delete("/api/credentials/odds-api").status_code == 200


def test_documents_listing_is_bounded_to_pdf_names_and_path_traversal_rejected(client):
    response = client.get("/api/documents")
    assert response.status_code == 200
    assert isinstance(response.json()["documents"], list)
    assert client.get("/documents/not-a-document.txt").status_code == 404
    assert client.get("/documents/..%2Fpyproject.toml").status_code == 404
