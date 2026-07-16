# Reproducibility guide — Part J replication package

Everything below runs from the repository root
(`Economy_financial/`) with Python 3.12, `numpy`, `matplotlib` and
`pytest`. All commands are deterministic given the stated seeds; the
campaign engine re-seeds every regime arm explicitly, so results do not
depend on execution order or on prior runs.

Code version used for the shipped results: see `code_version` inside
each `results/campaign_*/manifest.json` (recorded automatically as
`git rev-parse HEAD`, suffixed `+dirty` when the working tree differed).

## 1. Test suite

```bash
python -m pytest tests/ -q
```

Expected: all tests pass (143 as of Part J: 109 pre-existing + 12
conflict-resolution + 12 campaign + 10 stress). The suite includes the
legacy-trajectory regression (`enable_greenwashing_supervision=False`
unchanged), same-seed and regime-order invariance, campaign resume, and
no-truth-leakage checks.

## 2. Global sensitivity campaigns (exact shipped configuration)

For a new publication-campaign directory with the complete artifact
contract (timestamped root, `configuration.json`, logs, raw run-level table,
summaries and figures), use the top-level driver:

```bash
# Required 120-day campaign; creates results/global_lhs_campaign/YYYYMMDD_HHMMSS/
python run_global_lhs_campaign.py

# Add complete 365-, 1,000-, and 2,000-day robustness campaigns (200 draws each)
python run_global_lhs_campaign.py --full-robustness

# Resume exactly the same timestamped campaign after interruption
python run_global_lhs_campaign.py --resume results/global_lhs_campaign/YYYYMMDD_HHMMSS \
    --full-robustness
```

The driver refuses a non-publication design below 200 LHS draws, three paired
replications, or 120 days unless `--development` is explicitly supplied. It
uses only registry entries classified `STYLIZATION` or `EXPERIMENT`, records
their code locations/bounds/defaults/justifications, and keeps all
latent-truth metrics strictly research-only.

The lower-level commands below reproduce the historical shipped campaigns.

```bash
# 120-day global screening: 200 LHS draws x 3 paired replications
python -m market_sim.sensitivity_campaign --outdir results/campaign_120d \
    --draws 200 --replications 3 --horizon 120 --label c120

# 365-day confirmation on the 60-draw policy-relevant subset
python -m market_sim.sensitivity_campaign --outdir results/campaign_365d \
    --draws 200 --replications 3 --horizon 365 --label c365 \
    --subset "3,5,9,10,11,14,15,18,20,21,22,27,28,31,36,44,45,50,51,54,55,58,59,61,65,66,68,73,76,77,88,89,92,97,108,109,113,115,116,123,124,128,129,136,137,138,141,146,147,151,154,159,172,175,184,187,188,192,194,199"

# Long-horizon robustness on representative draws
python -m market_sim.sensitivity_campaign --outdir results/campaign_1000d \
    --draws 200 --replications 3 --horizon 1000 --label c1000 --subset "3,5,10,18,20,36"
python -m market_sim.sensitivity_campaign --outdir results/campaign_2000d \
    --draws 200 --replications 3 --horizon 2000 --label c2000 --subset "3,5,10"
```

Notes:

* `--draws 200` always regenerates the SAME design matrix (it is a
  function of the master seed and the draw count); `--subset` selects
  which draws to execute, so subset campaigns stay point-identical to
  the screening campaign's parameters.
* The default master seed is `20260716`; pass `--master-seed` to vary.
  Seed schedule (also in every manifest):
  `market_seed = master_seed + 1000000*draw + 1000*rep`,
  `supervision_seed = 104729 + 104729*draw + 7919*rep`.
* Interrupted campaigns resume with the identical command; completed
  draw files are validated (`"complete": true`) and never recomputed or
  overwritten. A conflicting design on an existing output directory is
  refused.
* Subset-selection rules are recorded in
  `results/subset_selection_365d.json` and
  `results/subset_selection_long.json` and were derived only from the
  120-day screening summary (selection script embedded there).
* Approximate runtimes on one modern desktop core: 120d campaign ~4
  minutes; 365d subset ~4 minutes; 1000d+2000d subsets ~3 minutes.
* CI / development mode: any smaller `--draws/--replications/--horizon`
  combination, e.g.
  `python -m market_sim.sensitivity_campaign --outdir tmp/ci --draws 4 --replications 2 --horizon 60`.
* To re-aggregate without running: add `--summary-only`.
* To add the hybrid arm: `--include-hybrid` (not part of the shipped
  default comparison).

## 3. Figures, tables and appendix documents

```bash
python -m market_sim.campaign_reporting --results results --out results/figures
python -m market_sim.parameter_registry --csv docs/parameter_registry.csv \
    --markdown docs/PARAMETER_REGISTRY.md
```

`campaign_reporting` also produces `results/default_comparison.json`
(5 paired replications, 365 days, registry-default parameters) the
first time it runs; delete the file to force recomputation.

## 4. Single-run ledgers and dashboard

```bash
python -m market_sim.main
```

writes `simulation_results.csv`, `environmental_claim_audit_log.csv`,
`greenwashing_regulatory_cases.csv` and
`market_simulation_dashboard.png` for one fully-enabled 365-day run
(see `docs/EU_GREENWASHING_MODEL.md` §11).

## 5. Interpretation rules

See `docs/EU_GREENWASHING_MODEL.md` §15 (Part J). In short: every
number is a simulation output under stylized parameters; paired
differences are model policy-experiment orderings, not empirical
predictions; rankings must always be reported conditional on horizon,
discount rate, weights and participation assumptions.
