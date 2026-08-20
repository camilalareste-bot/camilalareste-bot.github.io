# Data Engineer Technical Assessment — Submission Notes

**Candidate:** Camila Lareste

## Executive Summary

I approached the assessment as a production data-platform problem rather than a collection of isolated scripts.

The proposed design separates provider-specific extraction from business rules, normalizes data into an explicit canonical contract, applies data quality checks before persistence, performs idempotent incremental upserts with late-arrival support, and uses dbt for analytical modeling and post-load validation.

A key design choice is to model provider **capabilities** explicitly. The assessment lists both OHLC-style providers and reference-rate providers. These datasets are not semantically interchangeable, so the implementation never fabricates OHLC or volume values just to satisfy a schema.

---

# Task 1 — Architecture Review

## 1. Incremental loading, idempotency, and late-arriving records

**Current limitation / production gap**  
A production pipeline needs an explicit persisted ingestion state. Filtering only on `timestamp > max(timestamp)` prevents some duplicates but misses delayed or corrected records.

**Business impact**  
Late financial records can be silently excluded, corrected source data may never be reprocessed, and full reloads unnecessarily increase API usage and compute cost.

**Proposed solution**  
Persist a watermark by provider and currency pair. On each run, extract from `watermark - configurable_lookback_window`, then use PostgreSQL upserts with a unique key `(data_source, currency_pair, timestamp)`.

**Expected benefit**  
Idempotent reruns, controlled incremental processing, safe ingestion of late-arriving records, and lower API/database workload.

## 2. Provider abstraction and capability-aware failover

**Current limitation / production gap**  
The baseline depends on external providers that do not all expose equivalent market fields.

**Business impact**  
A provider outage can stop the pipeline. Blind failover can also corrupt semantics if a reference-rate feed is substituted for an OHLC feed.

**Proposed solution**  
Use a provider adapter interface plus capability metadata: `supports_ohlc`, `supports_volume`, `supports_historical`, `frequency`, and `requires_api_key`. Failover selects only providers capable of satisfying the requested workload.

**Expected benefit**  
Lower coupling, safer failover, minimal code changes when adding providers, and explicit data semantics.

## 3. Retry, exponential backoff, jitter, and circuit breaking

**Current limitation / production gap**  
Third-party APIs can fail transiently due to timeouts, HTTP 429 responses, and 5xx errors.

**Business impact**  
Without controlled retry behavior, transient failures become failed pipeline runs. Aggressive retries can amplify rate-limit incidents.

**Proposed solution**  
Implement bounded retries with exponential backoff and jitter. Track repeated failures by provider and temporarily remove unhealthy providers from the eligible pool.

**Expected benefit**  
Higher resilience without retry storms and faster recovery through alternative providers.

## 4. Data quality gates and quarantine

**Current limitation / production gap**  
External financial payloads should not be assumed valid simply because an HTTP request succeeded.

**Business impact**  
Null, negative, malformed, duplicated, or temporally inconsistent records can contaminate analytical models and downstream AI features.

**Proposed solution**  
Use two validation layers: ingestion-time Python validation and warehouse/dbt tests. Invalid rows should be recorded in a quarantine/dead-letter structure with the failure reason and source metadata.

**Expected benefit**  
Traceable failures, safer downstream models, and measurable data-quality SLAs.

## 5. Schema contracts and schema evolution

**Current limitation / production gap**  
Provider payloads evolve independently. Directly coupling source JSON fields to warehouse columns makes schema changes risky.

**Business impact**  
A source-field rename or format change can propagate failures across transformation and analytics layers.

**Proposed solution**  
Normalize each provider behind an adapter into a versioned canonical record. Track provider response metadata and add compatibility tests for adapters.

**Expected benefit**  
Localized provider changes and stable downstream contracts.

## 6. Observability and operational metadata

**Current limitation / production gap**  
A production pipeline must expose more than application logs.

**Business impact**  
Without freshness, latency, throughput, retry, validation, and provider-health metrics, incidents are discovered late and root-cause analysis becomes slower.

**Proposed solution**  
Emit structured logs and metrics for run id, provider, pair, extracted records, inserted/updated records, rejected records, latency, retries, freshness lag, and error category. Add alerts for failed runs and freshness SLA violations.

**Expected benefit**  
Faster detection, clearer incident ownership, and auditable pipeline behavior.

## 7. Security and secrets management

**Current limitation / production gap**  
API and database credentials must never be embedded in source code or committed to Git.

**Business impact**  
Credential leakage can create financial, security, and compliance exposure.

**Proposed solution**  
Use environment-injected secrets from a managed secret store, least-privilege database roles, TLS, network controls, and credential rotation. CI uses separate non-production credentials.

**Expected benefit**  
Reduced credential risk and cleaner environment separation.

## 8. CI/CD and data-contract testing

**Current limitation / production gap**  
Changes to adapters, SQL, and dbt models can introduce regressions even when basic unit tests pass.

**Business impact**  
Broken transformations or source mappings can reach production and invalidate dashboards or model features.

