"""Declarative field extraction for public pages, with no invented site selectors."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from bs4 import BeautifulSoup
from pydantic import ValidationError

from arbscanner.models import Quote
from .base import SourceConfigurationError

FIELDS = {"event_id", "sport", "league", "home", "away", "starts_at", "bookmaker", "market", "period", "rules", "line", "outcome", "odds", "observed_at", "source_updated_at", "source", "url", "currency"}
REQUIRED = {"sport", "league", "home", "away", "starts_at", "market", "rules", "outcome", "odds"}


def path_values(data: Any, path: str) -> list[Any]:
    """A small, non-executable path language: dotted keys, list indexes, and *."""
    if not path or path == "$":
        return [data]
    parts = path.removeprefix("$.").split(".")
    current = [data]
    for part in parts:
        following = []
        for value in current:
            if part == "*":
                if isinstance(value, list):
                    following.extend(value)
                elif isinstance(value, dict):
                    following.extend(value.values())
            elif isinstance(value, dict) and part in value:
                following.append(value[part])
            elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
                following.append(value[int(part)])
        current = following
    return current


def _rows(data: Any, path: str) -> list[Any]:
    values = path_values(data, path)
    return [row for value in values for row in (value if isinstance(value, list) else [value])]


def _contexts(data: Any, config: dict):
    """Flat rows or nested event -> market -> outcome documents are supported."""
    if "events_path" not in config:
        for row in _rows(data, config.get("items_path", "")):
            yield {"root": data, "event": row, "market": row, "quote": row}
        return
    for event in _rows(data, config["events_path"]):
        markets = _rows(event, config.get("markets_path", ""))
        for market in markets:
            for quote in _rows(market, config.get("outcomes_path", "")):
                yield {"root": data, "event": event, "market": market, "quote": quote}


def _context_path(context: dict, path: str):
    scope, separator, remainder = path.removeprefix("$").partition(".")
    if path.startswith("$") and scope in context:
        values = path_values(context[scope], remainder if separator else "")
    else:
        values = path_values(context["quote"], path)
    return values[0] if len(values) == 1 else None


def _quote(values: dict, source_id: str, url: str, observed_at: datetime) -> Quote:
    for field in ("source_updated_at", "line"):
        if values.get(field) in (None, ""):
            values.pop(field, None)
    values.setdefault("source", source_id)
    values.setdefault("bookmaker", source_id)
    values.setdefault("url", url)
    # Retrieval time is distinct from the bookmaker's last update time.
    values["observed_at"] = observed_at
    values.setdefault("period", "full_time")
    values.setdefault("currency", "EUR")
    missing = REQUIRED - values.keys()
    if missing or any(values.get(key) in (None, "") for key in REQUIRED):
        raise SourceConfigurationError("Field mapping is missing required event/market values")
    if not values.get("event_id"):
        # This is a local source identity, not a cross-book event-matching assertion.
        values["event_id"] = "|".join(str(values[k]) for k in ("sport", "league", "home", "away", "starts_at"))
    if not isinstance(values["starts_at"], datetime):
        stamp = str(values["starts_at"]).replace("Z", "+00:00")
        try:
            values["starts_at"] = datetime.fromisoformat(stamp)
        except ValueError as exc:
            raise SourceConfigurationError("starts_at must be an ISO 8601 timestamp with timezone") from exc
    if values["starts_at"].tzinfo is None:
        raise SourceConfigurationError("starts_at needs an explicit UTC offset")
    if values.get("source_updated_at"):
        stamp = values["source_updated_at"]
        if not isinstance(stamp, datetime):
            stamp = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise SourceConfigurationError("source_updated_at needs an explicit UTC offset")
        values["source_updated_at"] = stamp
    # Do not guess locale, fractional odds, or American price formats.
    for field in ("odds", "line"):
        if field in values:
            values[field] = Decimal(str(values[field]).strip())
    return Quote(**values)


def _transform(value: Any, spec: dict):
    """Explicit value maps handle source codes without guessing their meaning."""
    if value is None:
        return None
    if "values" in spec:
        translations = spec["values"]
        if not isinstance(translations, dict):
            raise SourceConfigurationError("values must be an explicit source-to-canonical mapping")
        value = translations.get(str(value))
        if value is None:
            return None
    if spec.get("format") in ("unix", "unix_ms"):
        seconds = float(value) / (1000 if spec["format"] == "unix_ms" else 1)
        value = datetime.fromtimestamp(seconds, timezone.utc)
    elif spec.get("format") == "american":
        price = Decimal(str(value).strip())
        if not price.is_finite() or abs(price) < 100:
            raise ValueError("American odds must be at least +100 or at most -100")
        value = Decimal(1) + (price / Decimal(100) if price >= 100 else Decimal(100) / abs(price))
    elif spec.get("format") == "fractional":
        parts = str(value).strip().split("/")
        if len(parts) != 2:
            raise ValueError("Fractional odds require a numerator and denominator")
        numerator, denominator = (Decimal(part.strip()) for part in parts)
        if not numerator.is_finite() or not denominator.is_finite() or numerator < 0 or denominator <= 0:
            raise ValueError("Fractional odds require a nonnegative numerator and positive denominator")
        value = Decimal(1) + numerator / denominator
    if "multiply" in spec:
        value = Decimal(str(value)) * Decimal(str(spec["multiply"]))
    return value


def parse_json(data: Any, config: dict, source_id: str, url: str, observed_at: datetime | None = None) -> tuple[list[Quote], int]:
    mapping = config.get("mapping") or {}
    constants = config.get("constants") or {}
    if not mapping or not isinstance(mapping, dict) or not isinstance(constants, dict):
        raise SourceConfigurationError("A field mapping and constants object are required")
    observed_at = observed_at or datetime.now(timezone.utc)
    quotes, rejected = [], 0
    for context in _contexts(data, config):
        values = {key: value for key, value in constants.items() if key in FIELDS}
        invalid_value = False
        for field, spec in mapping.items():
            if field not in FIELDS:
                continue
            if isinstance(spec, str):
                value = _context_path(context, spec)
            elif isinstance(spec, dict):
                value = _context_path(context, spec.get("path", field))
                if value is None:
                    value = spec.get("default")
                try:
                    value = _transform(value, spec)
                except (ArithmeticError, ValueError, TypeError):
                    invalid_value = True
                    break
            else:
                raise SourceConfigurationError("JSON mapping entries must be paths or objects")
            if value is not None:
                values[field] = value
        if invalid_value:
            rejected += 1
            continue
        try:
            # Explicit suspension/status fields must be handled before quotes enter the engine.
            status_path = config.get("active_path")
            if status_path and _context_path(context, status_path) not in config.get("active_values", [True, "active", "open"]):
                rejected += 1
                continue
            quotes.append(_quote(values, source_id, url, observed_at))
        except (ValidationError, ArithmeticError, ValueError, TypeError):
            rejected += 1
    return quotes, rejected


def parse_html(html: str, config: dict, source_id: str, url: str, observed_at: datetime | None = None) -> tuple[list[Quote], int]:
    mapping = config.get("mapping") or {}
    constants = config.get("constants") or {}
    selector = config.get("quote_selector")
    if not selector or not mapping:
        raise SourceConfigurationError("HTML scraping needs quote_selector and a field mapping")
    soup = BeautifulSoup(html, "html.parser")
    event_selector = config.get("event_selector")
    events = soup.select(event_selector) if event_selector else [soup]
    observed_at = observed_at or datetime.now(timezone.utc)
    quotes, rejected = [], 0
    for event in events:
        for row in event.select(selector):
            values = {key: value for key, value in constants.items() if key in FIELDS}
            invalid_value = False
            for field, spec in mapping.items():
                if field not in FIELDS:
                    continue
                if isinstance(spec, str):
                    spec = {"selector": spec}
                if not isinstance(spec, dict):
                    raise SourceConfigurationError("HTML mapping entries must be CSS selectors or objects")
                scope = event if spec.get("scope") == "event" else row
                node = scope.select_one(spec["selector"]) if spec.get("selector") else scope
                if node is None and spec.get("scope") is None and spec.get("selector"):
                    node = event.select_one(spec["selector"])
                if node:
                    attribute = spec.get("attr", "text")
                    value = node.get_text(" ", strip=True) if attribute == "text" else node.get(attribute)
                    if value is not None:
                        value = value.strip() if isinstance(value, str) else value
                        try:
                            value = _transform(value, spec)
                        except (ArithmeticError, ValueError, TypeError):
                            invalid_value = True
                            break
                        if value is not None:
                            values[field] = value
                elif "default" in spec:
                    try:
                        values[field] = _transform(spec["default"], spec)
                    except (ArithmeticError, ValueError, TypeError):
                        invalid_value = True
                        break
            if invalid_value:
                rejected += 1
                continue
            try:
                if config.get("inactive_selector") and row.select_one(config["inactive_selector"]):
                    rejected += 1
                    continue
                quotes.append(_quote(values, source_id, url, observed_at))
            except (ValidationError, ArithmeticError, ValueError, TypeError):
                rejected += 1
    return quotes, rejected
