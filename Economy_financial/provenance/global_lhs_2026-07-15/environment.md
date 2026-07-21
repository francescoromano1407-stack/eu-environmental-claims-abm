# Recoverable execution environment

## Directly recorded by the campaign

| Field | Recorded value |
|---|---|
| Campaign creation | `2026-07-16T14:43:22Z` |
| Campaign completion | `2026-07-16T14:56:55Z` |
| Recorded command | `run_global_lhs_campaign.py --full-robustness` |
| Code version | `1645f3589408503894c7e8f44a92ffe382a9a5b4+dirty` |
| Status | `complete`; no failures recorded |
| LHS draws | 200 |
| Replications per draw and regime | 3 |
| Regimes | `current_eu_supervision`; `sme_algorithmic_prescreening`; `certified_green_data_connector` |
| Horizons | 120, 365, 1,000, and 2,000 days |
| Traders | 8 |
| Manipulators | 0 |
| Credit layer | disabled (`enable_credit=false`) |
| Master seed | `20260716` |
| Supervision base seed | `104729` |
| Market-seed schedule | `master_seed + 1000000*draw + 1000*replication` |
| Supervision-seed schedule | `supervision_base_seed + 104729*draw + 7919*replication` |
| Common random numbers | both seeds reset for every regime within a replication |
| Discounting | `social_discount_rate` sampled per LHS draw; undiscounted ledgers retained |
| Interpretation notice | simulation-based policy experiment; not an empirical forecast |

The design implies 200 draws × 3 replications × 3 regimes × 4 horizons = 7,200 regime-replication evaluations in the preserved campaign outputs. The top-level manifest also records reuse of compatible earlier draw directories: 200 draws were imported for the 120-, 365-, and 1,000-day horizons and 173 for the 2,000-day horizon; the remaining 27 long-horizon draws were completed in the final campaign directory.

## Source and dependency evidence

The global manifests do **not** record the Python executable, exact Python patch version, operating-system build, hardware, package versions, a dependency lock file, a `pip freeze`, or source hashes. No `requirements*.txt`, `pyproject.toml`, Conda environment file, Pipfile, Poetry lock, or uv lock is present in the inspected project tree.

The candidate commit contains filenames ending in `.cpython-312.pyc`, which supports an inference that CPython 3.12 generated the cached bytecode. This is not a manifest-recorded interpreter version. CPython 3.12.13 was used only for the present read-only bytecode comparison and must not be reported as the original campaign's exact runtime version.

Inspection of the candidate source identifies these third-party runtime imports relevant to the campaign:

- `matplotlib` for non-interactive (`Agg`) figure generation;
- `numpy` in sensitivity-analysis calculations.

Their original versions are not recoverable from the campaign records. All other imports in the inspected campaign source are either Python standard-library modules or modules within `market_sim`.

## Recorded output assembly

The authoritative top-level manifest records that compatible completed draws were imported into the final campaign output. The final output logs show rapid assembly for the 120-, 365-, and 1,000-day horizons and approximately 802 seconds for the remaining 2,000-day work. These records describe output assembly and reuse; they do not add missing source identity or package-version evidence.

## What is intentionally not inferred

No current-machine package inventory, current worktree state, later financial-validation provenance, later audit source hashes, or later manuscript metadata is treated as evidence of the original campaign environment.
