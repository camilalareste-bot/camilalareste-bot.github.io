from __future__ import annotations

from datetime import datetime, time, timezone
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from models import CanonicalForexRecord, ProviderCapabilities, SourceKind


class ProviderError(RuntimeError):
    pass


class JsonHttpClient:
    def __init__(self, timeout_seconds: float = 15.0):
        self.timeout_seconds = timeout_seconds

    def get_json(self, url: str, params: dict[str, str] | None = None):
        if params:
            url = f"{url}?{urlencode(params)}"
        request = Request(url, headers={"User-Agent": "forex-reliability-lab/1.0"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise ProviderError(str(exc)) from exc


class AlphaVantageProvider:
    name = "alpha_vantage"
    capabilities = ProviderCapabilities(
        supports_ohlc=True,
        supports_volume=False,
        supports_historical=True,
        frequency="daily",
        requires_api_key=True,
    )

    def __init__(self, api_key: str, client: JsonHttpClient | None = None):
        if not api_key:
            raise ValueError("Alpha Vantage API key is required")
        self.api_key = api_key
        self.client = client or JsonHttpClient()

    def fetch(self, base: str, quote: str, since: datetime | None = None):
        payload = self.client.get_json(
            "https://www.alphavantage.co/query",
            params={
                "function": "FX_DAILY",
                "from_symbol": base.upper(),
                "to_symbol": quote.upper(),
                "outputsize": "full",
                "apikey": self.api_key,
            },
        )
        series = payload.get("Time Series FX (Daily)") if isinstance(payload, dict) else None
        if not series:
            raise ProviderError(f"Alpha Vantage returned no FX series: {payload}")

        rows = []
        for date_str, metrics in series.items():
            ts = datetime.combine(datetime.fromisoformat(date_str).date(), time.min, tzinfo=timezone.utc)
            if since is not None and ts < since:
                continue
            rows.append(CanonicalForexRecord(
                currency_pair=f"{base.upper()}/{quote.upper()}",
                timestamp=ts,
                data_source=self.name,
                source_kind=SourceKind.OHLC,
                open=float(metrics["1. open"]),
                high=float(metrics["2. high"]),
                low=float(metrics["3. low"]),
                close=float(metrics["4. close"]),
                volume=None,
            ))
        return rows


class TwelveDataProvider:
    name = "twelve_data"
    capabilities = ProviderCapabilities(
        supports_ohlc=True,
        supports_volume=True,
        supports_historical=True,
        frequency="configurable",
        requires_api_key=True,
    )

    def __init__(self, api_key: str, client: JsonHttpClient | None = None):
        if not api_key:
            raise ValueError("Twelve Data API key is required")
        self.api_key = api_key
        self.client = client or JsonHttpClient()

    def fetch(self, base: str, quote: str, since: datetime | None = None):
        params = {
            "symbol": f"{base.upper()}/{quote.upper()}",
            "interval": "1day",
            "outputsize": "5000",
            "apikey": self.api_key,
        }
        if since is not None:
            params["start_date"] = since.date().isoformat()

        payload = self.client.get_json("https://api.twelvedata.com/time_series", params=params)
        values = payload.get("values") if isinstance(payload, dict) else None
        if not values:
            raise ProviderError(f"Twelve Data returned no values: {payload}")

        rows = []
        for item in values:
            ts = datetime.fromisoformat(item["datetime"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            volume = item.get("volume")
            rows.append(CanonicalForexRecord(
                currency_pair=f"{base.upper()}/{quote.upper()}",
                timestamp=ts,
                data_source=self.name,
                source_kind=SourceKind.OHLC,
                open=float(item["open"]),
                high=float(item["high"]),
                low=float(item["low"]),
                close=float(item["close"]),
                volume=float(volume) if volume not in (None, "") else None,
            ))
        return rows


class ExchangeRateAPIProvider:
    """Latest reference-rate adapter. Historical capability is not overclaimed here."""

    name = "exchange_rate_api"
    capabilities = ProviderCapabilities(
        supports_ohlc=False,
        supports_volume=False,
        supports_historical=False,
        frequency="latest_reference_rate",
        requires_api_key=True,
    )

    def __init__(self, api_key: str, client: JsonHttpClient | None = None):
        if not api_key:
            raise ValueError("ExchangeRate API key is required")
        self.api_key = api_key
        self.client = client or JsonHttpClient()

    def fetch(self, base: str, quote: str, since: datetime | None = None):
        payload = self.client.get_json(
            f"https://v6.exchangerate-api.com/v6/{self.api_key}/latest/{base.upper()}"
        )
        rates = payload.get("conversion_rates") if isinstance(payload, dict) else None
        if not rates or quote.upper() not in rates:
            raise ProviderError(f"ExchangeRate API returned no quote for {quote}")

        epoch = payload.get("time_last_update_unix")
        ts = datetime.fromtimestamp(int(epoch), tz=timezone.utc) if epoch else datetime.now(timezone.utc)
        return [CanonicalForexRecord(
            currency_pair=f"{base.upper()}/{quote.upper()}",
            timestamp=ts,
            data_source=self.name,
            source_kind=SourceKind.REFERENCE_RATE,
            close=float(rates[quote.upper()]),
        )]


class ECBViaFrankfurterProvider:
    """
    Public no-key demo adapter.
    Frankfurter is the delivery API; providers=ECB pins ECB reference rates.
    These are reference rates, not OHLC market bars.
    """

    name = "ecb_via_frankfurter"
    capabilities = ProviderCapabilities(
        supports_ohlc=False,
        supports_volume=False,
        supports_historical=True,
        frequency="daily_reference_rate",
        requires_api_key=False,
    )

    def __init__(self, client: JsonHttpClient | None = None):
        self.client = client or JsonHttpClient()

    def fetch(self, base: str, quote: str, since: datetime | None = None):
        params = {"base": base.upper(), "quotes": quote.upper(), "providers": "ECB"}
        if since is not None:
            params["from"] = since.date().isoformat()

        payload = self.client.get_json("https://api.frankfurter.dev/v2/rates", params=params)
        if not isinstance(payload, list):
            raise ProviderError("Unexpected Frankfurter response shape")

        rows = []
        for item in payload:
            if item.get("quote") != quote.upper():
                continue
            ts = datetime.combine(datetime.fromisoformat(item["date"]).date(), time.min, tzinfo=timezone.utc)
            rows.append(CanonicalForexRecord(
                currency_pair=f"{base.upper()}/{quote.upper()}",
                timestamp=ts,
                data_source=self.name,
                source_kind=SourceKind.REFERENCE_RATE,
                close=float(item["rate"]),
                open=None,
                high=None,
                low=None,
                volume=None,
            ))
        if not rows:
            raise ProviderError("ECB adapter returned no rows for requested pair")
        return rows
