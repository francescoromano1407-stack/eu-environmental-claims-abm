"""Part J (Workstream E) stress tests: extreme populations, extreme
capacities, extreme failure rates, and numerical-integrity checks."""

import math
import random

import pytest

from market_sim.environmental_claims import FirmProfile
from market_sim.greenwashing_supervision import SupervisionParameters
from market_sim.parameter_registry import gsa_defaults
from market_sim.policy_comparison import PolicyOutcomeEvaluator
from market_sim.policy_regimes import (
    ConnectorParameters,
    GreenwashingPolicyRegime,
    PrescreeningParameters,
)
from market_sim.sensitivity_campaign import _validate_metrics
from market_sim.simulation import Simulation


def _profiles(strategy: str) -> list[FirmProfile]:
    return [FirmProfile(f"S{i}", 0.10 + 0.08 * i, strategy,
                        400_000_000 + 40_000_000 * i, 800 + 100 * i)
            for i in range(8)]


def _run(days=120, seed=42, regime=GreenwashingPolicyRegime
         .CURRENT_EU_SUPERVISION, **extra) -> Simulation:
    random.seed(seed)
    sim = Simulation(num_traders=8, num_manipulators=0,
                     enable_credit=False, enable_esg=True,
                     enable_greenwashing_supervision=True, days=days,
                     greenwashing_policy_regime=regime, **extra)
    sim.run()
    return sim


def _check_integrity(sim: Simulation) -> dict:
    metrics = PolicyOutcomeEvaluator().evaluate(sim)
    _validate_metrics(metrics, -1, "stress", -1)
    for venue in sim.venues:
        assert venue.asset.balance >= 0.0
        workforce = venue.asset.workforce
        assert workforce.employee_count >= 0.0
        assert workforce.onboarding_employees >= 0.0
        assert 0.0 <= workforce.trust <= 1.0
        assert math.isfinite(venue.asset.get_last_price())
    if sim.consumer_market is not None:
        sim.consumer_market.ledger.validate()
    supervisor = sim.greenwashing_supervisor
    assert float(supervisor.total_penalties_dec) \
        == pytest.approx(supervisor.total_penalties, abs=0.05)
    return metrics


def test_all_honest_population():
    sim = _run(asset_profiles=_profiles("honest"))
    metrics = _check_integrity(sim)
    assert metrics["strategic_material_overstatements"] == 0.0


def test_all_greenwasher_population():
    sim = _run(asset_profiles=_profiles("greenwasher"))
    metrics = _check_integrity(sim)
    assert metrics["original_material_overstatements"] > 0.0


def test_all_adaptive_population():
    sim = _run(asset_profiles=_profiles("adaptive"))
    _check_integrity(sim)


def test_zero_supervision_capacity():
    sim = _run(supervision_parameters=SupervisionParameters(
        evidence_request_capacity=0, investigation_capacity=0))
    metrics = _check_integrity(sim)
    assert metrics["true_positives"] == 0.0
    assert sim.greenwashing_supervisor.total_penalties == 0.0


def test_extreme_capacity():
    sim = _run(supervision_parameters=SupervisionParameters(
        evidence_request_capacity=500, investigation_capacity=100))
    _check_integrity(sim)
    # With abundant capacity nothing waits for an investigation slot;
    # the only open cases are running correction windows.
    supervisor = sim.greenwashing_supervisor
    assert len(supervisor._investigation_queue) == 0
    from market_sim.environmental_claims import CaseState
    for case in supervisor.cases:
        if case.closed_day is None:
            assert case.state in {CaseState.CORRECTION_WINDOW,
                                  CaseState.CONFLICT_RESOLUTION}


def test_high_conflict_rate_connector():
    sim = _run(
        regime=GreenwashingPolicyRegime.CERTIFIED_GREEN_DATA_CONNECTOR,
        days=240,
        connector_parameters=ConnectorParameters(
            register_error_probability=0.5, mismatch_probability=0.3))
    metrics = _check_integrity(sim)
    # Heavy source error must load the dispute channel, not the sanction
    # channel: escalation still requires corroboration.
    supervisor = sim.greenwashing_supervisor
    assert metrics["conflict_cases_opened"] > 0.0
    for case in supervisor.cases:
        if case.conflict_case and case.conflict_outcome != \
                "escalated_corroborated":
            assert case.applied_penalty == 0.0


def test_full_connector_downtime():
    sim = _run(
        regime=GreenwashingPolicyRegime.CERTIFIED_GREEN_DATA_CONNECTOR,
        connector_parameters=ConnectorParameters(
            downtime_probability=1.0, cyber_incident_probability=0.0))
    _check_integrity(sim)
    assert sim.green_data_connector.transfers == 0
    assert sim.green_data_connector.downtime_events > 0


def test_maximum_hub_noise_and_strictness():
    sim = _run(
        regime=GreenwashingPolicyRegime.SME_ALGORITHMIC_PRESCREENING,
        prescreening_parameters=PrescreeningParameters(
            strictness=0.95, noise=0.50))
    metrics = _check_integrity(sim)
    # An over-strict, noisy hub must be able to hurt: withdrawals occur.
    assert sim.prescreening_hub.withdrawals > 0


def test_gsa_bounds_extreme_corner_runs():
    """Both corners of the sampled hypercube run to completion with
    finite metrics (guards the campaign against nonsense regions)."""
    from market_sim.parameter_registry import (build_simulation_kwargs,
                                               gsa_space)
    lows = {name: spec.low for name, spec in gsa_space().items()}
    highs = {name: spec.high for name, spec in gsa_space().items()}
    for corner in (lows, highs):
        kwargs = build_simulation_kwargs(corner)
        random.seed(7)
        sim = Simulation(
            num_traders=8, num_manipulators=0, enable_credit=False,
            enable_esg=True, enable_greenwashing_supervision=True,
            days=120,
            greenwashing_policy_regime=GreenwashingPolicyRegime
            .HYBRID_PRESCREENING_AND_CONNECTOR, **kwargs)
        sim.run()
        evaluator = PolicyOutcomeEvaluator(
            discount_rate_annual=corner["social_discount_rate"])
        metrics = evaluator.evaluate(sim)
        _validate_metrics(metrics, -1, "corner", -1)


def test_legacy_disabled_path_untouched_by_part_j():
    """The Part J code paths are inert when supervision is disabled."""
    random.seed(42)
    sim = Simulation(days=30, num_traders=6, num_manipulators=0,
                     enable_credit=False)
    sim.run()
    assert sim.greenwashing_supervisor is None
    assert not sim._pending_reverifications
    assert sim._reverification_sequence == 0
