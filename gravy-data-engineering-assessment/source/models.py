from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import re
from typing import Optional

PAIR_RE = re.compile(r"^[A-Z]{3}/[A-Z]{3}$")


class SourceKind(str, Enum):
    OHLC = "ohlc"
    REFERENCE_RATE = "reference_rate"


@dataclass(frozen=True)
class ProviderCapabilities:
    supports_ohlc: bool
    supports_volume: bool
    supports_historical: bool
    frequency: str
    requires_api_key: bool


@dataclass(frozen=True)
class CanonicalForexRecord:
    currency_pair: str
    timestamp: datetime
    data_source: str
    source_kind: SourceKind
    close: float
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[float] = None

    def __post_init__(self) -> None:
        pair = self.currency_pair.upper().replace("-", "/").replace("_", "/")
        if "/" not in pair and len(pair) == 6:
            pair = f"{pair[:3]}/{pair[3:]}"
        object.__setattr__(self, "currency_pair", pair)

        if not PAIR_RE.match(pair):
            raise ValueError(f"Invalid currency pair: {pair}")
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        if self.close <= 0:
            raise ValueError("close/reference rate must be positive")

        if self.source_kind is SourceKind.OHLC:
            if None in (self.open, self.high, self.low):
                raise ValueError("OHLC source requires open/high/low")
            assert self.open is not None and self.high is not None and self.low is not None
            if min(self.open, self.high, self.low) <= 0:
                raise ValueError("OHLC values must be positive")
            if self.high < max(self.open, self.close, self.low):
                raise ValueError("high is inconsistent with OHLC values")
            if self.low > min(self.open, self.close, self.high):
                raise ValueError("low is inconsistent with OHLC values")

        if self.volume is not None and self.volume < 0:
            raise ValueError("volume cannot be negative")

    @property
    def idempotency_key(self) -> tuple[str, str, datetime]:
        return (self.data_source, self.currency_pair, self.timestamp)
