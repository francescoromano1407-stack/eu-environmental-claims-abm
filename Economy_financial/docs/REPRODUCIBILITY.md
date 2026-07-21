# Reproducibility guide

All commands run from the repository root. Simulation outputs are results of a
stylized computational policy experiment, not empirical forecasts or causal
estimates.

The authoritative publication snapshot is the machine-readable campaign at
`results/`: `configuration.json`, `manifest.json`, the four `raw/` horizon
directories, and the corresponding `summaries/`. It contains 200 LHS draws,
three paired replications, and three regimes at each of 120, 365, 1,000, and
2,000 days (7,200 regime runs in total). Every horizon uses the same 28-
dimensional LHS design and seed schedule. Historical 60/6/3 subset workflows
are not the design reported in the current manuscript.

## 1. Tests

```bash
python -m pytest tests/ -q
```

The tests cover information boundaries, same-seed reproducibility, regime-
order invariance, corrections and sanctions, accounting identities, strict
campaign resume validation, dry-run execution barriers, and the replication-
robustness workflow. Tests do not launch the global LHS campaign.

## 2. Inspect before any campaign execution

The top-level runner is read-only by default and inspects all four publication
horizons:

```bash
python run_global_lhs_campaign.py --resume results
```

It prints, for every horizon:

- the count and identifiers of valid active draws;
- valid draws available for atomic import from compatible prior campaigns;
- the exact missing, incomplete, corrupt, or incompatible draw list;
- rejected files and candidate directories with reasons.

The validator checks the complete LHS point, horizon, master-seed-derived
market seed, supervision seed, regime order, replication count, run-row
completeness, discount rate, and finite metrics. A bare `"complete": true`
flag is not sufficient. The default command changes no file and executes no
simulation.

Only after reviewing the printed preflight list can execution be permitted:

```bash
python run_global_lhs_campaign.py --resume results --execute-missing
```

That command preserves valid files, atomically imports compatible files, and
runs only unresolved draws. It then regenerates horizon summaries, run-level
tables, parameter importance, rank and Pareto frequencies, cross-horizon
ranking stability, figures, and manifests. Each horizon receives a
`completion_ledger.json` recording reused, imported, rejected, newly run, and
still-pending draws.

To regenerate derived artifacts only, with a hard refusal if any simulation is
needed:

```bash
python run_global_lhs_campaign.py --resume results --rebuild-only
```

The publication defaults are 200 draws, three replications, and horizons
120/365/1,000/2,000. Smaller fixtures require `--development`. Use
`--base-horizon-only` only for an explicitly limited inspection.

## 3. Design and random streams

- LHS master seed: `20260716`.
- Market seed: `master_seed + 1000000*draw + 1000*replication`.
- Supervision seed: `104729 + 104729*draw + 7919*replication`.
- Both streams are reset for every regime within a replication, preserving
  common random numbers across regimes and independent environments across
  replications.
- The LHS samples only registry entries classified `EXPERIMENT` or
  `STYLIZATION`; `LEGAL` and `LEGAL-ANCHOR` values are not sampled.
- Raw per-draw results and JSON manifests use atomic replacement.

## 4. Configurable replication robustness (executed 16 July 2026)

The extension selects 12 representative configurations by deterministic
maximin coverage of standardized cross-horizon outcomes and targets 15 paired
replications by default. It never alters or reruns the authoritative first
three replications.

```bash
# Read-only preflight
python run_replication_robustness.py --results-root results

# Explicitly add only replications 4-15 for missing selected draws
python run_replication_robustness.py --results-root results --execute-missing
```

`--target-replications` accepts 10-20 and `--subset-size` is configurable.
Outputs are separate in `results/replication_robustness/` and are complete:
draws 41, 42, 69, 71, 75, 104, 109, 136, 144, 147, 180, and 187 at all four
horizons, all valid (`manifest.json`, `replication_robustness_summary.json`,
`ranking_stability.csv`). Headline comparison of 3 versus 15 replications:
paired 95% intervals narrow in 92.3% of the 1,743 finite draw-metric-policy
cells (median half-width ratio 0.26); the default-weight winner is confirmed
in 32/48 draw-horizon cells and the full ranking in 60.4%. Re-running the
preflight command above verifies the stored extension without simulating.

