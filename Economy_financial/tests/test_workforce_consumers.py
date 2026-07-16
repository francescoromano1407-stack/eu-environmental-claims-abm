from datetime import date
import random
from types import SimpleNamespace

from market_sim.consumer_market import ConsumerMarket
from market_sim.environmental_claims import (
    ClaimAudience,
    ClaimChannel,
    ClaimSubject,
    ClaimType,
    EnvironmentalClaim,
    EvidenceRecord,
    EvidenceSource,
)
from market_sim.models import Asset
from market_sim.workforce import WorkforceState


def _venue(symbol, score, evidence_estimate, visible=True):
    asset = Asset(symbol, green_score=score)
    asset.q_truthful_benchmark = score
    asset.greenhushing_gap = 0.0 if visible else score
    if visible:
        claim = EnvironmentalClaim(
            f"C-{symbol}", symbol, 1, date(2026, 1, 1),
            ClaimChannel.MARKETING, ClaimAudience.CONSUMERS,
            ClaimType.QUANTITATIVE, ClaimSubject.GREEN_SCORE, score,
            "score_0_1", date(2025, 1, 1), date(2025, 12, 31),
            "group", "scope_1_2_3", (f"E-{symbol}",),
            stated_uncertainty=0.01)
        evidence = EvidenceRecord(
            f"E-{symbol}", symbol, ClaimSubject.GREEN_SCORE,
            date(2025, 1, 1), date(2025, 12, 31), evidence_estimate,
            0.01, EvidenceSource.COMPANY_RECORD, 1.0, 0.3,
            accessible_to_consumers=True)
        asset.claim_history.append(claim)
        asset.evidence_history.append(evidence)
    return SimpleNamespace(symbol=symbol, asset=asset)


def test_employee_trust_productivity_turnover_and_slow_recovery():
    workforce = WorkforceState(1200, trust=0.85)
    workforce.observe_internal_signal(0.90, 0.40, 0.02,
                                      confirmed_abuse=True, current_day=1)
    damaged = workforce.trust
    assert damaged < 0.85
    assert 0.97 <= workforce.productivity_multiplier <= 1.0
    assert 0.10 <= workforce.annual_turnover_rate <= 0.30
    workforce.observe_internal_signal(0.40, 0.40, 0.10, current_day=2)
    assert workforce.trust > damaged
    assert workforce.trust - damaged < 0.01


def test_turnover_hiring_onboarding_and_rolling_average():
    workforce = WorkforceState(1000, trust=0.0)
    rng = random.Random(3)
    first = workforce.daily_step(rng, 1, hiring_capacity=100)
    assert first["departures"] >= 0.0
    assert workforce.onboarding_employees == first["hires"]
    for day in range(2, 32):
        workforce.daily_step(rng, day, hiring_capacity=100)
    assert workforce.cumulative_hires >= first["hires"]
    assert workforce.average_employees_365d > 0.0
    assert len(workforce._headcount_history) == 32


def test_perceived_discrepancy_monotonically_reduces_demand():
    honest_venues = [_venue("F", 0.8, 0.8), _venue("R", 0.5, 0.5)]
    suspect_venues = [_venue("F", 0.8, 0.2), _venue("R", 0.5, 0.5)]
    honest = ConsumerMarket(1000.0)
    suspect = ConsumerMarket(1000.0)
    honest_flow = honest.step(1, honest_venues, random.Random(11))[0]
    suspect_flow = suspect.step(1, suspect_venues, random.Random(11))[0]
    assert suspect_flow.perceived_discrepancy \
        > honest_flow.perceived_discrepancy
    assert suspect_flow.gross_revenue < honest_flow.gross_revenue


def test_greenhushing_removes_green_premium_without_controversy_shock():
    visible = [_venue("F", 0.8, 0.8, True),
               _venue("R", 0.4, 0.4, True)]
    quiet = [_venue("F", 0.8, 0.8, False),
             _venue("R", 0.4, 0.4, True)]
    visible_flow = ConsumerMarket(1000).step(
        1, visible, random.Random(4))[0]
    quiet_market = ConsumerMarket(1000)
    quiet_flow = quiet_market.step(1, quiet, random.Random(4))[0]
    assert quiet_flow.gross_revenue < visible_flow.gross_revenue
    assert quiet_flow.perceived_discrepancy == 0.0
    assert all(belief.controversy == 0.0
               for key, belief in quiet_market.beliefs.items()
               if key[1] == "F")


def test_consumer_budget_and_external_flow_ledger_conserve():
    market = ConsumerMarket(1000.0)
    venues = [_venue("A", 0.7, 0.7), _venue("B", 0.3, 0.3)]
    for day in range(1, 11):
        market.step(day, venues, random.Random(day))
    market.ledger.validate()
    assert market.ledger.cumulative_gross_revenue == 10_000.0
    assert abs(market.ledger.cumulative_external_production_cost
               + market.ledger.cumulative_corporate_margin
               - 10_000.0) < 1e-8