**Proposed solution**  
CI should run Python unit tests, formatting/linting, adapter contract tests using fixtures, SQL/dbt compilation, dbt tests, migration checks, and secret scanning.

**Expected benefit**  
Safer releases, reproducible environments, and lower regression risk.

---

# Task 2 — Hands-on Engineering

## Canonical contract

The canonical record intentionally allows nullable OHLCV fields for reference-rate sources. A reference-rate provider is represented with `source_kind='reference_rate'`, a positive `close`/reference rate, and `open/high/low/volume = null` rather than fabricated values.

For an OHLC-capable provider, `open/high/low/close` are required and checked for internal consistency.

## Provider adapters

| Provider | Source kind | OHLC | Volume | Historical | Key |
|---|---|---:|---:|---:|---:|
| Alpha Vantage | OHLC | Yes | No for FX_DAILY | Yes | Yes |
| Twelve Data | OHLC | Yes | Instrument-dependent | Yes | Yes |
| ExchangeRate API | Reference rate | No | No | Provider/plan dependent | Yes |
| ECB via Frankfurter demo adapter | Reference rate | No | No | Yes | No |

## Automatic failover

The orchestration layer filters providers by required capability, attempts the primary provider, applies bounded retry behavior, records failures, moves to the next eligible provider, and fails explicitly if no compatible provider remains.

An ECB reference-rate source is **not** used as a silent fallback for an OHLC workload.

## Incremental processing

For each provider/pair:

```text
watermark = last_successful_timestamp
start = watermark - lookback_window
extract(start..now)
validate
upsert on (provider, pair, timestamp)
advance watermark after successful persistence
```

The lookback absorbs delayed/corrected records and the unique constraint preserves idempotency.

## Data quality rules

- unique `(provider, currency_pair, timestamp)`
- non-null positive `close` / reference rate
- valid ISO-style currency pair shape
- timezone-aware timestamp
- OHLC consistency only when `source_kind = 'ohlc'`
- no fabricated `volume`
- freshness metrics
- quarantine reason capture

---

# Task 3 — Data Modeling

## Model layers

```text
raw_forex_rates
      ↓
stg_forex_rates
      ↓
int_forex_daily
      ↓
├── fct_currency_performance
├── fct_volatility_trends
└── fct_data_quality_metrics
```

Daily return is calculated as `(close_t / close_t-1) - 1`.

Weekly and monthly returns are derived using calendar period boundaries rather than assuming that seven rows always equal one week or thirty rows always equal one month.

Rolling volatility uses the standard deviation of daily returns. Intraday high/low spread is calculated only for OHLC sources. Reference-rate records remain valid for rate-return analysis without pretending to contain intraday price ranges.

Moving averages are produced for 7, 30, and 90 observations, and the model exposes sample counts so consumers can distinguish complete windows from early partial windows.

Data-quality metrics include total records, duplicate count, invalid close/reference rates, invalid currency pairs, OHLC consistency failures, latest timestamp, freshness lag, and records by provider/source kind.

---

# Task 4 — Git Challenges

These commands are intentionally destructive and should be executed in the employer-provided assessment repository.

## Challenge 1 — Recover the lost commit

```bash
git switch git-assessment
git reflog
git show <lost_commit_sha>
git reset --hard <lost_commit_sha>
```

Alternative, when the branch should remain at its current tip and only the lost change must be reapplied:

```bash
git cherry-pick <lost_commit_sha>
```

## Challenge 2 — Clean messy history

```bash
git switch git-assessment
git rebase -i HEAD~5
```

Keep the first meaningful commit as `pick`, mark noisy follow-up commits as `fixup`/`squash`, then rewrite the final commit message to describe the resulting change.

## Challenge 3 — Move the payment commit

Starting with the accidental payment commit at `HEAD` on `git-assessment`:

```bash
git switch git-assessment
git branch feature/payment HEAD
git reset --hard HEAD~1
git switch feature/payment
```

Validation:

```bash
git log --oneline --decorate --graph --all
```

The payment commit should exist on `feature/payment` and no longer be part of `git-assessment`.

---

# Final Production Architecture

```text
External Providers
  ├── Alpha Vantage
  ├── Twelve Data
  ├── ExchangeRate API
  └── ECB reference rates
          │
          ▼
Provider Adapters + Capability Registry
          │
          ▼
Canonical Forex Contract
          │
     Validation Gate
      ┌───┴─────────┐
      ▼             ▼
   Valid         Quarantine
      │
      ▼
Raw/Bronze + ingestion metadata
      │
      ▼
Lookback Incremental Upsert
      │
      ▼
PostgreSQL / RDS
      │
      ▼
dbt staging → intermediate → marts
      │
      ├── Currency Performance
      ├── Volatility
      ├── Trends
      └── Data Quality
      │
      ▼
Observability / Alerts / AI & Analytics Consumers
```

# Reviewer Demo

The companion web MVP is intentionally small. It demonstrates live public reference-rate ingestion, provider capability modeling, simulated capability-aware failover, data-quality checks, freshness, trend analytics, and architecture decisions.

It is explicitly labeled as a **supplemental visual demo**. The production implementation remains the Python/PostgreSQL/dbt design.