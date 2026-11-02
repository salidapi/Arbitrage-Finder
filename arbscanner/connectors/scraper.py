"""Anonymous, declaratively configured public-page scrapers for each source profile."""
import asyncio
import json
import os
import shutil
from urllib.parse import urlsplit

import httpx

from .base import PROFILES, SourceBlocked, SourceConfigurationError, SourceResult
from .network import MAX_BYTES, USER_AGENT, detect_challenge, fetch_public_page, robots_allowed, validate_public_url
from .parsers import parse_html, parse_json


async def browser_html(url: str, config: dict, allowed_hosts: list[str]) -> tuple[str, str]:
    """Read a public page in a new empty browser context. Authentication is unsupported."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise SourceConfigurationError("Browser mode needs the optional Playwright package and Chromium") from exc
    await validate_public_url(url, allowed_hosts)
    interval = max(2, float(config.get("min_interval_seconds", 10)))
    async with httpx.AsyncClient(timeout=25, headers={"User-Agent": USER_AGENT}, trust_env=True) as client:
        interval = await robots_allowed(client, url, allowed_hosts, interval)
    await asyncio.sleep(interval)
    async with async_playwright() as playwright:
        launch = {"headless": True}
        # Preserve the platform's proxy route. Never ignore certificate errors.
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if proxy:
            launch["proxy"] = {"server": proxy}
        executable = config.get("browser_executable")
        if executable and executable not in ("chromium", "chromium-browser", "google-chrome"):
            raise SourceConfigurationError("browser_executable must name chromium, chromium-browser, or google-chrome")
        executable = shutil.which(executable) if executable else shutil.which("chromium")
        if executable:
            launch["executable_path"] = executable
        browser = await playwright.chromium.launch(**launch)
        try:
            context = await browser.new_context(user_agent=USER_AGENT, service_workers="block")
            denied = []

            async def guard(route):
                target = route.request.url
                try:
                    await validate_public_url(target, allowed_hosts)
                    if route.request.method != "GET":
                        # No login forms, mutation calls, or consent-changing POST requests.
                        raise SourceBlocked("Browser page requested a non-GET operation")
                    if route.request.resource_type in ("image", "media", "font"):
                        await route.abort()
                    else:
                        await route.continue_()
                except (SourceBlocked, SourceConfigurationError):
                    denied.append(True)
                    await route.abort()

            await context.route("**/*", guard)
            page = await context.new_page()
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            if response is None or response.status in (401, 403, 429, 451):
                raise SourceBlocked("Browser navigation was denied; no bypass attempted")
            if response.status != 200:
                raise SourceBlocked(f"Browser page returned HTTP {response.status}")
            if config.get("wait_selector"):
                await page.wait_for_selector(config["wait_selector"], timeout=10_000)
            final_url = page.url
            await validate_public_url(final_url, allowed_hosts)
            if final_url != url:
                async with httpx.AsyncClient(timeout=25, headers={"User-Agent": USER_AGENT}, trust_env=True) as client:
                    await robots_allowed(client, final_url, allowed_hosts, interval)
            html = await page.content()
            if len(html.encode("utf-8")) > MAX_BYTES:
                raise SourceBlocked("Rendered page exceeds the 5 MB safety limit")
            if await page.locator('input[type="password"]').count():
                raise SourceBlocked("Page requires a login; anonymous scraper stopped")
            detect_challenge(html)
            if denied and not html:
                raise SourceBlocked("Required browser requests were blocked by the source safety policy")
            return final_url, html
        finally:
            await browser.close()


async def fetch_scraper(source_id: str, config: dict, api_key: str | None = None) -> SourceResult:
    profile = next((p for p in PROFILES if p["id"] == source_id and p["kind"] == "scraper"), None)
    if profile is None:
        return SourceResult(source_id=source_id, status="unconfigured", message="Unknown scraper profile")
    if not config.get("url"):
        return SourceResult(source_id=source_id, status="unconfigured", message="Set a public source URL and verified HTML/JSON field mapping first")
    if config.get("rules_confirmed") is not True:
        return SourceResult(source_id=source_id, status="unconfigured", message="Confirm market settlement rules and suspended-odds filtering before enabling this scraper")
    allowed_hosts = config.get("allowed_hosts") or profile["domains"]
    if not allowed_hosts or not isinstance(allowed_hosts, list) or not all(isinstance(h, str) and h and "/" not in h and ":" not in h for h in allowed_hosts):
        return SourceResult(source_id=source_id, status="unconfigured", message="Specify allowed_hosts as public DNS hostnames")
    mode = config.get("mode", "html")
    if mode not in ("html", "json", "browser"):
        return SourceResult(source_id=source_id, status="unconfigured", message="mode must be html, json, or browser")
    additional_pages = config.get("pages") or []
    if not isinstance(config["url"], str) or not isinstance(additional_pages, list) or not all(isinstance(page, str) for page in additional_pages):
        return SourceResult(source_id=source_id, status="unconfigured", message="url must be a string and pages must be a list of URL strings")
    pages = [config["url"]] + additional_pages
    pages = list(dict.fromkeys(pages))
    try:
        maximum = max(1, min(3, int(config.get("max_pages", 3))))
    except (ValueError, TypeError):
        return SourceResult(source_id=source_id, status="unconfigured", message="max_pages must be an integer from 1 to 3")
    pages = pages[:maximum]
    quotes, rejected, fetched_pages = [], 0, 0
    try:
        for url in pages:
            final_url, body = await (browser_html(url, config, allowed_hosts) if mode == "browser" else fetch_public_page(url, allowed_hosts, config.get("min_interval_seconds", 10)))
            if mode == "json":
                data = json.loads(body)
                parsed, invalid = parse_json(data, config, source_id, final_url)
            else:
                parsed, invalid = parse_html(body, config, source_id, final_url)
            quotes.extend(parsed)
            rejected += invalid
            fetched_pages += 1
        if not quotes:
            return SourceResult(source_id=source_id, status="error", message="No valid odds extracted. Check selectors, public accessibility, suspension handling, ISO timestamps, and settlement rules.", metadata={"pages": fetched_pages, "rejected_rows": rejected, "live_verified": False})
        return SourceResult(source_id=source_id, status="ok", message=f"Extracted {len(quotes)} public pre-match quotes; verify regional coverage and freshness before use", quotes=quotes,
                            metadata={"pages": fetched_pages, "rejected_rows": rejected, "source_timestamp_available": any(q.source_updated_at for q in quotes), "mapping_user_configured": True})
    except SourceConfigurationError as exc:
        return SourceResult(source_id=source_id, status="unconfigured", message=str(exc))
    except SourceBlocked as exc:
        return SourceResult(source_id=source_id, status="blocked", message=str(exc), metadata={"pages_completed": fetched_pages})
    except (json.JSONDecodeError, ValueError, TypeError, KeyError):
        return SourceResult(source_id=source_id, status="error", message="Source content or mapping is invalid; check the configured fields and response format")
    except Exception:
        # httpx/Playwright errors can include query-string credentials or raw payloads.
        return SourceResult(source_id=source_id, status="error", message="Source request failed. Check network access, TLS trust, optional browser installation, and public page availability; no login or access bypass was attempted")