## 5. Financial stylized-facts diagnostics (single path — superseded)

This command reads an existing price path and never runs the model:

```bash
# Print only
python -m market_sim.financial_validation --input simulation_results.csv

# Write provenance-hashed JSON/CSV diagnostics and SVG figures
python -m market_sim.financial_validation --input simulation_results.csv --write
```

The CSV is a detached single path without a matching seed/configuration
manifest. Its diagnostics are illustrative provenance history only and are
superseded by the completed multi-seed campaign in Section 6.

## 6. Multi-seed financial validation (completed, 30 seeds)

The fixed-parameter financial validation campaign is distinct from the policy
LHS and is dry-run-first. The completed campaign lives in
`results/financial_validation/pilot_30seeds/`: 30 independent seeds, horizon
10,000 days, burn-in 2,000 days, baseline `current_eu_supervision` regime,
with `daily_market.csv` and `order_book_events.csv` per seed and a provenance
and integrity manifest per seed plus `aggregate_manifest.json`. The read-only
preflight verifies the stored campaign without simulating:

```bash
python run_financial_validation_campaign.py \
    --output-root results/financial_validation/pilot_30seeds \
    --seeds 30 --horizon 10000 --burn-in 2000 \
    --regime current_eu_supervision --write-order-book-events
```

Completed seed outputs can be re-analysed without simulation:

```bash
python -m market_sim.financial_validation \
    --campaign-root results/financial_validation/pilot_30seeds --write \
    --output-dir results/financial_validation/pilot_30seeds/diagnostics
```

Aggregate classifications (seed as unit of inference): volatility
clustering, positive spread/depth, trade-sign persistence, and cancellation
activity reproduced (30/30 each); fat tails, volume-volatility, and weak
linear return autocorrelation partially reproduced; positive price impact
**not reproduced** (26/30 seeds). See
`docs/FINANCIAL_VALIDATION_CAMPAIGN.md` for schemas and interpretation
limits.

## 6a. Static price-feedback audits

Two read-only audits document that firm environmental decisions contain no
own-share-price feedback (the basis for the paper's market-response framing):

```bash
python audit_firm_price_feedback.py
python audit_paper_price_feedback_materiality.py
```

Outputs are in `results/audits/`. They parse Python source and the
manuscript-support documents; they never execute a simulation.

## 7. Parameter registry and interpretation

```bash
python -m market_sim.parameter_registry --csv docs/parameter_registry.csv \
    --markdown docs/PARAMETER_REGISTRY.md
```

Always report policy effects as within-model paired comparisons. Composite
rankings must be accompanied by raw effects, Pareto frequency, alternative
weights, horizon, participation assumptions, and the explicit statement that
simulation-scale euros are not EU budget estimates.

## 8. Versioning statement

All completed simulation evidence is version 1 and unchanged by the July 2026
manuscript revision, which touched only the manuscript and documentation:

- Global LHS campaign (`results/raw/`, `results/summaries/`,
  `results/figures/`): recorded against code version
  `1645f3589408503894c7e8f44a92ffe382a9a5b4+dirty`.
- Replication robustness extension (`results/replication_robustness/`) and
  financial validation campaign (`results/financial_validation/pilot_30seeds/`):
  recorded against commit `00134a694e653fc2ce74b62eab1e8c6e9d0f67f7` with a
  dirty working tree; each manifest stores the source-tree SHA-256 and the
  working-tree status hash.
- Because both campaigns record `+dirty` trees, the archival release must
  either preserve the exact dirty-tree diff alongside the tagged commit or
  reproduce the outputs from a clean tagged tree before claiming bit-level
  reproducibility. Until then, manifests are the authoritative provenance.
- No output directory may be rewritten in place. A substantive model change
  (for example a future market-discipline extension) requires new versioned
  output roots and a fresh seed schedule; existing outputs would then be
  marked archival, never deleted.
