"""Persistence and key-handling tests use isolated disposable directories."""
from datetime import datetime, timedelta, timezone
import os

from cryptography.fernet import Fernet
import pytest

from arbscanner.models import Settings
from arbscanner.storage import Store


def test_settings_and_sources_survive_store_reopen(tmp_path):
    store = Store(tmp_path)
    store.put("settings", Settings(minimum_profit=2.5, bankroll="250.50").model_dump(mode="json"))
    source = {"id": "fixture", "enabled": True, "config": {"url": "https://example.com"}}
    store.save_source(source)
    reopened = Store(tmp_path)
    assert reopened.settings().minimum_profit == 2.5
    assert str(reopened.settings().bankroll) == "250.50"
    assert reopened.sources() == [source]


def test_api_key_is_encrypted_and_survives_reopen(tmp_path):
    secret = "test_key_only_not_real_9Q24fT"
    store = Store(tmp_path)
    assert store.credential("odds-api") is None
    store.set_credential("odds-api", secret)
    ciphertext = store.get("credential:odds-api")
    assert ciphertext != secret
    assert secret.encode() not in store.path.read_bytes()
    assert secret.encode() not in store.keypath.read_bytes()
    assert Store(tmp_path).credential("odds-api") == secret
    store.delete_credential("odds-api")
    assert Store(tmp_path).credential("odds-api") is None


@pytest.mark.skipif(os.name == "nt", reason="Windows file protection uses filesystem ACLs")
def test_private_files_have_owner_only_permissions(tmp_path):
    store = Store(tmp_path / "private")
    assert store.directory.stat().st_mode & 0o777 == 0o700
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert store.keypath.stat().st_mode & 0o777 == 0o600


def test_wrong_valid_encryption_key_fails_without_revealing_secret(tmp_path):
    secret = "example_secret_key_123456"
    store = Store(tmp_path)
    store.set_credential("odds-api", secret)
    store.keypath.write_bytes(Fernet.generate_key())
    replaced = Store(tmp_path)
    with pytest.raises(RuntimeError) as caught:
        replaced.credential("odds-api")
    assert secret not in str(caught.value)
    replaced.set_credential("odds-api", "replacement_key_123456")
    assert replaced.credential("odds-api") == "replacement_key_123456"


def test_scan_history_is_newest_first_and_bounded_to_100(tmp_path):
    store = Store(tmp_path)
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    for index in range(105):
        store.save_scan({"id": str(index), "started_at": (now + timedelta(seconds=index)).isoformat(), "mode": "demo"})
    assert len(store.history()) == 20
    history = store.history(200)
    assert len(history) == 100
    assert history[0]["id"] == "104"
    assert history[-1]["id"] == "5"
    assert store.history(1)[0]["id"] == "104"


def test_parameterized_keys_do_not_change_schema(tmp_path):
    store = Store(tmp_path)
    key = "x'); DROP TABLE kv; --"
    store.put(key, {"value": "still data"})
    assert store.get(key) == {"value": "still data"}
    store.put("ordinary", 2)
    assert store.get("ordinary") == 2
