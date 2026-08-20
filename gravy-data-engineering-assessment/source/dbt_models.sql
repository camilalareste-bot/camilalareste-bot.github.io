-- dbt model: int_forex_daily.sql
WITH base AS (
    SELECT
        *,
        close / NULLIF(
            LAG(close) OVER (
                PARTITION BY data_source, currency_pair
                ORDER BY timestamp
            ),
            0
        ) - 1 AS daily_return
    FROM {{ ref('stg_forex_rates') }}
)
SELECT * FROM base;

-- dbt model: fct_currency_performance.sql
WITH daily AS (
    SELECT * FROM {{ ref('int_forex_daily') }}
),
period_values AS (
    SELECT
        data_source,
        currency_pair,
        timestamp,
        close,
        daily_return,
        FIRST_VALUE(close) OVER (
            PARTITION BY data_source, currency_pair, DATE_TRUNC('week', timestamp)
            ORDER BY timestamp
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS week_open,
        FIRST_VALUE(close) OVER (
            PARTITION BY data_source, currency_pair, DATE_TRUNC('month', timestamp)
            ORDER BY timestamp
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS month_open
    FROM daily
)
SELECT
    data_source,
    currency_pair,
    timestamp,
    close,
    daily_return,
    close / NULLIF(week_open, 0) - 1 AS weekly_return,
    close / NULLIF(month_open, 0) - 1 AS monthly_return
FROM period_values;

-- dbt model: fct_volatility_trends.sql
SELECT
    data_source,
    currency_pair,
    timestamp,
    source_kind,
    close,
    CASE
        WHEN source_kind = 'ohlc'
        THEN (high - low) / NULLIF(low, 0)
    END AS intraday_spread_pct,
    STDDEV_SAMP(daily_return) OVER (
        PARTITION BY data_source, currency_pair
        ORDER BY timestamp
        ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS rolling_30_observation_volatility,
    AVG(close) OVER (
        PARTITION BY data_source, currency_pair
        ORDER BY timestamp
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS ma_7,
    AVG(close) OVER (
        PARTITION BY data_source, currency_pair
        ORDER BY timestamp
        ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS ma_30,
    AVG(close) OVER (
        PARTITION BY data_source, currency_pair
        ORDER BY timestamp
        ROWS BETWEEN 89 PRECEDING AND CURRENT ROW
    ) AS ma_90,
    COUNT(*) OVER (
        PARTITION BY data_source, currency_pair
        ORDER BY timestamp
        ROWS BETWEEN 89 PRECEDING AND CURRENT ROW
    ) AS rolling_sample_count
FROM {{ ref('int_forex_daily') }};

-- dbt model: fct_data_quality_metrics.sql
SELECT
    data_source,
    source_kind,
    COUNT(*) AS total_records,
    COUNT(*) - COUNT(DISTINCT (currency_pair, timestamp)) AS duplicate_records,
    COUNT(*) FILTER (WHERE close IS NULL OR close <= 0) AS invalid_close_records,
    COUNT(*) FILTER (
        WHERE currency_pair IS NULL
           OR currency_pair !~ '^[A-Z]{3}/[A-Z]{3}$'
    ) AS invalid_currency_pair_records,
    COUNT(*) FILTER (
        WHERE source_kind = 'ohlc'
          AND (
              open IS NULL OR high IS NULL OR low IS NULL
              OR low > LEAST(open, close)
              OR high < GREATEST(open, close)
          )
    ) AS invalid_ohlc_records,
    MAX(timestamp) AS latest_record_timestamp,
    NOW() - MAX(timestamp) AS freshness_lag
FROM {{ ref('stg_forex_rates') }}
GROUP BY data_source, source_kind;
