"""Part H tests: comparative efficiency, scoring, Pareto, horizons.

The synthetic-metric tests exercise the scoring machinery directly; the
end-to-end tests run small paired comparisons with common random numbers.
"""

import csv
import math
import os
import random

import pytest

from market_sim.policy_comparison import (
    DEFAULT_WEIGHT_SCENARIOS,
    PolicyOutcomeEvaluator,
    PolicyScoreWeights,
    composite_scores,
    pareto_frontier,
    run_greenwashing_policy_comparison,
)
from market_sim.policy_regimes import GreenwashingPolicyRegime
from market_sim.simulation import Simulation


def _metrics(**overrides) -> dict:
    """A neutral, complete metric dictionary for scoring tests."""
    base = {
        "true_material_overstatements": 10.0,
        "severity_weighted_greenwashing": 2.0,
        "precision": 0.8, "recall": 0.7,
        "evidence_quality_mean": 0.6,
        "state_policy_cost": 1000.0, "regulator_time_cost": 500.0,
        "firm_policy_cost": 300.0, "firm_reporting_cost": 200.0,
        "false_positives": 2.0,
        "mean_greenhushing_gap": 0.10,
        "withheld_truthful_claims": 1.0,
        "voluntary_claims_published": 50.0,
        "privacy_cyber_incidents": 0.0,
    }
    base.update(overrides)
    return base


def test_greater_true_prevention_improves_reduction_metric():
    metrics = {"A": _metrics(),
               "B": _metrics(severity_weighted_greenwashing=0.5,
                             true_material_overstatements=4.0)}
    scores = composite_scores(metrics, PolicyScoreWeights())
    assert scores["B"] > scores["A"]


def test_false_positives_reduce_efficiency():
    metrics = {"A": _metrics(), "B": _metrics(false_positives=12.0)}
    scores = composite_scores(metrics, PolicyScoreWeights())
    assert scores["B"] < scores["A"]


def test_greenhushing_reduces_efficiency_independently():
    metrics = {"A": _metrics(),
               "B": _metrics(mean_greenhushing_gap=0.35,
                             withheld_truthful_claims=8.0)}
    scores = composite_scores(metrics, PolicyScoreWeights())
    assert metrics["A"]["severity_weighted_greenwashing"] \
        == metrics["B"]["severity_weighted_greenwashing"]
    assert scores["B"] < scores["A"]


def test_administrative_cost_reduces_efficiency():
    metrics = {"A": _metrics(),
               "B": _metrics(state_policy_cost=90_000.0,
                             regulator_time_cost=20_000.0)}
    scores = composite_scores(metrics, PolicyScoreWeights())
    assert scores["B"] < scores["A"]


def test_rankings_respond_correctly_to_weight_changes():
    cheap_inaccurate = _metrics(state_policy_cost=100.0,
                                regulator_time_cost=50.0,
                                precision=0.55, recall=0.45)
    costly_accurate = _metrics(state_policy_cost=80_000.0,
                               regulator_time_cost=10_000.0,
                               precision=0.99, recall=0.95)
    metrics = {"cheap": cheap_inaccurate, "accurate": costly_accurate}
    cost_scores = composite_scores(
        metrics, PolicyScoreWeights(name="cost", public_cost=5.0,
                                    accuracy_gain=0.1))
    accuracy_scores = composite_scores(
        metrics, PolicyScoreWeights(name="acc", public_cost=0.1,
                                    accuracy_gain=5.0))
    assert max(cost_scores, key=cost_scores.get) == "cheap"
    assert max(accuracy_scores, key=accuracy_scores.get) == "accurate"


def test_pareto_dominance_is_calculated_correctly():
    dominant = _metrics(severity_weighted_greenwashing=0.1,
                        state_policy_cost=10.0, regulator_time_cost=0.0,
                        mean_greenhushing_gap=0.01,
                        withheld_truthful_claims=0.0,
                        precision=0.99, recall=0.99)
    dominated = _metrics(severity_weighted_greenwashing=5.0,
                         state_policy_cost=90_000.0,
                         regulator_time_cost=5_000.0,
                         mean_greenhushing_gap=0.40,
                         withheld_truthful_claims=9.0,
                         precision=0.50, recall=0.40)
    middle = _metrics(severity_weighted_greenwashing=0.05,
                      state_policy_cost=95_000.0,
                      regulator_time_cost=5_000.0)
    frontier = pareto_frontier({"good": dominant, "bad": dominated,
                                "tradeoff": middle})
    assert "good" in frontier
    assert "bad" not in frontier
    assert "tradeoff" in frontier   # Better on one axis, worse on another.


