# Financial-market validation campaign

This campaign validates the stylized financial-market engine separately from
the global policy LHS campaign. It uses fixed parameters, the baseline
`current_eu_supervision` regime, and independent market/supervision seeds.
Its outputs are simulation diagnostics, not empirical calibration, causal
estimates, or forecasts.

## Completed campaign state (16 July 2026)

The 30-seed campaign is complete in
`results/financial_validation/pilot_30seeds/`: 30 valid seeds at horizon
10,000 days with 2,000-day burn-in, order-book events enabled, no pending,
missing, rejected, or quarantined seeds, 1.09 GB total output. One transient
Windows file-lock failure (seed_017) was recorded in `failures.json` and
resolved by an atomic re-run; the final aggregate manifest lists all 30 seeds
valid. Multi-seed diagnostics are in `diagnostics/`.

Aggregate classifications with the independent seed as the unit of inference:

| Fact | Status | Seed counts (R/P/N) |
|---|---|---|
| Volatility clustering | reproduced | 30/0/0 |
| Positive spread and depth | reproduced | 30/0/0 |
| Trade-sign persistence | reproduced | 30/0/0 |
| Cancellation activity | reproduced | 30/0/0 |
| Volume-volatility relation | partially reproduced | 17/13/0 |
| Fat-tailed returns | partially reproduced | 3/27/0 |
| Weak linear return autocorrelation | partially reproduced | 0/29/1 |
| Positive price impact | **not reproduced** | 0/4/26 |

The non-reproduced positive-price-impact result and the partial results are
reported verbatim in manuscript Section 5.7 and in the eleventh limitation.
The market layer is described in the paper as endogenous market response and
financing context, not as a price-discipline mechanism; the static audits in
`results/audits/` document that firm environmental decisions contain no
own-share-price feedback. A signed event-level impact diagnostic (trade sign
x future mid-price change at multiple event horizons, seed-level inference)
is identified as future work and would require new code, not new simulation
of the stored seeds.

The runner is read-only by default. Importing the module or running the
commands below without `--execute-missing` never starts a simulation and does
not create the output directory.

## Five-seed pilot

Inspect the exact seed schedule, configuration, paths, and missing/invalid
outputs:

```powershell
python run_financial_validation_campaign.py `
  --output-root results/financial_validation/pilot_5seeds `
  --seeds 5 `
  --horizon 10000 `
  --burn-in 2000 `
  --regime current_eu_supervision `
  --write-order-book-events
```

Only after explicit approval and review of that preflight, add
`--execute-missing`. Valid seed directories are reused unchanged. Invalid
directories are moved to `rejected/` during an explicitly authorized execution
and replaced atomically. An interrupted campaign can be resumed with the
identical command.

## Outputs and provenance

Each `seed_NNN/` directory contains `manifest.json`, `daily_market.csv`, and,
when enabled, `order_book_events.csv`. The manifest stores the complete
constructor configuration (including defaults and effective asset profiles),
independent seeds, burn-in rule, code/dirty-tree fingerprints, timestamps,
runtime, schemas, record counts, byte sizes, and SHA-256 hashes.

`daily_market.csv` contains only days strictly after the burn-in. Its volume is
the primary listing's executed quantity and realized volatility is the rolling
sample standard deviation of the latest 20 calendar log returns.

The optional event stream is passive and covers the primary listing. Its
`timestamp` is a deterministic model-event sequence, not a wall-clock time.
Depth is total active resting quantity at emission; submission snapshots are
pre-matching and trade/execution/cancellation snapshots follow their state
update. Empty fields mean “not applicable.” The model has no amendment
operation; the exporter records that limitation rather than fabricating
amendment observations.

`aggregate_manifest.json` records reused, rejected, quarantined, missing,
pending, newly run, and failed seeds; per-seed runtime and storage; anomalies;
and a conservative 30-seed planning projection once exactly five valid pilot
seeds exist. Derived multi-seed diagnostics are written under `diagnostics/`.

## Inspect runtime and storage

The manifest is authoritative for runtime and byte counts. A PowerShell disk
cross-check is:

```powershell
$bytes = (Get-ChildItem results\financial_validation\pilot_5seeds -Recurse -File |
  Measure-Object -Property Length -Sum).Sum
[math]::Round($bytes / 1GB, 2)
```

The planning projection uses:

```text
projected_time_30 = pilot_time_5 × 6 × safety_factor
projected_storage_30 = pilot_storage_5 × 6 × safety_factor
```

with a configurable safety factor between 1.25 and 1.30. It is a capacity
planning estimate, not a scientific result.

## Thirty-seed campaign

First perform a read-only preflight:

```powershell
python run_financial_validation_campaign.py `
  --output-root results/financial_validation/full_30seeds `
  --seeds 30 `
  --horizon 10000 `
  --burn-in 2000 `
  --regime current_eu_supervision `
  --write-order-book-events
```

After confirming available time and storage, repeat with
`--execute-missing`. A preregistered market seed list can replace the generated
schedule using `--seed-list 11,29,...`; supervision seeds retain their separate
documented schedule.

## Diagnostics and limitations

The runner generates seed-level and aggregate fat-tail, linear-return ACF,
volatility-clustering, spread/depth, cancellation, trade-sign, immediate price-
impact, and volume-volatility diagnostics. Cross-seed statements use the seed
as the unit; raw returns are never pooled across paths.

The classifications are transparent diagnostic rules. Reproducing selected
stylized facts is weaker than calibration or out-of-sample empirical
validation. Immediate mid-price movement is not a causal long-horizon price-
impact estimate, event data cover the primary listing only, and the current
model has no order-amendment event.
