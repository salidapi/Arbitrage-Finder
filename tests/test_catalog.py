from fastapi.testclient import TestClient

from arbscanner.app import create_app


def test_catalog_without_key_does_not_request_external_api(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1:8000") as client:
        response = client.post("/api/catalog/sports", json={})
        assert response.status_code == 200
        assert response.json()["status"] == "unconfigured"
        assert response.json()["sports"] == []
        assert client.post("/api/catalog/sports", json={}).status_code == 429


def test_catalog_passes_saved_key_without_echo_and_uses_no_scan_history(tmp_path, monkeypatch):
    key = "synthetic_catalog_key_12345"
    async def catalog(api_key):
        assert api_key == key
        return {"status": "ok", "message": "Synthetic catalog", "sports": [{"key": "soccer_test", "title": "Test league"}], "quota": {"x-requests-remaining": "20"}}
    monkeypatch.setattr("arbscanner.connectors.list_api_sports", catalog)
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1:8000") as client:
        client.put("/api/credentials/odds-api", json={"api_key": key})
        response = client.post("/api/catalog/sports", json={})
        assert response.status_code == 200
        assert response.json()["sports"][0]["key"] == "soccer_test"
        assert key not in response.text
        assert client.get("/api/history").json()["scans"] == []
