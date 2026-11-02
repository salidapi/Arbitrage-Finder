"""Bounded HTTPS reads. Never follows unchecked redirects or reaches local hosts."""
import asyncio
import ipaddress
import socket
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from .base import SourceBlocked, SourceConfigurationError

USER_AGENT = "ArbitrageFinder/1.0 (public pre-match research; no login)"
MAX_BYTES = 5_000_000
_last_requests: dict[str, float] = {}
_host_locks: dict[str, asyncio.Lock] = {}


async def validate_public_url(url: str, allowed_hosts: list[str] | None = None) -> str:
    """Validate every destination, including redirects. DNS rebinding still requires OS isolation."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise SourceConfigurationError("Malformed source URL") from exc
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or port not in (None, 443):
        raise SourceConfigurationError("Use an HTTPS URL on port 443 without credentials")
    if parsed.fragment or len(url) > 4096:
        raise SourceConfigurationError("Remove URL fragments and use a URL shorter than 4096 characters")
    if allowed_hosts and not any(host == h.lower() or host.endswith("." + h.lower()) for h in allowed_hosts):
        raise SourceConfigurationError("URL hostname is outside this source's configured allowed hosts")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise SourceConfigurationError("Local and private destinations are forbidden")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise SourceConfigurationError("Private or special-use IP addresses are forbidden")
    try:
        addresses = await asyncio.wait_for(asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM), timeout=5)
    except (socket.gaierror, TimeoutError) as exc:
        raise SourceBlocked("Source hostname could not be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
        raise SourceConfigurationError("Source must resolve only to public Internet addresses")
    return host


async def _request(client: httpx.AsyncClient, url: str, allowed_hosts: list[str], interval: float) -> tuple[str, int, str]:
    for _ in range(4):
        host = await validate_public_url(url, allowed_hosts)
        lock = _host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            delay = interval - (time.monotonic() - _last_requests.get(host, 0))
            if delay > 0:
                await asyncio.sleep(delay)
            _last_requests[host] = time.monotonic()
            async with client.stream("GET", url, follow_redirects=False) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise SourceBlocked("Source returned an invalid redirect")
                    url = urljoin(url, location)
                    continue
                if response.status_code in (401, 403, 429, 451):
                    raise SourceBlocked(f"Source denied access (HTTP {response.status_code}); no bypass attempted")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise SourceBlocked("Source response exceeds the 5 MB safety limit")
                encoding = response.encoding or "utf-8"
                return url, response.status_code, data.decode(encoding, errors="replace")
    raise SourceBlocked("Too many source redirects")


async def robots_allowed(client: httpx.AsyncClient, url: str, allowed_hosts: list[str], interval: float) -> float:
    parsed = urlsplit(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    _, status, body = await _request(client, robots_url, allowed_hosts, interval)
    if status in (404, 410):
        return interval
    if status != 200:
        raise SourceBlocked("Could not establish robots.txt permission")
    parser = RobotFileParser()
    parser.parse(body.splitlines())
    if not parser.can_fetch(USER_AGENT, url):
        raise SourceBlocked("robots.txt disallows this page for the scraper")
    crawl_delay = parser.crawl_delay(USER_AGENT) or parser.crawl_delay("*") or interval
    return max(interval, float(crawl_delay))


def detect_challenge(body: str) -> None:
    sample = body[:250_000].lower()
    if any(token in sample for token in ("cf-chl-", "verify you are human", "checking your browser", "captcha", "access denied")):
        raise SourceBlocked("Public page returned an access challenge; no bypass attempted")


async def fetch_public_page(url: str, allowed_hosts: list[str], interval: float = 10) -> tuple[str, str]:
    interval = max(2, min(float(interval), 120))
    async with httpx.AsyncClient(timeout=httpx.Timeout(25), headers={"User-Agent": USER_AGENT}, trust_env=True) as client:
        await validate_public_url(url, allowed_hosts)
        interval = await robots_allowed(client, url, allowed_hosts, interval)
        final_url, status, body = await _request(client, url, allowed_hosts, interval)
        if status != 200:
            raise SourceBlocked(f"Source page returned HTTP {status}")
        # Redirects may change the path to a robots-disallowed page.
        if final_url != url:
            await robots_allowed(client, final_url, allowed_hosts, interval)
        detect_challenge(body)
        return final_url, body
