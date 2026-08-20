from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import random
import time
from typing import Iterable

from models import CanonicalForexRecord


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_delay_seconds: float = 0.25
    max_delay_seconds: float = 2.0


@dataclass(frozen=True)
class PipelineResult:
    provider: str
    records: list[CanonicalForexRecord]
    failures: tuple[str, ...]


class ResilientForexPipeline:
    def __init__(self, providers: Iterable, retry: RetryPolicy | None = None, sleep_fn=time.sleep):
        self.providers = list(providers)
        self.retry = retry or RetryPolicy()
        self.sleep_fn = sleep_fn

    def extract_with_failover(
        self,
        base: str,
        quote: str,
        *,
        since: datetime | None = None,
        require_ohlc: bool = False,
    ) -> PipelineResult:
        eligible = [
            provider
            for provider in self.providers
            if not require_ohlc or provider.capabilities.supports_ohlc
        ]
        if not eligible:
            raise ProviderError("No provider satisfies the requested capabilities")

        failures: list[str] = []
        for provider in eligible:
            for attempt in range(1, self.retry.attempts + 1):
                try:
                    rows = list(provider.fetch(base, quote, since=since))
                    if not rows:
                        raise ProviderError("empty response")
                    return PipelineResult(provider=provider.name, records=rows, failures=tuple(failures))
                except Exception as exc:
                    failures.append(f"{provider.name}: attempt {attempt}: {exc}")
                    if attempt < self.retry.attempts:
                        delay = min(
                            self.retry.max_delay_seconds,
                            self.retry.base_delay_seconds * (2 ** (attempt - 1)),
                        )
                        delay += random.uniform(0, delay * 0.15)
                        self.sleep_fn(delay)

        raise ProviderError("All eligible providers failed: " + " | ".join(failures))
