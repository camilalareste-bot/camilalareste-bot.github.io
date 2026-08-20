CREATE TABLE IF NOT EXISTS raw_forex_rates (
    data_source TEXT NOT NULL,
    currency_pair TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('ohlc', 'reference_rate')),
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC NOT NULL CHECK (close > 0),
    volume NUMERIC,
    provider_payload_hash TEXT,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT raw_forex_rates_pk
        PRIMARY KEY (data_source, currency_pair, timestamp),
    CONSTRAINT raw_forex_rates_ohlc_contract CHECK (
        source_kind <> 'ohlc'
        OR (open IS NOT NULL AND high IS NOT NULL AND low IS NOT NULL)
    ),
    CONSTRAINT raw_forex_rates_volume_nonnegative CHECK (
        volume IS NULL OR volume >= 0
    )
);

CREATE TABLE IF NOT EXISTS ingestion_watermarks (
    data_source TEXT NOT NULL,
    currency_pair TEXT NOT NULL,
    watermark TIMESTAMPTZ NOT NULL,
    last_successful_run_id UUID,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (data_source, currency_pair)
);

CREATE TABLE IF NOT EXISTS forex_quarantine (
    quarantine_id BIGSERIAL PRIMARY KEY,
    data_source TEXT NOT NULL,
    currency_pair TEXT,
    source_timestamp TIMESTAMPTZ,
    failure_reason TEXT NOT NULL,
    payload JSONB,
    quarantined_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Idempotent upsert pattern used after extracting from watermark - lookback_window.
INSERT INTO raw_forex_rates (
    data_source, currency_pair, timestamp, source_kind,
    open, high, low, close, volume, provider_payload_hash
)
VALUES (
    %(data_source)s, %(currency_pair)s, %(timestamp)s, %(source_kind)s,
    %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(provider_payload_hash)s
)
ON CONFLICT (data_source, currency_pair, timestamp)
DO UPDATE SET
    source_kind = EXCLUDED.source_kind,
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    provider_payload_hash = EXCLUDED.provider_payload_hash,
    updated_at = NOW()
WHERE raw_forex_rates.provider_payload_hash IS DISTINCT FROM EXCLUDED.provider_payload_hash;
