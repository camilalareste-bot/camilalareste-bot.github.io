from __future__ import annotations

from datetime import datetime, time, timezone
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from models import CanonicalForexRecord, ProviderCapabilities, SourceKind


class ProviderError(RuntimeError):
    pass


class ECBViaFrankfurterProvider:
    """
    Public no-key demo adapter.

    Frankfurter is the delivery API; providers=ECB pins the underlying
    reference-rate source. These are reference rates, not OHLC market bars.
    """

    name = "ecb_via_frankfurter"
    capabilities = ProviderCapabilities(
        supports_ohlc=False,
        supports_volume=False,
        supports_historical=True,
        frequency="daily_reference_rate",
        requires_api_key=False,
    )

    def fetch(self, base: str, quote: str, since: datetime | None = None):
        params = {
            "base": base.upper(),
            "quotes": quote.upper(),
            "providers": "ECB",
        }
        if since is not None:
            params["from"] = since.date().isoformat()

        url = "https://api.frankfurter.dev/v2/rates?" + urlencode(params)
        request = Request(url, headers={"User-Agent": "forex-reliability-lab/1.0"})
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise ProviderError(str(exc)) from exc

        if not isinstance(payload, list):
            raise ProviderError("Unexpected Frankfurter response shape")

        rows: list[CanonicalForexRecord] = []
        for item in payload:
            if item.get("quote") != quote.upper():
                continue
            ts = datetime.combine(
                datetime.fromisoformat(item["date"]).date(),
                time.min,
                tzinfo=timezone.utc,
            )
            rows.append(
                CanonicalForexRecord(
                    currency_pair=f"{base.upper()}/{quote.upper()}",
                    timestamp=ts,
                    data_source=self.name,
                    source_kind=SourceKind.REFERENCE_RATE,
                    close=float(item["rate"]),
                    open=None,
                    high=None,
                    low=None,
                    volume=None,
                )
            )

        if not rows:
            raise ProviderError("ECB adapter returned no rows for requested pair")
        return rows
