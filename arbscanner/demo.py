"""Synthetic fixtures. Never returned by a live connector or labelled live odds."""
from datetime import timedelta

from .models import Quote, utcnow


def demo_quotes():
    now = utcnow()
    common = dict(event_id="synthetic-1", sport="Football", league="DEMO league (fictional)",
                  home="Demo North", away="Demo South", starts_at=now + timedelta(days=1),
                  market="h2h_3way", observed_at=now, source_updated_at=now, source="synthetic_demo")
    return [Quote(**common, bookmaker=book, outcome=outcome, odds=odds)
            for book, outcome, odds in [("Demo book A", "home", "3.6"),
                                        ("Demo book B", "draw", "3.6"),
                                        ("Demo book C", "away", "3.6")]]
