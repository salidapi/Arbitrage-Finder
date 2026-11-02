"""Small SQLite store with locally encrypted secrets and bounded scan history."""
import json
import os
from pathlib import Path
import sqlite3
from threading import RLock

from cryptography.fernet import Fernet, InvalidToken

from .models import Settings


class Store:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / "scanner.sqlite3"
        self.keypath = directory / "secret.key"
        if not self.keypath.exists():
            fd = os.open(self.keypath, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(Fernet.generate_key())
        self.cipher = Fernet(self.keypath.read_bytes())
        self.lock = RLock()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scans (id TEXT PRIMARY KEY, created TEXT NOT NULL, value TEXT NOT NULL);
            """)
        if os.name != "nt":
            self.path.chmod(0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def get(self, key, default=None):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self.lock, self.connect() as db:
            db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, json.dumps(value)))

    def settings(self):
        return Settings.model_validate(self.get("settings", {}))

    def set_credential(self, name, value):
        self.put("credential:" + name, self.cipher.encrypt(value.encode()).decode())

    def credential(self, name):
        value = self.get("credential:" + name)
        if not value:
            return None
        try:
            return self.cipher.decrypt(value.encode()).decode()
        except InvalidToken:
            raise RuntimeError("Credential key does not match this data store; re-enter the API key") from None

    def delete_credential(self, name):
        with self.lock, self.connect() as db:
            db.execute("DELETE FROM kv WHERE key=?", ("credential:" + name,))

    def sources(self):
        with self.lock, self.connect() as db:
            rows = db.execute("SELECT value FROM sources ORDER BY id").fetchall()
        return [json.loads(row[0]) for row in rows]

    def save_source(self, value):
        with self.lock, self.connect() as db:
            db.execute("INSERT OR REPLACE INTO sources VALUES (?,?)", (value["id"], json.dumps(value)))

    def save_scan(self, value):
        with self.lock, self.connect() as db:
            db.execute("INSERT INTO scans VALUES (?,?,?)", (value["id"], value["started_at"], json.dumps(value)))
            db.execute("DELETE FROM scans WHERE id NOT IN (SELECT id FROM scans ORDER BY created DESC LIMIT 100)")

    def history(self, limit=20):
        with self.lock, self.connect() as db:
            rows = db.execute("SELECT value FROM scans ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(row[0]) for row in rows]
