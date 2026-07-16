"""
Operational entry point.

Seeds the global RNG for reproducible runs, instantiates the orchestration
loop with the canonical production configuration, and triggers the
analytical export and plotting pipelines.

This is the ONLY module in the package with an `if __name__ == '__main__':`
execution block; every other module is import-side-effect free.

Run from the directory containing the `market_sim` package:

    python -m market_sim.main
"""

from __future__ import annotations

import random

from market_sim.simulation import (
    Simulation,
    export_claim_audit_log,
    export_regulatory_cases,
    export_simulation_metrics,
)

# Reproducibility anchor: seed 42 reproduces the validated reference run
# (price corridor ~80-130 around the drifting fundamental, no stagnation,
# no systemic crashes) bit-for-bit.
DEFAULT_SEED = 42


def main(seed: int = DEFAULT_SEED) -> Simulation:
    """Runs the simulation with the Credit, ESG and (Part G) regulatory
    greenwashing frameworks enabled."""
    random.seed(seed)

    sim = Simulation(num_traders=100, initial_cash=10_000.0,
                     initial_shares=100, initial_price=100.0,
                     rf_rate=0.03, days=2000, num_manipulators=2,
                     enable_credit=True,
                     enable_esg=True,
                     enable_regulation=True,
                     enable_greenwashing_supervision=True)

    sim.run()
    export_simulation_metrics(sim, "simulation_results.csv")
    export_claim_audit_log(sim, "environmental_claim_audit_log.csv")
    export_regulatory_cases(sim, "greenwashing_regulatory_cases.csv")
    sim.plot_dashboard("market_simulation_dashboard.png")
    return sim

if __name__ == '__main__':
    main()
