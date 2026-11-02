"""Conservative event/contract matching and Decimal stake allocation."""
from collections import Counter, defaultdict
from datetime import datetime
from datetime import timedelta
from decimal import Decimal, ROUND_DOWN
from itertools import product
import unicodedata

from .models import Quote, Settings, utcnow

CENT = Decimal("0.01")
OUTCOMES = {
    "h2h_2way": ("home", "away"), "h2h_3way": ("home", "draw", "away"),
    "totals": ("over", "under"), "spreads": ("home", "away"),
}


def normalized(text: str) -> str:
    # Preserve punctuation/diacritics so distinct team identities are not merged.
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def contract_key(q: Quote) -> tuple:
    # Exact scheduled instant, participants in source orientation, sport AND league.
    # Source event IDs are intentionally local to connectors and not cross-book IDs.
    return (normalized(q.sport), normalized(q.league), normalized(q.home), normalized(q.away),
            q.starts_at, q.market, normalized(q.period), normalized(q.rules), q.line, q.currency)


def rounded_plan(quotes: list[Quote], budget: Decimal):
    """Test all penny neighbours of the proportional allocation; never exceed budget."""
    reciprocal = sum(Decimal(1) / q.odds for q in quotes)
    ideal = [(budget / q.odds / reciprocal).quantize(CENT, rounding=ROUND_DOWN) for q in quotes]
    best = None
    # With at most three legs, at most two leftover pennies need distributing.
    for offsets in product(range(len(quotes)), repeat=len(quotes)):
        stakes = [stake + CENT * offset for stake, offset in zip(ideal, offsets)]
        total = sum(stakes)
        if total > budget or any(stake <= 0 for stake in stakes):
            continue
        payouts = [(stake * quote.odds).quantize(CENT, rounding=ROUND_DOWN) for stake, quote in zip(stakes, quotes)]
        profit = min(payouts) - total
        roi = profit / total * 100
        candidate = (roi, profit, total, stakes, payouts)
        if best is None or candidate[:3] > best[:3]:
            best = candidate
    return best


def scan_quotes(quotes: list[Quote], settings: Settings, now: datetime | None = None) -> dict:
    now = now or utcnow()
    rejected = Counter()
    groups = defaultdict(list)
    for q in quotes:
        reason = None
        if q.starts_at <= now:
            reason = "already_started"
        elif q.observed_at > now:
            reason = "future_timestamp"
        elif (now - q.observed_at).total_seconds() > settings.max_age_seconds:
            reason = "stale_observation"
        elif q.source_updated_at and (now - q.source_updated_at).total_seconds() > settings.max_age_seconds:
            reason = "stale_source"
        elif settings.require_source_timestamps and q.source_updated_at is None:
            reason = "unknown_source_age"
        elif q.currency != settings.currency:
            reason = "currency_mismatch"
        elif settings.sports_filter and normalized(settings.sports_filter) not in normalized(q.sport):
            reason = "sport_filter"
        elif settings.leagues_filter and normalized(settings.leagues_filter) not in normalized(q.league):
            reason = "league_filter"
        if reason:
            rejected[reason] += 1
        else:
            groups[contract_key(q)].append(q)
    opportunities = []
    for rows in groups.values():
        ref = rows[0]
        expected = OUTCOMES[ref.market]
        # Conflicting quotes at an identical timestamp invalidate that book/outcome.
        latest = {}
        conflicts = set()
        for q in rows:
            key = (normalized(q.bookmaker), q.outcome)
            if key not in latest or q.observed_at > latest[key].observed_at:
                latest[key] = q
                conflicts.discard(key)
            elif q.observed_at == latest[key].observed_at and q.odds != latest[key].odds:
                conflicts.add(key)
        if conflicts:
            rejected["conflicting_quotes"] += len(conflicts)
        usable = [q for key, q in latest.items() if key not in conflicts]
        if any(not any(q.outcome == outcome for q in usable) for outcome in expected):
            rejected["incomplete_market"] += 1
            continue
        # Search coherent timestamp windows. A globally best price may be too old
        # relative to another leg while a slightly lower price is compatible.
        best = None
        reason = "quote_time_skew"
        seen = set()
        for start in sorted({q.source_updated_at or q.observed_at for q in usable}):
            end = start + timedelta(seconds=settings.source_skew_seconds)
            window = [q for q in usable if start <= (q.source_updated_at or q.observed_at) <= end]
            if any(not any(q.outcome == outcome for q in window) for outcome in expected):
                continue
            chosen = [max((q for q in window if q.outcome == outcome), key=lambda q: q.odds) for outcome in expected]
            candidates = [chosen]
            if len({normalized(q.bookmaker) for q in chosen}) < 2:
                candidates = []
                for i, outcome in enumerate(expected):
                    alternatives = [q for q in window if q.outcome == outcome and normalized(q.bookmaker) != normalized(chosen[i].bookmaker)]
                    if alternatives:
                        candidate = chosen.copy()
                        candidate[i] = max(alternatives, key=lambda q: q.odds)
                        candidates.append(candidate)
                if not candidates and reason == "quote_time_skew":
                    reason = "single_bookmaker"
            for candidate in candidates:
                fingerprint = tuple((q.bookmaker, q.outcome, q.odds, q.observed_at) for q in candidate)
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                implied = sum(Decimal(1) / q.odds for q in candidate)
                if implied >= 1:
                    if reason != "below_threshold_after_rounding":
                        reason = "no_arbitrage"
                    continue
                plan = rounded_plan(candidate, settings.bankroll)
                if plan is None or plan[1] <= 0 or plan[0] < Decimal(str(settings.minimum_profit)):
                    reason = "below_threshold_after_rounding"
                    continue
                if best is None or plan[:3] > best[0][:3]:
                    best = (plan, candidate)
        if best is None:
            rejected[reason] += 1
            continue
        plan, chosen = best
        roi, profit, total, stakes, payouts = plan
        warnings = ["Fees, taxes, stake limits, payout caps and actual bet acceptance are not modelled. Verify every leg manually."]
        if any(q.source_updated_at is None for q in chosen):
            warnings.append("Source odds age is unknown; timestamps only confirm page retrieval.")
        opportunities.append({
            "event": f"{ref.home} vs {ref.away}", "home": ref.home, "away": ref.away,
            "sport": ref.sport, "league": ref.league, "starts_at": ref.starts_at.isoformat(),
            "market": ref.market, "period": ref.period, "rules": ref.rules,
            "line": str(ref.line) if ref.line is not None else None,
            "roi_percent": float(roi), "total_stake": str(total), "worst_profit": str(profit),
            "currency": ref.currency, "warnings": warnings,
            "legs": [{"bookmaker": q.bookmaker, "outcome": q.outcome, "odds": str(q.odds),
                      "stake": str(stake), "payout": str(payout), "observed_at": q.observed_at.isoformat(),
                      "source_updated_at": q.source_updated_at.isoformat() if q.source_updated_at else None,
                      "source": q.source, "url": q.url} for q, stake, payout in zip(chosen, stakes, payouts)],
        })
    opportunities.sort(key=lambda row: row["roi_percent"], reverse=True)
    return {"opportunities": opportunities, "rejected": dict(rejected), "eligible_market_count": len(groups)}
