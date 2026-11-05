"""Common results and profiles; a profile is not a verified live integration."""
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from arbscanner.models import Quote


class SourceResult(BaseModel):
    source_id: str
    status: Literal["ok", "error", "unconfigured", "blocked"]
    message: str
    quotes: list[Quote] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


PROFILES = [
    {"id": "bet365", "name": "Bet365", "kind": "scraper", "domains": ["bet365.com"], "verified": False},
    {"id": "stake", "name": "Stake", "kind": "scraper", "domains": ["stake.com"], "verified": False},
    {"id": "1xbet", "name": "1XBet", "kind": "scraper", "domains": ["al-1xbet.com"], "verified": False},
    {"id": "marathonbet", "name": "Marathonbet", "kind": "scraper", "domains": ["marathonbet.com"], "verified": False},
    {"id": "bet105", "name": "Bet105", "kind": "scraper", "domains": ["bet105.ag"], "verified": False},
    {"id": "custom", "name": "Custom public source", "kind": "scraper", "domains": [], "verified": False},
    {"id": "the_odds_api", "name": "The Odds API (optional free-tier key)", "kind": "api", "domains": ["api.the-odds-api.com"], "verified": False},
]

DEFAULT_URLS = {"bet365": "https://www.bet365.com/", "stake": "https://stake.com/", "1xbet": "https://al-1xbet.com/en", "marathonbet": "https://www.marathonbet.com/en/", "bet105": "https://bet105.ag/", "custom": ""}


def default_config(profile: dict) -> dict:
    if profile["kind"] == "api":
        return {"sports": [], "bookmakers": [], "markets": ["h2h"], "regions": ["eu"],
                "max_requests": 2, "currency": "EUR", "rules_confirmed": False, "rules_by_sport": {}}
    if profile["id"] == "1xbet":
        return {"adapter": "1xbet_dashboard", "mode": "browser", "url": DEFAULT_URLS["1xbet"],
                "allowed_hosts": ["al-1xbet.com", "v3.traincdn.com"],
                "wait_selector": ".dashboard-game:has(.dashboard-game-action-bar[islive='false'])",
                "min_interval_seconds": 10, "max_pages": 1, "pages": [], "rules_confirmed": False,
                "constants": {"period": "full_time", "rules": "", "currency": "EUR"}}
    return {"mode": "html", "url": DEFAULT_URLS[profile["id"]], "allowed_hosts": list(profile["domains"]),
            "min_interval_seconds": 10, "max_pages": 1, "pages": [], "rules_confirmed": False,
            "event_selector": "", "quote_selector": "", "mapping": {},
            "constants": {"sport": "", "league": "", "period": "full_time", "rules": "", "currency": "EUR"}}


def get_profiles() -> list[dict]:
    """Expose evidence rather than treating a named scraper as ready to use."""
    return [dict(p, default_config=default_config(p), supported_modes=(["html", "json", "browser"] if p["kind"] == "scraper" else ["api"]),
                 setup_note=("Requires a public URL, verified field mapping, and confirmed settlement rules. No site-specific selectors have been live-validated."
                             if p["kind"] == "scraper" else "Requires your key and explicit sport selection. Free-tier quota and bookmaker coverage must be checked with the provider; no paid calls are selected automatically."))
            for p in PROFILES]


class SourceBlocked(ValueError):
    """Access/robots/challenge denial; retrying cannot make permission appear."""


class SourceConfigurationError(ValueError):
    """A mapping or source setting is incomplete."""
