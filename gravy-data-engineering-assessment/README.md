# Forex Reliability Lab — Gravy Data Engineering Assessment

Supplemental reviewer-facing implementation for a Senior Data Engineer technical assessment.

## Production design

Provider Adapters → Capability Filter → Canonical Contract → Validation / Quarantine → Raw / Bronze → Lookback Watermark → Idempotent PostgreSQL Upsert → dbt Staging / Marts → Observability.

## Key engineering decisions

- Provider capabilities are explicit; rate-only feeds are not coerced into OHLCV.
- ECB data in the live demo is identified as reference-rate data, delivered through Frankfurter with `providers=ECB`.
- Late-arriving data is handled with a persisted watermark plus configurable lookback window.
- Idempotency key: `(data_source, currency_pair, timestamp)`.
- Failover is capability-aware: an OHLC workload only fails over to another OHLC-capable provider.
- Data quality is enforced at ingestion and in dbt; invalid records should be quarantined with a reason.
- No credentials are embedded in the demo.

## Interactive demo

GitHub Pages: `https://camilalareste-bot.github.io/gravy-data-engineering-assessment/`

## Source layout in this folder

- `SUBMISSION.md` — architecture review and assessment reasoning
- `source/models.py` — canonical contract and provider capabilities
- `source/pipeline.py` — bounded retries and capability-aware failover
- `source/frankfurter_ecb.py` — public no-key ECB reference-rate demo adapter
- `source/schema.sql` — PostgreSQL raw, watermark, and quarantine tables
- `source/dbt_models.sql` — representative dbt analytical models
- `source/tests.py` — core behavioral tests

## Scope note

The employer assessment describes destructive Git-history challenges in the provided repository. Those operations should be executed against that original assessment repository so the expected history is preserved rather than simulated in this companion demo.