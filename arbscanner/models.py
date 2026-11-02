"""Validated canonical quotes. Ambiguous settlement contracts are never guessed."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    event_id: str = Field(min_length=1, max_length=200)
    sport: str = Field(min_length=1, max_length=100)
    league: str = Field(min_length=1, max_length=200)
    home: str = Field(min_length=1, max_length=200)
    away: str = Field(min_length=1, max_length=200)
    starts_at: datetime
    bookmaker: str = Field(min_length=1, max_length=100)
    market: Literal["h2h_2way", "h2h_3way", "totals", "spreads"]
    period: str = Field(default="full_time", min_length=1, max_length=100)
    rules: str = Field(default="regulation", min_length=1, max_length=100)
    line: Decimal | None = None
    outcome: Literal["home", "away", "draw", "over", "under"]
    odds: Decimal = Field(gt=1, le=10000, allow_inf_nan=False)
    observed_at: datetime
    source_updated_at: datetime | None = None
    source: str = Field(min_length=1, max_length=200)
    url: str | None = Field(default=None, max_length=2000)
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")

    @field_validator("starts_at", "observed_at", "source_updated_at")
    @classmethod
    def require_timezone(cls, value):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Timestamps must include a timezone, e.g. +00:00")
            return value.astimezone(timezone.utc)
        return value

    @field_validator("url")
    @classmethod
    def safe_link(cls, value):
        if value:
            parsed = urlsplit(value)
            if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Only HTTP(S) source links without credentials are supported")
        return value

    @model_validator(mode="after")
    def validate_contract(self):
        allowed = {
            "h2h_2way": {"home", "away"}, "h2h_3way": {"home", "draw", "away"},
            "totals": {"over", "under"}, "spreads": {"home", "away"},
        }
        if self.outcome not in allowed[self.market]:
            raise ValueError("Outcome does not belong to this market")
        if self.home.casefold() == self.away.casefold():
            raise ValueError("Event participants must differ")
        if self.market in {"totals", "spreads"}:
            if self.line is None or not self.line.is_finite() or abs(self.line) > 10000:
                raise ValueError("A finite canonical line is required")
            # Only half lines have simple mutually exclusive win/lose payouts.
            if abs(self.line % 1) != Decimal("0.5"):
                raise ValueError("Only half lines are supported; pushes and Asian quarter lines need settlement modelling")
            if self.market == "totals" and self.line < 0:
                raise ValueError("Totals lines cannot be negative")
        elif self.line is not None:
            raise ValueError("Moneyline markets cannot contain a line")
        if self.source_updated_at and self.source_updated_at > self.observed_at:
            raise ValueError("Source timestamp cannot be later than observation timestamp")
        return self


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minimum_profit: float = Field(default=0.5, ge=0, le=100, allow_inf_nan=False)
    bankroll: Decimal = Field(default=Decimal("100"), ge=1, le=1000000, allow_inf_nan=False)
    max_age_seconds: int = Field(default=120, ge=5, le=86400)
    source_skew_seconds: int = Field(default=60, ge=1, le=3600)
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    mode: Literal["live", "demo"] = "live"
    sports_filter: str = Field(default="", max_length=100)
    leagues_filter: str = Field(default="", max_length=200)
    require_source_timestamps: bool = True

    @field_validator("bankroll")
    @classmethod
    def cents(cls, value):
        if value != value.quantize(Decimal("0.01")):
            raise ValueError("Use at most two decimal places for the stake budget")
        return value
