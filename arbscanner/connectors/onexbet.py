"""Static, fail-closed joins for the public 1XBet football dashboard.

This adapter reads prices from the DOM and schedule/identity data from JSON.
Embedded JavaScript is never executed, and retrieval time is not price freshness.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
import re
import unicodedata
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from pydantic import ValidationError

from arbscanner.models import Quote, utcnow
from .base import SourceConfigurationError


_HOSTS = frozenset({"al-1xbet.com"})
_GAME_PATH = re.compile(r"^/en/line/(?:football|soccer)/\d+-[^/]+/([1-9]\d*)-([^/]+)/?$")
_HYDRATION_KEY = re.compile(r'"normalizedDataItems-betting/home/line/dashboardStore-games"\s*:\s*')
_JSON_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
_PRICE = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_OUTCOMES = {"W1": "home", "X": "draw", "W2": "away"}
_MAX_CHARS = 8_000_000


@dataclass(frozen=True)
class _Event:
    event_id: str
    home: str
    away: str
    league: str
    starts_at: datetime
    url: str | None = None

    def contract(self):
        return (_name(self.home), _name(self.away), _name(self.league), self.starts_at)


def _name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _text(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Missing metadata text")
    return " ".join(value.split())


def _soccer(value) -> bool:
    return isinstance(value, str) and _name(value) in {"football", "soccer", "association football"}


def _ordinary(home: str, away: str, slug: str = "") -> bool:
    names = {_name(home), _name(away)}
    return (len(names) == 2 and names != {"home", "away"}
            and not any("special bet" in name for name in names)
            and not any(part in slug.casefold() for part in ("special-bet", "home-away", "aggregate")))


def _event_url(value, base: str, hosts: set[str]) -> tuple[str, str, str]:
    if not isinstance(value, str) or not value:
        raise ValueError("Missing fixture URL")
    parsed = urlsplit(urljoin(base, value))
    if (parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username or parsed.password
            or parsed.port not in (None, 443) or parsed.query or parsed.fragment):
        raise ValueError("Fixture URL is outside the configured profile")
    match = _GAME_PATH.fullmatch(parsed.path)
    if not match:
        raise ValueError("Not a full-match pre-match football route")
    canonical = urlunsplit(("https", parsed.hostname, parsed.path.rstrip("/"), "", ""))
    return canonical, match.group(1), match.group(2)


def _iso_start(value) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Missing ISO fixture start")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Fixture start needs a timezone")
    return stamp.astimezone(timezone.utc)


def _unix_start(record: dict) -> datetime:
    seconds = []
    for key, divisor in (("startUnixTimestamp", 1), ("startTimestamp", 1000)):
        if key not in record:
            continue
        value = record[key]
        # Strict units and JSON numbers: never guess units from digit count.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Invalid fixture timestamp")
        number = Decimal(str(value)) / divisor
        if not number.is_finite() or number <= 0:
            raise ValueError("Invalid fixture timestamp")
        seconds.append(number)
    if not seconds or any(value != seconds[0] for value in seconds[1:]):
        raise ValueError("Missing or conflicting fixture timestamps")
    return datetime.fromtimestamp(float(seconds[0]), timezone.utc)


def _strict_constant(_value):
    raise ValueError("Non-JSON numeric constant")


_DECODER = json.JSONDecoder(parse_constant=_strict_constant)


def _jsonld_events(value, depth=0):
    if depth > 12:
        return
    if isinstance(value, list):
        for item in value[:5000]:
            yield from _jsonld_events(item, depth + 1)
    elif isinstance(value, dict):
        types = value.get("@type", [])
        if types == "SportsEvent" or isinstance(types, list) and "SportsEvent" in types:
            yield value
        if "@graph" in value:
            yield from _jsonld_events(value["@graph"], depth + 1)


def _ld_event(record: dict, base: str, hosts: set[str]) -> _Event:
    url, event_id, slug = _event_url(record.get("url"), base, hosts)
    home_data, away_data, organizer = (record.get(key) for key in ("homeTeam", "awayTeam", "organizer"))
    if not all(isinstance(item, dict) for item in (home_data, away_data, organizer)):
        raise ValueError("Missing fixture participants or competition")
    sports = [item["sport"] for item in (record, organizer, home_data, away_data) if "sport" in item]
    if not sports or not all(_soccer(sport) for sport in sports):
        raise ValueError("Only association football is supported")
    home, away = _text(home_data.get("name")), _text(away_data.get("name"))
    if not _ordinary(home, away, slug):
        raise ValueError("Not an ordinary fixture")
    # JSON-LD has no isNotStarted flag in the observed page. The /line/ URL,
    # explicit DOM pre-match marker and future authoritative start must agree.
    if (any(key in record and record[key] is not False for key in ("isLive", "isGameOver", "isLong", "isSubGame", "isDummy"))
            or "isNotStarted" in record and record["isNotStarted"] is not True):
        raise ValueError("Fixture has started")
    return _Event(event_id, home, away, _text(organizer.get("name")), _iso_start(record.get("startDate")), url)


def _permanent_id(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not re.fullmatch(r"[1-9]\d*", str(value)):
        raise ValueError("Missing permanent fixture ID")
    return str(value)


def _hydration_event(record: dict, base: str, hosts: set[str]) -> _Event:
    event_id = _permanent_id(record.get("permanentId"))
    if (record.get("isNotStarted") is not True
            or any(key in record and record[key] is not False for key in ("isLive", "isGameOver", "isLong", "isSubGame", "isDummy"))
            or record.get("sectionType", 3) != 3):
        raise ValueError("Not a full-match pre-match fixture")
    if not _soccer(record.get("sportName")):
        raise ValueError("Only association football is supported")
    home, away = _text(record.get("firstOpponentName")), _text(record.get("secondOpponentName"))
    if not _ordinary(home, away, str(record.get("gameNameForUrl", ""))):
        raise ValueError("Not an ordinary fixture")
    route = record.get("url")
    route_fields = [record.get(key) for key in ("sportNameForUrl", "champNameForUrl", "gameNameForUrl")]
    if route is None and all(isinstance(part, str) and part for part in route_fields):
        route = "/en/line/" + "/".join(route_fields)
    canonical = None
    if route is not None:
        canonical, route_id, _ = _event_url(route, base, hosts)
        if route_id != event_id:
            raise ValueError("Fixture route and permanent ID disagree")
    if "gameIdForUrl" in record and str(record["gameIdForUrl"]) != event_id:
        raise ValueError("Fixture route ID and permanent ID disagree")
    return _Event(event_id, home, away, _text(record.get("champName")), _unix_start(record), canonical)


def _hydration_arrays(script: str):
    """Decode known JSON literals in the wrapper, never JavaScript expressions."""
    pending = [(script, 0)]
    seen = set()
    while pending:
        source, depth = pending.pop()
        if source in seen:
            continue
        seen.add(source)
        for match in _HYDRATION_KEY.finditer(source):
            try:
                value, _ = _DECODER.raw_decode(source, match.end())
                if not isinstance(value, list) or len(value) > 5000:
                    raise ValueError("Invalid schedule array")
                yield value
            except (ValueError, RecursionError):
                yield None
        if depth >= 2:
            continue
        for match in _JSON_STRING.finditer(source):
            literal = match.group()
            if "__BETTING_APP__" not in literal and "normalizedDataItems-betting/home/line/dashboardStore-games" not in literal:
                continue
            try:
                decoded = _DECODER.decode(literal)
            except (ValueError, RecursionError):
                continue
            if isinstance(decoded, str):
                pending.append((decoded, depth + 1))


def _metadata(soup: BeautifulSoup, base: str, hosts: set[str]):
    events, blocked_ids, rejected = {}, set(), 0

    def add(record, hydration=False):
        nonlocal rejected
        if not isinstance(record, dict):
            rejected += 1
            return
        try:
            event = (_hydration_event if hydration else _ld_event)(record, base, hosts)
        except (ValueError, TypeError, ArithmeticError, OverflowError, OSError):
            rejected += 1
            # A conflicting schedule must not be rescued by another metadata
            # representation of the same fixture.
            try:
                blocked_ids.add(_permanent_id(record.get("permanentId")) if hydration
                                else _event_url(record.get("url"), base, hosts)[1])
            except (ValueError, TypeError):
                pass
            return
        events.setdefault(event.event_id, []).append(event)

    for script in soup.find_all("script"):
        source = script.string or script.get_text()
        if script.get("type", "").casefold() == "application/ld+json":
            try:
                for record in _jsonld_events(_DECODER.decode(source)):
                    add(record)
            except (ValueError, RecursionError):
                rejected += 1
        elif "window.__V3_HOST_APP__" in source or "window.__BETTING_APP__" in source:
            for records in _hydration_arrays(source):
                if records is None:
                    rejected += 1
                else:
                    for record in records:
                        add(record, hydration=True)
    return events, blocked_ids, rejected


def parse_onexbet_dashboard(html: str, config: dict, source_id: str = "1xbet",
                           url: str = "https://al-1xbet.com/en",
                           observed_at: datetime | None = None) -> tuple[list[Quote], int]:
    """Return DOM 1X2 quotes joined to exact, authoritative pre-match metadata.

    Rejection counts include invalid metadata records, unsupported event rows,
    and unavailable/invalid price cells. The caller enforces rules_confirmed.
    """
    if source_id != "1xbet":
        raise SourceConfigurationError("The 1XBet dashboard adapter is only available for the 1xbet source profile")
    constants = config.get("constants") or {}
    if not isinstance(constants, dict) or not isinstance(constants.get("rules"), str) or not constants["rules"].strip():
        raise SourceConfigurationError("1XBet needs an explicit confirmed full-match settlement rules label in constants.rules")
    if constants.get("period", "full_time") != "full_time":
        raise SourceConfigurationError("The 1XBet dashboard adapter supports full_time football 1X2 only")
    if constants.get("sport") and not _soccer(constants["sport"]):
        raise SourceConfigurationError("The 1XBet dashboard adapter supports association football only")
    if constants.get("league") and not isinstance(constants["league"], str):
        raise SourceConfigurationError("The optional 1XBet league filter must be text")
    allowed = config.get("allowed_hosts", list(_HOSTS))
    if (not isinstance(allowed, list) or not all(isinstance(host, str) for host in allowed)
            or not _HOSTS.intersection(allowed)):
        raise SourceConfigurationError("1XBet allowed_hosts must include the exact al-1xbet.com profile host")
    # The transport may separately allow CDN resource hosts. Those hosts never
    # become fixture/document hosts merely because browser assets need them.
    hosts = set(allowed).intersection(_HOSTS)
    try:
        parsed_base = urlsplit(url)
        if (parsed_base.scheme != "https" or parsed_base.hostname not in hosts or parsed_base.username
                or parsed_base.password or parsed_base.port not in (None, 443)):
            raise ValueError("Invalid profile URL")
    except ValueError:
        raise SourceConfigurationError("1XBet requires an HTTPS URL on the exact configured profile host") from None
    observed_at = observed_at or utcnow()
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise SourceConfigurationError("The observation timestamp must include a timezone")
    if not isinstance(html, str) or len(html) > _MAX_CHARS:
        raise SourceConfigurationError("The 1XBet page is missing or exceeds the parser size limit")
    soup = BeautifulSoup(html, "html.parser")
    events, blocked_ids, rejected = _metadata(soup, url, hosts)
    if not events:
        raise SourceConfigurationError("No usable 1XBet fixture metadata was found; the adapter needs matching SportsEvent JSON-LD or dashboard schedule JSON with full start timestamps")
    quotes = []
    for row in soup.select(".dashboard-game"):
        try:
            bars = row.select(".dashboard-game-action-bar")
            links = row.select("a.dashboard-game-block__link[href]")
            if len(bars) != 1 or bars[0].get("islive") != "false" or len(links) != 1:
                raise ValueError("Not an explicit pre-match row")
            fixture_url, event_id, slug = _event_url(links[0]["href"], url, hosts)
            names = []
            for side in ("first", "second"):
                nodes = row.select(f'[data-test="betting-dashboard-game-{side}-team"] .dashboard-game-team-info__name')
                if len(nodes) != 1:
                    raise ValueError("Ambiguous DOM participants")
                names.append(_text(nodes[0].get_text(" ", strip=True)))
            home, away = names
            candidates = events.get(event_id, [])
            if (not _ordinary(home, away, slug) or event_id in blocked_ids or not candidates
                    or len({candidate.contract() for candidate in candidates}) != 1):
                raise ValueError("Missing or conflicting fixture metadata")
            event = candidates[0]
            if (event.contract()[:2] != (_name(home), _name(away))
                    or any(candidate.url is not None and candidate.url != fixture_url for candidate in candidates)
                    or event.starts_at <= observed_at):
                raise ValueError("Fixture identity or pre-match start does not match")
            if constants.get("league") and _name(constants["league"]) != _name(event.league):
                raise ValueError("Fixture is outside the configured league filter")
            cells = row.select(".dashboard-markets__market")
            buttons = [cell.select("button.ui-market__toggle") for cell in cells]
            labels = [items[0].get("aria-label") if len(items) == 1 else None for items in buttons]
            if len(cells) != 3 or set(labels) != set(_OUTCOMES):
                raise ValueError("Not one unambiguous full-match W1/X/W2 group")
        except (ValueError, TypeError):
            rejected += 1
            continue
        for cell, label in zip(cells, labels):
            # Availability is checked before accessing any numeric price text.
            if (set(cell.get("class", [])) & {"ui-market--locked", "ui-market--empty"}
                    or cell.has_attr("disabled") or cell.get("aria-disabled") == "true"
                    or cell.select_one(".ui-market--locked, .ui-market--empty, [disabled], [aria-disabled='true'], .ui-market__lock")):
                rejected += 1
                continue
            try:
                values = cell.select(".ui-market__value")
                if len(values) != 1:
                    raise ValueError("Missing price")
                price = values[0].get_text("", strip=True)
                if not _PRICE.fullmatch(price):
                    raise ValueError("Not decimal odds")
                quotes.append(Quote(event_id=event_id, sport="soccer", league=event.league, home=home, away=away,
                                    starts_at=event.starts_at, bookmaker=source_id, market="h2h_3way",
                                    period="full_time", rules=constants["rules"].strip(), outcome=_OUTCOMES[label],
                                    odds=Decimal(price), observed_at=observed_at, source_updated_at=None,
                                    source=source_id, url=fixture_url, currency=constants.get("currency", "EUR")))
            except (ValueError, TypeError, ArithmeticError, ValidationError):
                rejected += 1
    return quotes, rejected
