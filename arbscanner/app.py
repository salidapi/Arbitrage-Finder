"""Local HTTP application. No remote hosting, scheduled scans, or bet placement."""
import asyncio
from datetime import datetime
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .demo import demo_quotes
from .engine import scan_quotes
from .models import Quote, Settings, utcnow
from .storage import Store

ROOT = Path(__file__).resolve().parent.parent


class SourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    config: dict[str, Any]


class CredentialUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str = Field(min_length=8, max_length=512, pattern=r"^[A-Za-z0-9_\-]+$")


class ImportQuotes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quotes: list[Quote] = Field(min_length=1, max_length=10000)


def create_app(data_dir: Path | None = None):
    from .connectors import fetch_source, get_profiles, list_api_sports
    store = Store(data_dir or Path(os.environ.get("ARBSCANNER_DATA_DIR", Path.cwd() / ".data")))
    app = FastAPI(title="Arbitrage Finder", docs_url=None, redoc_url=None)
    app.state.store = store
    scan_lock = asyncio.Lock()
    existing = {s["id"] for s in store.sources()}
    for profile in get_profiles():
        source_id = profile.get("id", profile.get("source_id"))
        if source_id and source_id not in existing:
            store.save_source({"id": source_id, "name": profile.get("name", source_id),
                "enabled": False, "config": profile.get("config", profile.get("default_config", {})),
                "status": "unconfigured", "message": "Configure and verify this source before enabling.",
                "last_scan_at": None})

    @app.middleware("http")
    async def protect_local(request: Request, call_next):
        host = urlsplit("//" + request.headers.get("host", "")).hostname
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return JSONResponse({"detail": "This application accepts localhost requests only"}, 403)
        if request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
                return JSONResponse({"detail": "Cross-origin access is disabled"}, 403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Cross-site access is disabled"}, 403)
            if request.method in {"POST", "PUT", "PATCH"}:
                if request.headers.get("content-type", "").split(";")[0] != "application/json":
                    return JSONResponse({"detail": "Send application/json"}, 415)
                # Bound chunked uploads as well as declared content lengths.
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 5 * 1024 * 1024:
                        return JSONResponse({"detail": "Request exceeds 5 MiB limit"}, 413)
                request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RuntimeError)
    async def safe_error(request, exc):
        return JSONResponse({"detail": "Local data or credential operation failed. Check file access or re-enter the API key."}, 500)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc):
        # Pydantic's default error includes rejected input, including secret values.
        errors = [{"loc": list(error["loc"]), "type": error["type"], "msg": error["msg"]}
                  for error in exc.errors()]
        return JSONResponse({"detail": errors}, 422)

    @app.get("/api/state")
    async def state():
        history = store.history(1)
        try:
            has_key = bool(store.credential("odds-api"))
        except RuntimeError:
            has_key = False
        return {"settings": store.settings().model_dump(mode="json"), "sources": store.sources(),
                "api_key_present": has_key, "last_scan": history[0] if history else None}

    @app.put("/api/settings")
    async def save_settings(value: Settings):
        store.put("settings", value.model_dump(mode="json"))
        return {"saved": True, "settings": value.model_dump(mode="json")}

    @app.put("/api/sources/{source_id}")
    async def save_source(source_id: str, value: SourceUpdate):
        if scan_lock.locked():
            raise HTTPException(409, "Wait for the current scan before editing sources")
        rows = {s["id"]: s for s in store.sources()}
        if source_id not in rows:
            raise HTTPException(404, "Unknown source")
        # Secrets have a dedicated encrypted field, never a public config field.
        def has_secret(obj):
            if isinstance(obj, dict):
                return any(any(part in key.casefold() for part in ("key", "token", "secret", "password", "cookie", "authorization")) or has_secret(val) for key, val in obj.items())
            if isinstance(obj, list):
                return any(has_secret(val) for val in obj)
            if isinstance(obj, str) and obj.startswith(("http://", "https://")):
                parsed = urlsplit(obj)
                return bool(parsed.username or parsed.password) or any(
                    any(word in key.casefold() for word in ("key", "token", "secret", "password", "auth", "cookie"))
                    for key, _ in parse_qsl(parsed.query))
            return False
        if has_secret(value.config):
            raise HTTPException(422, "Keep credentials out of source JSON; use the dedicated API key setting")
        try:
            interval = float(value.config.get("min_interval_seconds", 30))
            if not 10 <= interval <= 3600:
                raise ValueError
        except (ValueError, TypeError):
            raise HTTPException(422, "min_interval_seconds must be a number between 10 and 3600") from None
        row = rows[source_id]
        row.update(enabled=value.enabled, config=value.config, status="unconfigured", message="Configuration changed; run a scan to check it.")
        store.save_source(row)
        return {"saved": True}

    @app.put("/api/credentials/odds-api")
    async def credential(value: CredentialUpdate):
        if scan_lock.locked():
            raise HTTPException(409, "Wait for the current scan before editing credentials")
        store.set_credential("odds-api", value.api_key)
        return {"saved": True, "api_key_present": True}

    @app.delete("/api/credentials/odds-api")
    async def remove_credential():
        if scan_lock.locked():
            raise HTTPException(409, "Wait for the current scan before editing credentials")
        store.delete_credential("odds-api")
        return {"deleted": True, "api_key_present": False}

    catalog_last_requested = None

    @app.post("/api/catalog/sports")
    async def sports_catalog():
        nonlocal catalog_last_requested
        if catalog_last_requested and (utcnow() - catalog_last_requested).total_seconds() < 10:
            raise HTTPException(429, "Wait 10 seconds between catalog requests")
        catalog_last_requested = utcnow()
        return await list_api_sports(store.credential("odds-api"))

    async def run_scan(imported: list[Quote] | None = None):
        if scan_lock.locked():
            raise HTTPException(409, "A scan is already running")
        async with scan_lock:
            settings = store.settings()
            started = utcnow()
            mode = "import" if imported is not None else settings.mode
            quotes = []
            results = []
            warnings = []
            if imported is not None:
                quotes = imported
                warnings.append("Imported data, not a live scan. Freshness and source authenticity depend on your input.")
            elif mode == "demo":
                quotes = demo_quotes()
                warnings.append("DEMO: entirely synthetic prices and events. No bookmaker has been contacted.")
            else:
                sources = [s for s in store.sources() if s["enabled"]]
                if not sources:
                    warnings.append("No live sources enabled. Configure public scrapers or an optional free-plan API before scanning.")
                sem = asyncio.Semaphore(2)

                async def collect(source):
                    now = utcnow()
                    try:
                        interval = float(source["config"].get("min_interval_seconds", 30))
                        if not 10 <= interval <= 3600:
                            raise ValueError
                    except (ValueError, TypeError):
                        return {"id": source["id"], "status": "error", "message": "Invalid min_interval_seconds; configure a number between 10 and 3600.", "quote_count": 0}, []
                    if source["last_scan_at"] and (now - datetime.fromisoformat(source["last_scan_at"])).total_seconds() < interval:
                        return {"id": source["id"], "status": "cooldown", "message": f"Wait at least {interval:g} seconds between source requests.", "quote_count": 0}, []
                    source["last_scan_at"] = now.isoformat()
                    store.save_source(source)
                    try:
                        async with sem:
                            result = await asyncio.wait_for(fetch_source(source["id"], source["config"], store.credential("odds-api") if source["id"] == "the_odds_api" else None), timeout=90)
                        status = result.status
                        message = result.message
                        data = result.quotes if status == "ok" else []
                        metadata = result.metadata
                    except Exception:
                        status, message, data, metadata = "error", "Source failed. Check public access, mappings and configuration; no credentials are included in this error.", [], {}
                    source.update(status=status, message=message)
                    store.save_source(source)
                    return {"id": source["id"], "status": status, "message": message, "quote_count": len(data), "metadata": metadata}, data

                for summary, data in await asyncio.gather(*(collect(source) for source in sources)):
                    results.append(summary)
                    quotes.extend(data)
                if not quotes:
                    names = {source["id"]: source["name"] for source in sources}
                    for result in results:
                        warnings.append(f"{names.get(result['id'], result['id'])} [{result['status']}]: {result['message']}")
            output = scan_quotes(quotes, settings)
            value = {"id": str(uuid4()), "mode": mode, "started_at": started.isoformat(),
                     "completed_at": utcnow().isoformat(), "quote_count": len(quotes), "sources": results,
                     "quote_samples": [quote.model_dump(mode="json") for quote in quotes[:100]],
                     "settings": settings.model_dump(mode="json"), "warnings": warnings, **output}
            store.save_scan(value)
            return value

    @app.post("/api/scan")
    async def scan():
        return await run_scan()

    @app.post("/api/import")
    async def import_quotes(value: ImportQuotes):
        return await run_scan(value.quotes)

    @app.get("/api/history")
    async def history():
        return {"scans": store.history()}

    packaged = Path(__file__).resolve().parent
    pdf_dir = packaged / "documents" if (packaged / "documents").is_dir() else ROOT / "docs" / "pdf"

    @app.get("/api/documents")
    async def documents():
        return {"documents": [{"name": p.name, "url": "/documents/" + p.name} for p in sorted(pdf_dir.glob("*.pdf"))]}

    @app.get("/documents/{name}")
    async def pdf(name: str):
        if Path(name).name != name or not name.endswith(".pdf") or not (pdf_dir / name).is_file():
            raise HTTPException(404, "Document not found")
        return FileResponse(pdf_dir / name, media_type="application/pdf", filename=name)

    static = packaged / "static" if (packaged / "static").is_dir() else ROOT / "static"
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="dashboard")
    return app
