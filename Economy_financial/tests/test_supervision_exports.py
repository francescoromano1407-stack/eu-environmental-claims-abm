import csv
import math
import random

from market_sim.simulation import (
    Simulation,
    export_claim_audit_log,
    export_regulatory_cases,
    export_simulation_metrics,
)


LEGACY_PREFIX = [
    'day', 'asset_price', 'corporate_balance',
    'noise_count', 'fundamentalist_count', 'chartist_count',
    'noise_wealth', 'fundamentalist_wealth', 'chartist_wealth',
    'market_maker_wealth', 'manipulator_wealth',
]


def test_supervision_exports_append_columns_and_write_separate_ledgers(tmp_path):
    random.seed(17)
    sim = Simulation(
        num_traders=6, num_manipulators=0, enable_credit=False,
        enable_esg=True, enable_greenwashing_supervision=True, days=60)
    sim.run()
    metrics = tmp_path / "metrics.csv"
    claims = tmp_path / "claims.csv"
    cases = tmp_path / "cases.csv"
    export_simulation_metrics(sim, str(metrics))
    export_claim_audit_log(sim, str(claims))
    export_regulatory_cases(sim, str(cases))

    with metrics.open(newline='', encoding='utf-8') as handle:
        rows = list(csv.reader(handle))
    assert rows[0][:len(LEGACY_PREFIX)] == LEGACY_PREFIX
    assert 'mean_greenhushing_gap' in rows[0]
    assert 'consumer_gross_revenue' in rows[0]
    assert 'BRN1_employee_trust' in rows[0]
    assert len(rows) == sim.days + 2
    assert all(len(row) == len(rows[0]) for row in rows)

    with claims.open(newline='', encoding='utf-8') as handle:
        claim_rows = list(csv.DictReader(handle))
    with cases.open(newline='', encoding='utf-8') as handle:
        case_rows = list(csv.DictReader(handle))
    assert claim_rows and case_rows
    assert 'rule_ids' in claim_rows[0]
    assert 'state_history' in case_rows[0]


def test_all_supervision_series_are_aligned_and_bounded():
    random.seed(19)
    sim = Simulation(
        num_traders=6, num_manipulators=0, enable_credit=False,
        enable_esg=True, enable_greenwashing_supervision=True, days=120)
    sim.run()
    series = [
        sim.log_greenhushing_gap,
        sim.log_regulatory_cases,
        sim.log_supervision_precision,
        sim.log_supervision_recall,
        sim.log_consumer_gross_revenue,
        sim.log_workforce_trust,
        sim.log_workforce_productivity,
        sim.log_workforce_turnover,
    ]
    assert all(len(values) == sim.days for values in series)
    assert all(math.isfinite(value) for values in series for value in values)
    assert all(0.0 <= value <= 1.0
               for value in sim.log_supervision_precision
               + sim.log_supervision_recall + sim.log_workforce_trust)
    assert all(0.97 <= value <= 1.0
               for value in sim.log_workforce_productivity)
    assert all(0.0 <= value <= 0.30
               for value in sim.log_workforce_turnover)
    assert sim.consumer_market.ledger.cumulative_gross_revenue \
        == sim.days * sim.consumer_daily_budget
