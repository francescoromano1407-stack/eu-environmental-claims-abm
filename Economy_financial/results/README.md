# Global LHS campaign

> Simulation-based policy experiment; not an empirical forecast.

`configuration.json` is the complete requested design; `manifest.json` records its execution state.  Every raw draw is atomic and resumable.  Latent-truth metrics are evaluator-only research metrics and are never agent inputs.

- `raw/<horizon>/draw_*.json`: one completed LHS configuration with all paired replications and metric families.
- `summaries/`: copied machine-readable summaries and flat tables.
- `figures/`: publication figures created after at least one horizon is available.
- `raw/<horizon>/failed_runs.json`: atomic failure record, if any.
