import unittest
from datetime import datetime, timedelta, timezone

from models import CanonicalForexRecord, ProviderCapabilities, SourceKind
from pipeline import ProviderError, ResilientForexPipeline, RetryPolicy

TS = datetime(2026, 8, 18, tzinfo=timezone.utc)


class FailingProvider:
    name = "failing"
    capabilities = ProviderCapabilities(True, False, True, "daily", False)

    def fetch(self, base, quote, since=None):
        raise ProviderError("simulated outage")


class GoodProvider:
    name = "good"
    capabilities = ProviderCapabilities(True, False, True, "daily", False)

    def fetch(self, base, quote, since=None):
        return [
            CanonicalForexRecord(
                currency_pair=f"{base}/{quote}",
                timestamp=TS,
                data_source=self.name,
                source_kind=SourceKind.OHLC,
                open=1.1,
                high=1.2,
                low=1.0,
                close=1.15,
            )
        ]


class RateOnlyProvider:
    name = "rate_only"
    capabilities = ProviderCapabilities(False, False, True, "daily", False)

    def fetch(self, base, quote, since=None):
        return [
            CanonicalForexRecord(
                currency_pair=f"{base}/{quote}",
                timestamp=TS,
                data_source=self.name,
                source_kind=SourceKind.REFERENCE_RATE,
                close=1.15,
            )
        ]


class PipelineTests(unittest.TestCase):
    def test_reference_rate_does_not_fabricate_ohlc(self):
        row = RateOnlyProvider().fetch("EUR", "USD")[0]
        self.assertIsNone(row.open)
        self.assertIsNone(row.high)
        self.assertIsNone(row.low)
        self.assertIsNone(row.volume)

    def test_failover_selects_next_eligible_provider(self):
        pipeline = ResilientForexPipeline(
            [FailingProvider(), GoodProvider()],
            retry=RetryPolicy(attempts=1),
            sleep_fn=lambda _: None,
        )
        result = pipeline.extract_with_failover("EUR", "USD", require_ohlc=True)
        self.assertEqual(result.provider, "good")
        self.assertEqual(len(result.failures), 1)

    def test_rate_only_provider_is_not_used_for_ohlc_failover(self):
        pipeline = ResilientForexPipeline(
            [RateOnlyProvider()],
            retry=RetryPolicy(attempts=1),
            sleep_fn=lambda _: None,
        )
        with self.assertRaises(ProviderError):
            pipeline.extract_with_failover("EUR", "USD", require_ohlc=True)


if __name__ == "__main__":
    unittest.main()
