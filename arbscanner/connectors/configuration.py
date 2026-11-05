"""Check setup before making paid or public network requests."""
from .parsers import REQUIRED


def scraper_setup_issues(source_id: str, config: dict) -> list[str]:
    """Return safe field names and guidance, never user-provided field values."""
    issues = []
    mapping = config.get("mapping")
    constants = config.get("constants")
    if not isinstance(mapping, dict):
        mapping = {}
    if not isinstance(constants, dict):
        constants = {}
    adapter = config.get("adapter")
    if adapter not in (None, "", "1xbet_dashboard"):
        issues.append("The selected bookmaker adapter is not supported.")
    if adapter == "1xbet_dashboard" and source_id != "1xbet":
        issues.append("The 1XBet dashboard adapter belongs to the 1XBet source.")
    if adapter == "1xbet_dashboard":
        # The adapter supplies identity, schedule, participants, market and price.
        if not isinstance(constants.get("rules"), str) or not constants["rules"].strip():
            issues.append("Set constants.rules to the settlement contract you have verified.")
        if config.get("mode", "html") == "json":
            issues.append("The 1XBet dashboard adapter reads HTML; choose html or browser mode.")
    else:
        missing = []
        for field in sorted(REQUIRED):
            constant = constants.get(field)
            constant_present = constant is not None and (not isinstance(constant, str) or bool(constant.strip()))
            spec = mapping.get(field)
            mapped = isinstance(spec, str) and bool(spec.strip()) or isinstance(spec, dict) and bool(spec)
            if not constant_present and not mapped:
                missing.append(field)
        if missing:
            issues.append("Missing required fields: " + ", ".join(missing) + ".")
        if "starts_at" in missing:
            issues.append("Map a verified event start with a timezone, or use a supported bookmaker adapter; a displayed HH:MM clock is insufficient.")
        if config.get("mode", "html") in ("html", "browser") and not config.get("quote_selector"):
            issues.append("Set quote_selector to the offered selection rows.")
        if not mapping:
            issues.append("Add a field mapping for the source's actual content.")
    if config.get("rules_confirmed") is not True:
        issues.append("Market settlement and suspended-selection handling are not confirmed (rules_confirmed is false).")
    return issues
