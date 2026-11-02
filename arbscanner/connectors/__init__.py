"""Public connector registry used by the manual scan service."""
from .base import SourceResult, get_profiles
from .odds_api import fetch_odds_api, list_api_sports
from .scraper import fetch_scraper


async def fetch_source(source_id: str, config: dict, api_key: str | None = None) -> SourceResult:
    if source_id == "the_odds_api":
        return await fetch_odds_api(config, api_key)
    return await fetch_scraper(source_id, config, api_key)


__all__ = ["SourceResult", "fetch_source", "get_profiles", "list_api_sports"]