def test_no_regime_receives_privileged_truth_access():
    """The evaluator is the ONLY truth reader, and only ex post: policy
    components never hold a reference to the truth ledger, and connector
    measurements carry error against the physical state."""
    random.seed(47)
    sim = Simulation(
        num_traders=8, num_manipulators=0, enable_credit=False,
        enable_esg=True, enable_greenwashing_supervision=True, days=70,
        greenwashing_policy_regime=GreenwashingPolicyRegime
        .HYBRID_PRESCREENING_AND_CONNECTOR)
    sim.run()
    truth = sim._evaluation_truth_by_claim
    for component in (sim.prescreening_hub, sim.green_data_connector,
                      sim.greenwashing_supervisor):
        for value in vars(component).values():
            assert value is not truth
    connector = sim.green_data_connector
    exact_hits = 0
    comparisons = 0
    for record in connector.provenance:
        venue = next(v for v in sim.venues
                     if v.symbol == record.firm_symbol)
        true_now = venue.asset.environmental_facts.value_for(
            next(s.subject for s in connector.parameters.sources
                 if s.kind.value == record.source_kind))
        comparisons += 1
        if record.estimate == true_now:
            exact_hits += 1
    assert comparisons > 0
    assert exact_hits < comparisons   # Metered, not copied.


def test_comparison_runner_csv_and_alignment():
    csv_path = os.path.join(os.path.dirname(__file__),
                            "_tmp_comparison.csv")
    try:
        report = run_greenwashing_policy_comparison(
            dict(num_traders=8, num_manipulators=0, enable_credit=False,
                 enable_esg=True, days=120),
            replications=2, common_seed=11, csv_path=csv_path)
        with open(csv_path, newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        assert rows[0][0] == "policy_regime"
        assert len(rows) == 1 + 3 * 2     # Header + 3 regimes x 2 reps.
        assert report.rankings_by_scenario
        assert report.pareto_regimes
        assert set(report.mean_metrics) == {
            regime.value for regime in (
                GreenwashingPolicyRegime.CURRENT_EU_SUPERVISION,
                GreenwashingPolicyRegime.SME_ALGORITHMIC_PRESCREENING,
                GreenwashingPolicyRegime.CERTIFIED_GREEN_DATA_CONNECTOR)}
        # Paired replications: rows for the same replication share the
        # market seed (common random numbers).
        seeds = {}
        for row in report.rows:
            seeds.setdefault(row.replication, set()).add(row.market_seed)
        assert all(len(values) == 1 for values in seeds.values())
        # Every metric is finite.
        for row in report.rows:
            for key, value in row.metrics.items():
                assert math.isfinite(value), key
    finally:
        if os.path.exists(csv_path):
            os.remove(csv_path)


def test_same_regime_reruns_are_deterministic():
    def _run() -> dict:
        report = run_greenwashing_policy_comparison(
            dict(num_traders=6, num_manipulators=0, enable_credit=False,
                 enable_esg=True, days=70),
            regimes=[GreenwashingPolicyRegime.SME_ALGORITHMIC_PRESCREENING],
            replications=1, common_seed=13)
        return report.rows[0].metrics

    assert _run() == _run()


@pytest.mark.parametrize("days", [120, 365])
def test_multi_horizon_comparisons_produce_aligned_finite_series(days):
    report = run_greenwashing_policy_comparison(
        dict(num_traders=6, num_manipulators=0, enable_credit=False,
             enable_esg=True, days=days),
        replications=1, common_seed=17)
    for row in report.rows:
        assert all(math.isfinite(value) for value in row.metrics.values())
    assert len(report.mean_metrics) == 3


def test_two_thousand_day_comparison_succeeds():
    report = run_greenwashing_policy_comparison(
        dict(num_traders=6, num_manipulators=0, enable_credit=False,
             enable_esg=True, days=2000),
        replications=1, common_seed=19)
    for row in report.rows:
        assert all(math.isfinite(value) for value in row.metrics.values())


def test_default_weight_scenarios_are_labeled_experiment():
    assert DEFAULT_WEIGHT_SCENARIOS[0].name == "default_experiment"
    evaluator = PolicyOutcomeEvaluator()
    assert evaluator is not None
