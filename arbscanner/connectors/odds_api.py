"""Bounded, opt-in The Odds API v4 reads. Coverage/quotas come from the provider."""
from datetime import datetime, timezone
from decimal import Decimal

import httpx
from pydantic import ValidationError

from arbscanner.models import Quote
from .base import SourceResult

API_ROOT = "https://api.the-odds-api.com/v4"
MARKETS = {"h2h", "totals", "spreads"}
ALIASES = {"onexbet": "1xbet", "1xbet": "1xbet", "bet365": "bet365", "stake": "stake", "marathonbet": "marathonbet", "bet105": "bet105"}
MAX_RESPONSE_BYTES = 10_000_000


def _stamp(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def parse_odds_api(payload: list, config: dict, observed_at: datetime | None = None) -> tuple[list[Quote], int]:
    observed_at = observed_at or datetime.now(timezone.utc)
    selected = set(config.get("bookmakers") or [])
    rules = config.get("rules_by_sport") or {}
    quotes, rejected = [], 0
    for event in payload:
        try:
            home, away = event["home_team"], event["away_team"]
            sport_key = event["sport_key"]
            sport = sport_key.split("_")[0]
            league = event.get("sport_title", sport_key)
            starts_at = _stamp(event["commence_time"])
            # Settlement rules must be verified for this sport/league before comparison.
            rule = rules.get(sport_key)
            if not rule:
                rejected += 1
                continue
            for bookmaker in event.get("bookmakers", []):
                book_key = bookmaker["key"]
                if book_key not in selected:
                    continue
                for market in bookmaker.get("markets", []):
                    key = market["key"]
                    if key not in MARKETS or key not in config.get("markets", ["h2h"]):
                        continue
                    outcomes = market.get("outcomes", [])
                    if key == "h2h":
                        names = {str(outcome.get("name", "")) for outcome in outcomes}
                        if names == {home, away}:
                            canonical = "h2h_2way"
                        elif names == {home, away, "Draw"}:
                            canonical = "h2h_3way"
                        else:
                            rejected += len(outcomes)
                            continue
                    else:
                        canonical = key
                    for outcome in outcomes:
                        name = outcome.get("name")
                        side = "home" if name == home else "away" if name == away else "draw" if name == "Draw" else "over" if name == "Over" else "under" if name == "Under" else None
                        if side is None:
                            rejected += 1
                            continue
                        try:
                            line = None if key == "h2h" else Decimal(str(outcome["point"]))
                            # Canonical spread line is always the home handicap.
                            if key == "spreads" and side == "away":
                                line = -line
                            quotes.append(Quote(event_id=event["id"], sport=sport, league=league, home=home, away=away,
                                                starts_at=starts_at, bookmaker=ALIASES.get(book_key, book_key), market=canonical,
                                                period="full_time", rules=rule, line=line, outcome=side, odds=Decimal(str(outcome["price"])),
                                                observed_at=observed_at, source_updated_at=_stamp(market.get("last_update") or bookmaker.get("last_update")),
                                                source="the_odds_api", url=None, currency=config.get("currency", "EUR")))
                        except (ValueError, TypeError, KeyError, ValidationError):
                            rejected += 1
        except (ValueError, TypeError, KeyError):
            rejected += 1
    return quotes, rejected


def _valid_keys(values):
    return isinstance(values, list) and all(isinstance(v, str) and 0 < len(v) <= 100 and all(c.isalnum() or c == "_" for c in v) for v in values)


async def _json_get(client: httpx.AsyncClient, path: str, params: dict):
    async with client.stream("GET", API_ROOT + path, params=params, follow_redirects=False) as response:
        status = response.status_code
        quota = {name: response.headers.get(name) for name in ("x-requests-remaining", "x-requests-used", "x-requests-last") if name in response.headers}
        if status != 200:
            return status, None, quota
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > MAX_RESPONSE_BYTES:
                raise ValueError("API response exceeds size limit")
        import json
        return status, json.loads(data), quota


async def list_api_sports(api_key: str | None) -> dict:
    """Read the active sports catalog. Its request accounting is provider-controlled."""
    if not api_key:
        return {"status": "unconfigured", "message": "Add your API key in dashboard settings", "sports": []}
    try:
        async with httpx.AsyncClient(timeout=25, trust_env=True) as client:
            status, data, quota = await _json_get(client, "/sports", {"apiKey": api_key})
        if status != 200 or not isinstance(data, list):
            return {"status": "blocked" if status in (401, 403, 429, 451) else "error", "message": f"Sports catalog returned HTTP {status}", "sports": [], "quota": quota}
        sports = [{k: item.get(k) for k in ("key", "group", "title", "description", "active", "has_outrights")} for item in data if isinstance(item, dict) and item.get("active") and not item.get("has_outrights")]
        return {"status": "ok", "message": "Active non-outright sports from provider", "sports": sports, "quota": quota}
    except Exception:
        return {"status": "error", "message": "Sports catalog could not be fetched. Check network access and key permissions.", "sports": []}


async def fetch_odds_api(config: dict, api_key: str | None = None) -> SourceResult:
    source_id = "the_odds_api"
    if not api_key:
        return SourceResult(source_id=source_id, status="unconfigured", message="Add your optional The Odds API key in dashboard settings")
    sports = config.get("sports") or []
    books = config.get("bookmakers") or []
    markets = config.get("markets", ["h2h"])
    regions = config.get("regions", ["eu"])
    if not _valid_keys(sports) or not sports or len(sports) > 8:
        return SourceResult(source_id=source_id, status="unconfigured", message="Choose 1–8 explicit sport keys; no automatic all-sports polling is enabled")
    if not _valid_keys(books) or not books or len(books) > 30:
        return SourceResult(source_id=source_id, status="unconfigured", message="Set 1–30 exact provider bookmaker keys after checking coverage; listed bookmakers are not assumed available")
    if not isinstance(markets, list) or not markets or set(markets) - MARKETS:
        return SourceResult(source_id=source_id, status="unconfigured", message="Choose h2h, totals, and/or spreads; extra per-event markets are not requested automatically")
    if not _valid_keys(regions) or not regions or len(regions) > 2:
        return SourceResult(source_id=source_id, status="unconfigured", message="Choose one or two explicit regions, e.g. ['eu']")
    rules_by_sport = config.get("rules_by_sport") or {}
    if config.get("rules_confirmed") is not True or not isinstance(rules_by_sport, dict) or any(not rules_by_sport.get(sport) for sport in sports):
        return SourceResult(source_id=source_id, status="unconfigured", message="Confirm settlement rules and set rules_by_sport for every selected sport key")
    try:
        maximum = max(1, min(8, int(config.get("max_requests", 2))))
    except (ValueError, TypeError):
        return SourceResult(source_id=source_id, status="unconfigured", message="max_requests must be an integer from 1 to 8")
    sports = sports[:maximum]
    quotes, rejected, requests_done = [], 0, 0
    quota, failures = {}, []
    # Upper bound for standard market/region accounting; provider headers are authoritative.
    estimated_credit_bound = len(sports) * len(set(markets)) * max(len(set(regions)), (len(set(books)) + 9) // 10)
    try:
        async with httpx.AsyncClient(timeout=25, trust_env=True) as client:
            for sport in sports:
                params = {"apiKey": api_key, "regions": ",".join(regions), "markets": ",".join(markets), "bookmakers": ",".join(books), "oddsFormat": "decimal", "dateFormat": "iso"}
                status, payload, quota = await _json_get(client, f"/sports/{sport}/odds", params)
                requests_done += 1
                if status != 200 or not isinstance(payload, list):
                    failures.append(f"{sport}: HTTP {status}")
                    if status in (401, 403, 429, 451):
                        break
                    continue
                parsed, invalid = parse_odds_api(payload, config)
                quotes.extend(parsed)
                rejected += invalid
                remaining = quota.get("x-requests-remaining")
                if remaining is not None:
                    try:
                        if float(remaining) < len(set(markets)) * max(1, (len(set(books)) + 9) // 10):
                            break
                    except ValueError:
                        pass
        metadata = {"requests": requests_done, "request_limit": maximum, "sports_selected": len(config.get("sports", [])), "sports_requested": requests_done, "estimated_credit_upper_bound": estimated_credit_bound, "quota": quota, "rejected_rows": rejected, "failures": failures, "bookmaker_coverage_verified": False}
        if failures:
            # Partial quotes are deliberately discarded to prevent a partial failure appearing healthy.
            return SourceResult(source_id=source_id, status="blocked" if any(code in " ".join(failures) for code in ("401", "403", "429", "451")) else "error", message="Provider request failed: " + "; ".join(failures), metadata=metadata)
        return SourceResult(source_id=source_id, status="ok", message=f"Received {len(quotes)} supported quotes; {requests_done} bounded request(s). Empty coverage is not a working bookmaker integration.", quotes=quotes, metadata=metadata)
    except Exception:
        return SourceResult(source_id=source_id, status="error", message="Provider request failed. Check network access, key permissions, quota, and provider configuration; API-key values are not returned", metadata={"requests": requests_done})
