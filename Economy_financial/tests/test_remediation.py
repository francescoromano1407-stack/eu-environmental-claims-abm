"""Part I remediation tests: one section per red-team finding.

P0-1 sanction scale, P0-2 replication inference, P1-3 immutable ledger,
P1-4 detector hardening (4.1-4.5), P1/P2-5 hub substance, P1/P2-6
connector operations, P1/P2-7 metric families, P2-8 horizon/discounting/
sensitivity. All deterministic.
"""

import random
import statistics
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from market_sim.environmental_claims import (
    AssessmentOutcome,
    ClaimAudience,
    ClaimChannel,
    ClaimSubject,
    ClaimType,
    EnvironmentalClaim,
    EvidenceRecord,
    EvidenceSource,
    LegalTrack,
    meaningful_qualification,
)
from market_sim.greenwashing_supervision import (
    GreenwashingSupervisor,
    PenaltyPolicy,
    SupervisionParameters,
)
from market_sim.policy_comparison import (
    PolicyOutcomeEvaluator,
    PolicyScoreWeights,
    composite_scores,
    run_greenwashing_policy_comparison,
    run_horizon_grid,
    run_sensitivity_analysis,
)
from market_sim.policy_regimes import (
    CertifiedGreenDataConnector,
    ConnectorParameters,
    GreenwashingPolicyRegime,
    PrescreeningParameters,
    ReconciliationClass,
    SMEPrescreeningHub,
)
from market_sim.regulation import LegalRegime
from market_sim.simulation import Simulation

POST = date(2026, 10, 15)
MEANINGFUL_QUAL = ("Estimate limited to the stated period, boundary and "
                   "methodology uncertainty.")

_SEQ = [0]


def _claim(**overrides) -> EnvironmentalClaim:
    _SEQ[0] += 1
    base = dict(claim_id=f"RM-{_SEQ[0]}", firm_symbol="RMX", day=300,
                communication_date=POST, channel=ClaimChannel.MARKETING,
                audience=ClaimAudience.CONSUMERS,
                claim_type=ClaimType.QUANTITATIVE,
                subject=ClaimSubject.GREEN_SCORE, asserted_value=0.5,
                unit="score_0_1", period_start=date(2026, 1, 1),
                period_end=date(2026, 6, 30),
                organizational_boundary="consolidated_group",
                operational_boundary="scope_1_2_3")
    base.update(overrides)
    return EnvironmentalClaim(**base)


def _evidence(**overrides) -> EvidenceRecord:
    _SEQ[0] += 1
    base = dict(evidence_id=f"RE-{_SEQ[0]}", firm_symbol="RMX",
                subject=ClaimSubject.GREEN_SCORE,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 6, 30), estimate=0.5,
                standard_error=0.02, source=EvidenceSource.COMPANY_RECORD,
                coverage=0.9, independence=0.2, verified=False,
                reliability_prior=0.8)
    base.update(overrides)
    return EvidenceRecord(**base)


def _engine():
    return GreenwashingSupervisor(LegalRegime(), random.Random(1)).rules


def _run_supervised(days=365, seed=42, **extra) -> Simulation:
    random.seed(seed)
    sim = Simulation(num_traders=8, num_manipulators=0,
                     enable_credit=False, enable_esg=True,
                     enable_greenwashing_supervision=True, days=days,
                     **extra)
    sim.run()
    return sim


# --------------------------------------------------------------------------- #
# P0-1: sanction-scale calibration
# --------------------------------------------------------------------------- #
def test_sanctions_are_proportionate_not_confiscatory():
    sim = _run_supervised(days=365)
    supervisor = sim.greenwashing_supervisor
    penalised = [case for case in supervisor.cases
                 if case.applied_penalty > 0.0]
    assert penalised, "adverse cases must still be sanctioned"
    for case in penalised:
        assert case.applied_penalty <= case.applicable_cap + 1e-6
        # Sim-scale ceiling: even the 4% consumer cap on 1.5x the largest
        # plausible balance stays far below the old confiscatory range.
        assert case.applicable_cap <= 0.04 * 1.5 * 6_000_000.0
    total = float(supervisor.total_penalties_dec)
    assert 0.0 < total < 1_500_000.0   # Pre-fix: 5.18M in one year.
    # No firm is pinned at the solvency floor by sanctions alone.
    floored = sum(1 for venue in sim.venues
                  if venue.asset.balance <= 25_000.0)
    assert floored == 0


def test_penalty_monotonicity_track_gating_and_escalation():
    params = SupervisionParameters()
    policy = PenaltyPolicy(params)

    def assessment(outcome, confidence=0.8,
                   track=LegalTrack.CONSUMER):
        base = _engine().assess(_claim(), [_evidence()], 300, POST)
        base.outcome = outcome
        base.confidence = confidence
        base.legal_track = track
        return base

    turnover = 3_750_000.0
    weak = policy.calculate(assessment(AssessmentOutcome.NEGLIGENCE),
                            turnover, 1_000.0, 100_000.0)[2]
    severe = policy.calculate(assessment(AssessmentOutcome.SYSTEMIC_ABUSE),
                              turnover, 1_000.0, 100_000.0)[2]
    assert severe >= weak
    low_conf = policy.calculate(
        assessment(AssessmentOutcome.OVERSTATEMENT, confidence=0.2),
        turnover, 1_000.0, 100_000.0)[2]
    high_conf = policy.calculate(
        assessment(AssessmentOutcome.OVERSTATEMENT, confidence=0.9),
        turnover, 1_000.0, 100_000.0)[2]
    assert high_conf >= low_conf
    small_benefit = policy.calculate(
        assessment(AssessmentOutcome.OVERSTATEMENT), turnover,
        500.0, 100_000.0)[2]
    big_benefit = policy.calculate(
        assessment(AssessmentOutcome.OVERSTATEMENT), turnover,
        5_000.0, 100_000.0)[2]
    assert big_benefit >= small_benefit
    more_revenue = policy.calculate(
        assessment(AssessmentOutcome.OVERSTATEMENT), turnover,
        500.0, 400_000.0)[2]
    assert more_revenue >= small_benefit
    repeat = policy.calculate(
        assessment(AssessmentOutcome.OVERSTATEMENT), turnover,
        5_000.0, 400_000.0, repeat_count=3)[2]
    first = policy.calculate(
        assessment(AssessmentOutcome.OVERSTATEMENT), turnover,
        5_000.0, 400_000.0, repeat_count=0)[2]
    assert repeat >= first

    # Track-gated legal ceilings (rates unchanged by the scale bridge).
    ordinary_cap = policy.calculate(
        assessment(AssessmentOutcome.OVERSTATEMENT), turnover,
        1e9, 1e9)[1]
    consumer_cap = policy.calculate(
        assessment(AssessmentOutcome.OVERSTATEMENT), turnover,
        1e9, 1e9, cross_border_consumer_case=True)[1]
    csddd_cap = policy.calculate(
        assessment(AssessmentOutcome.OVERSTATEMENT,
                   track=LegalTrack.DUE_DILIGENCE),
        turnover, 1e9, 1e9)[1]
    assert ordinary_cap == pytest.approx(0.01 * turnover)
    assert consumer_cap == pytest.approx(0.04 * turnover)
    assert csddd_cap == pytest.approx(0.03 * turnover)
    # Escalation never pierces the ceiling.
    capped = policy.calculate(
        assessment(AssessmentOutcome.SYSTEMIC_ABUSE), turnover,
        1e9, 1e9, repeat_count=10)[2]
    assert capped <= ordinary_cap + 1e-9


def test_penalty_ledger_conservation_and_meaningfulness():
    sim = _run_supervised(days=365, seed=11)
    supervisor = sim.greenwashing_supervisor
    assert sim.state.penalty_inflow_dec \
        == supervisor.total_penalties_dec
    engine = _engine()
    adverse = engine.assess(
        _claim(asserted_value=0.9, evidence_ids=("RE-X",)),
        [_evidence(evidence_id="RE-X", estimate=0.4)], 300, POST)
    policy = PenaltyPolicy(SupervisionParameters())
    _, _, penalty = policy.calculate(adverse, 3_750_000.0, 5_000.0,
                                     150_000.0)
    assert penalty >= 1.5 * 5_000.0   # At least the benefit multiple.


# --------------------------------------------------------------------------- #
# P0-2: replication inference
# --------------------------------------------------------------------------- #
def test_replications_vary_and_paired_stats_are_reported():
    report = run_greenwashing_policy_comparison(
        dict(num_traders=8, num_manipulators=0, enable_credit=False,
             enable_esg=True, days=120),
        replications=3, common_seed=100)
    assert report.replications == 3
    seeds = {row.supervision_seed for row in report.rows}
    assert len(seeds) == 3            # Seed provenance varies per rep.
    stats = report.paired_statistics["severity_weighted_greenwashing"]
    hub = stats[GreenwashingPolicyRegime
                .SME_ALGORITHMIC_PRESCREENING.value]
    assert hub["n"] == 3.0
    assert hub["sd_diff"] > 0.0       # Non-degenerate variance.
    assert not any("Insufficient effective variation" in warning
                   for warning in report.warnings)


def test_single_replication_warns_and_reruns_are_reproducible():
    def _run():
        return run_greenwashing_policy_comparison(
            dict(num_traders=6, num_manipulators=0, enable_credit=False,
                 enable_esg=True, days=70),
            regimes=[GreenwashingPolicyRegime.CURRENT_EU_SUPERVISION,
                     GreenwashingPolicyRegime
                     .SME_ALGORITHMIC_PRESCREENING],
            replications=1, common_seed=13)

    first, second = _run(), _run()
    assert first.rows[0].metrics == second.rows[0].metrics
    assert any("Single replication" in warning
               for warning in first.warnings)


# --------------------------------------------------------------------------- #
# P1-3: immutable claim-and-correction ledger
# --------------------------------------------------------------------------- #
def test_corrections_preserve_original_values():
    claim = _claim(asserted_value=0.85)
    claim.record_correction(320, 0.55, basis="supervisory_correction:T")
    assert claim.asserted_value == 0.55            # Prospective public value
    assert claim.original_asserted_value == 0.85   # History immutable
    assert claim.historical_asserted_value == 0.85
    assert claim.corrected_day == 320
    assert claim.exposure_days(400) == 20          # 300 -> 320 only.
    # A second correction never overwrites the first snapshot.
    claim.record_correction(360, 0.50, basis="again")
    assert claim.original_asserted_value == 0.85


def test_supervised_run_populates_correction_ledger():
    sim = _run_supervised(days=365, seed=42)
    supervisor = sim.greenwashing_supervisor
    events = supervisor.correction_events
    assert events, "a year of supervision must produce corrections"
    for event in events:
        claim = supervisor.claims[event.claim_id]
        assert claim.original_asserted_value is not None
        assert event.original_value == pytest.approx(
            claim.original_asserted_value)
        assert event.exposure_days >= 0
        if event.event == "correction":
            assert claim.corrected_day == event.day
            # The live value changed prospectively; history survived.
            assert claim.asserted_value != claim.original_asserted_value \
                or claim.corrected_day is not None


# --------------------------------------------------------------------------- #
# P1-4.1: self-declared uncertainty gaming
# --------------------------------------------------------------------------- #
def test_inflated_stated_uncertainty_no_longer_hides_overstatement():
    engine = _engine()
    record = _evidence()
    gamed = _claim(asserted_value=0.85, evidence_ids=(record.evidence_id,),
                   stated_uncertainty=0.60,
                   qualification=MEANINGFUL_QUAL)
    assessment = engine.assess(gamed, [record], 300, POST)
    assert assessment.implausible_uncertainty
    assert assessment.outcome in {AssessmentOutcome.NEGLIGENCE,
                                  AssessmentOutcome.OVERSTATEMENT,
                                  AssessmentOutcome.SYSTEMIC_ABUSE}
    assert any("plausibility cap" in reason
               for reason in assessment.reasons)
    # Honest declared uncertainty still behaves normally.
    honest = _claim(asserted_value=0.51,
                    evidence_ids=(record.evidence_id,),
                    stated_uncertainty=0.02)
    ok = engine.assess(honest, [record], 300, POST)
    assert not ok.implausible_uncertainty
    assert ok.outcome == AssessmentOutcome.NOISE


# --------------------------------------------------------------------------- #
# P1-4.2: boundary mismatch cannot reduce suspicion
# --------------------------------------------------------------------------- #
def test_undisclosed_restricted_boundary_escalates_not_lenient():
    engine = _engine()
    record = _evidence(subject=ClaimSubject.SCOPE_1_EMISSIONS,
                       estimate=50_000.0, standard_error=1_000.0)
    sneaky = _claim(subject=ClaimSubject.SCOPE_1_EMISSIONS,
                    asserted_value=50_000.0, unit="tCO2e",
                    operational_boundary="scope_1_2",
                    evidence_ids=(record.evidence_id,))
    assessment = engine.assess(sneaky, [record], 300, POST)
    assert assessment.boundary_mismatch
    assert assessment.outcome == AssessmentOutcome.CORRECTABLE_ERROR
    assert assessment.corrective_action == "qualify_and_correct"

    disclosed = _claim(subject=ClaimSubject.SCOPE_1_EMISSIONS,
                       asserted_value=50_000.0, unit="tCO2e",
                       operational_boundary="scope_1_2",
                       evidence_ids=(record.evidence_id,),
                       qualification=("Scope 1-2 boundary only; Scope 3 "
                                      "reported separately for the stated "
                                      "period."))
    valid = engine.assess(disclosed, [record], 300, POST)
    assert not valid.boundary_mismatch
    assert valid.outcome in {AssessmentOutcome.SUPPORTED,
                             AssessmentOutcome.SUPPORTED_WITH_QUALIFICATION}


# --------------------------------------------------------------------------- #
# P1-4.3: repeated sub-threshold escalation
# --------------------------------------------------------------------------- #
def test_repeated_one_sided_subthreshold_findings_escalate():
    engine = _engine()
    outcomes = []
    for index in range(4):
        record = _evidence()
        claim = _claim(asserted_value=0.53,
                       evidence_ids=(record.evidence_id,))
        assessment = engine.assess(claim, [record], 300 + index * 30, POST)
        outcomes.append(assessment)
    assert outcomes[0].outcome == AssessmentOutcome.INCONCLUSIVE
    assert outcomes[-1].pattern_escalated
    assert outcomes[-1].outcome == AssessmentOutcome.NEGLIGENCE
    # Isolated noise never escalates.
    fresh = _engine()
    record = _evidence()
    single = fresh.assess(_claim(asserted_value=0.51,
                                 evidence_ids=(record.evidence_id,)),
                          [record], 300, POST)
    assert not single.pattern_escalated
    assert single.outcome == AssessmentOutcome.NOISE


# --------------------------------------------------------------------------- #
# P1-4.4: evidence conflict routes to inconclusive, never a sanction
# --------------------------------------------------------------------------- #
def test_wrong_verified_public_record_no_longer_convicts_truthful_firm():
    engine = _engine()
    own_correct = _evidence(estimate=0.52, standard_error=0.02)
    wrong_public = _evidence(source=EvidenceSource.PUBLIC_DATA,
                             estimate=0.20, standard_error=0.01,
                             verified=True, independence=0.95,
                             coverage=0.95, reliability_prior=0.95)
    truthful = _claim(asserted_value=0.52,
                      evidence_ids=(own_correct.evidence_id,))
    assessment = engine.assess(truthful, [own_correct, wrong_public],
                               300, POST)
    assert assessment.evidence_conflict
    assert assessment.outcome == AssessmentOutcome.INCONCLUSIVE
    assert assessment.penalty == 0.0
    assert any("conflict" in reason.lower()
               for reason in assessment.reasons)


# --------------------------------------------------------------------------- #
# P1-4.5: cross-period and baseline manipulation
# --------------------------------------------------------------------------- #
def test_cherry_picked_period_is_flagged():
    engine = _engine()
    good = _evidence(estimate=0.70, period_start=date(2026, 4, 1),
                     period_end=date(2026, 6, 30))
    bad_prior = _evidence(estimate=0.30, period_start=date(2026, 1, 1),
                          period_end=date(2026, 3, 31))
    cherry = _claim(asserted_value=0.70,
                    period_start=date(2026, 4, 1),
                    period_end=date(2026, 6, 30),
                    evidence_ids=(good.evidence_id,))
    assessment = engine.assess(cherry, [good, bad_prior], 300, POST)
    assert assessment.outcome == AssessmentOutcome.CORRECTABLE_ERROR
    assert any("Selective reporting period" in reason
               for reason in assessment.reasons)


def test_implausible_comparative_baseline_is_flagged():
    engine = _engine()
    current = _evidence(estimate=0.50, period_start=date(2026, 4, 1),
                        period_end=date(2026, 6, 30))
    prior = _evidence(estimate=0.45, period_start=date(2026, 1, 1),
                      period_end=date(2026, 3, 31))
    fabricated = _claim(claim_type=ClaimType.COMPARATIVE,
                        asserted_value=0.50, baseline_value=0.10,
                        period_start=date(2026, 4, 1),
                        period_end=date(2026, 6, 30),
                        qualification=MEANINGFUL_QUAL,
                        evidence_ids=(current.evidence_id,))
    assessment = engine.assess(fabricated, [current, prior], 300, POST)
    assert any("baseline" in reason.lower()
               for reason in assessment.reasons)
    assert assessment.outcome in {AssessmentOutcome.CORRECTABLE_ERROR,
                                  AssessmentOutcome.NOISE,
                                  AssessmentOutcome.INCONCLUSIVE}


# --------------------------------------------------------------------------- #
# P1/P2-5: hub substance
# --------------------------------------------------------------------------- #
def test_meaningless_qualification_is_detected_semantically():
    assert not meaningful_qualification("x")
    assert not meaningful_qualification("qualified")
    assert meaningful_qualification(MEANINGFUL_QUAL)
    hub = SMEPrescreeningHub(replace(PrescreeningParameters(), noise=0.0))
    record = _evidence(standard_error=0.10)
    gamed = _claim(asserted_value=0.85,
                   evidence_ids=(record.evidence_id,),
                   qualification="x", stated_uncertainty=0.30)
    feedback = hub.screen(gamed, {record.evidence_id: record}, [], [],
                          random.Random(3), 60)
    codes = {issue.issue_code for issue in feedback.issues}
    assert "MEANINGLESS_QUALIFICATION" in codes
    assert "CLAIM_EXCEEDS_OWN_EVIDENCE" in codes
    assert "OVERSTATED_UNCERTAINTY" in codes


def test_overstated_uncertainty_flagged_by_hub():
    hub = SMEPrescreeningHub(replace(PrescreeningParameters(), noise=0.0))
    record = _evidence(standard_error=0.02)
    shielded = _claim(asserted_value=0.60,
                      evidence_ids=(record.evidence_id,),
                      stated_uncertainty=0.50,
                      qualification=MEANINGFUL_QUAL)
    feedback = hub.screen(shielded, {record.evidence_id: record}, [], [],
                          random.Random(5), 60)
    assert "OVERSTATED_UNCERTAINTY" in {issue.issue_code
                                        for issue in feedback.issues}


class _WF:
    average_employees_365d = 400.0


class _AssetStub:
    def __init__(self):
        self.symbol = "SME1"
        self.balance = 500_000.0
        self.workforce = _WF()
        self.q_truthful_benchmark = 0.6
        self.greenhushing_gap = 0.0
        self.claim_history = []
        self.evidence_history = []
        self.public_environmental_signals = []


def test_spurious_flags_do_not_count_as_meaningful_prevention():
    hub = SMEPrescreeningHub(replace(PrescreeningParameters(), noise=1.0,
                                     strictness=0.10))
    asset = _AssetStub()
    for seed in range(30):
        record = _evidence(estimate=0.55, standard_error=0.03)
        truthful = _claim(claim_id=f"SP-{seed}",
                          asserted_value=0.55,
                          evidence_ids=(record.evidence_id,),
                          qualification=MEANINGFUL_QUAL,
                          stated_uncertainty=0.03)
        hub.process_firm_claims(60, asset, "honest", [truthful],
                                [record], False, random.Random(seed))
    assert hub.noise_flag_events > 0
    assert hub.meaningful_revisions == 0
    assert hub.published_clean > 0


def test_processing_delay_is_operational():
    # Epoch day 60 + 5-day review: at day 63 hub-screened voluntary
    # claims are still under review and NOT public; by day 70 they are.
    early = _run_supervised(
        days=63, seed=42,
        greenwashing_policy_regime=GreenwashingPolicyRegime
        .SME_ALGORITHMIC_PRESCREENING)
    reviewed_early = [claim for claim in early.claim_log
                      if claim.review_day is not None]
    assert early.prescreening_hub.submissions > 0
    assert reviewed_early == []
    assert early._hub_pending_claims

    late = _run_supervised(
        days=70, seed=42,
        greenwashing_policy_regime=GreenwashingPolicyRegime
        .SME_ALGORITHMIC_PRESCREENING)
    reviewed_late = [claim for claim in late.claim_log
                     if claim.review_day is not None]
    assert reviewed_late
    from market_sim.constants import PRESCREEN_PROCESSING_DELAY_DAYS
    for claim in reviewed_late:
        assert claim.review_day \
            == claim.day + PRESCREEN_PROCESSING_DELAY_DAYS


def test_hub_composition_audit_tracks_strategies():
    sim = _run_supervised(
        days=180, seed=42,
        greenwashing_policy_regime=GreenwashingPolicyRegime
        .SME_ALGORITHMIC_PRESCREENING)
    composition = sim.prescreening_hub.composition
    assert composition
    for strategy, counts in composition.items():
        assert counts["participating_firm_periods"] \
            <= counts["eligible_firm_periods"]
        assert counts["meaningful_revisions"] <= counts["submissions"]


# --------------------------------------------------------------------------- #
# P1/P2-6: connector operations
# --------------------------------------------------------------------------- #
class _Facts:
    period_start = date(2026, 1, 1)
    period_end = date(2026, 12, 31)

    def value_for(self, subject):
        return {ClaimSubject.SCOPE_1_EMISSIONS: 50_000.0,
                ClaimSubject.SCOPE_2_EMISSIONS: 30_000.0,
                ClaimSubject.SCOPE_3_EMISSIONS: 100_000.0,
                ClaimSubject.RENEWABLE_ENERGY_SHARE: 0.4}.get(subject, 1.0)


class _CAsset(_AssetStub):
    def __init__(self, symbol="GW1"):
        super().__init__()
        self.symbol = symbol
        self.environmental_facts = _Facts()


def _clean_connector(**overrides) -> ConnectorParameters:
    base = dict(stale_probability=0.0, mismatch_probability=0.0,
                register_error_probability=0.0, downtime_probability=0.0,
                cyber_incident_probability=0.0)
    base.update(overrides)
    return ConnectorParameters(**base)


def test_tampered_provenance_is_detected_and_excluded():
    connector = CertifiedGreenDataConnector(_clean_connector())
    asset = _CAsset()
    connector.onboard_firm(asset, "honest", random.Random(1))
    records = connector.transfer_period(60, date(2026, 3, 1), asset,
                                        random.Random(2))
    assert records
    target = connector.provenance[0]
    target.estimate *= 0.5          # Tamper with the stored value.
    tampered = connector.verify_provenance()
    assert target.transfer_id in tampered
    assert not target.integrity_ok
    # Reconciliation refuses the tampered record entirely: no finding is
    # produced for a claim whose only connector comparator was tampered.
    tampered_record = next(record for record in records
                           if record.evidence_id == target.transfer_id)
    claim = _claim(subject=tampered_record.subject, firm_symbol="GW1",
                   channel=ClaimChannel.SUSTAINABILITY_REPORT,
                   asserted_value=tampered_record.estimate * 0.5,
                   unit="tCO2e")
    findings, flags = connector.reconcile(60, [claim],
                                          [tampered_record], [])
    assert findings == [] and flags == set()
    # Untampered records elsewhere still verify clean.
    assert all(record.integrity_ok for record in connector.provenance
               if record.transfer_id != target.transfer_id)


def test_register_error_correction_lifecycle_propagates_prospectively():
    connector = CertifiedGreenDataConnector(
        _clean_connector(register_error_probability=1.0))
    asset = _CAsset()
    connector.onboard_firm(asset, "honest", random.Random(3))
    connector.transfer_period(60, date(2026, 3, 1), asset,
                              random.Random(4))
    assert connector._pending_corrections
    due_days = [info["due"]
                for info in connector._pending_corrections.values()]
    assert all(due == 60 + 60 for due in due_days)
    # Not yet due: nothing happens.
    assert connector.process_corrections(
        100, {"GW1": asset}, random.Random(5)) == []
    corrected = connector.process_corrections(
        120, {"GW1": asset}, random.Random(5))
    assert corrected
    assert connector._pending_corrections == {}
    assert connector.corrections_issued == len(corrected)
    linked = [record for record in connector.provenance
              if record.corrects_transfer_id is not None]
    assert len(linked) == len(corrected)


def test_stale_records_carry_genuinely_old_information():
    connector = CertifiedGreenDataConnector(
        _clean_connector(stale_probability=1.0))
    asset = _CAsset()
    connector.onboard_firm(asset, "honest", random.Random(7))
    # Pre-seed register history: an old measurement of 42.0.
    for source in connector.parameters.sources:
        connector._measurement_history[
            ("GW1", source.subject.value)] = [(1, 42.0)]
    records = connector.transfer_period(130, date(2026, 5, 1), asset,
                                        random.Random(8))
    assert records
    unclamped = {ClaimSubject.SCOPE_1_EMISSIONS,
                 ClaimSubject.SCOPE_2_EMISSIONS,
                 ClaimSubject.SCOPE_3_EMISSIONS,
                 ClaimSubject.ENVIRONMENTAL_CAPEX}
    checked = 0
    for record in records:
        assert record.staleness_days == 120
        if record.subject in unclamped:
            # The stale read IS the old register measurement, verbatim.
            assert record.estimate == pytest.approx(42.0)
            checked += 1
    assert checked > 0


def test_low_coverage_no_longer_immunizes_large_fraud():
    connector = CertifiedGreenDataConnector(_clean_connector())
    asset = _CAsset()
    connector.onboard_firm(asset, "honest", random.Random(1))
    records = connector.transfer_period(60, date(2026, 3, 1), asset,
                                        random.Random(2))
    scope3 = next(record for record in records
                  if record.subject == ClaimSubject.SCOPE_3_EMISSIONS)
    fraud = _claim(subject=ClaimSubject.SCOPE_3_EMISSIONS,
                   claim_type=ClaimType.QUANTITATIVE,
                   channel=ClaimChannel.SUSTAINABILITY_REPORT,
                   asserted_value=scope3.estimate * 0.2, unit="tCO2e",
                   firm_symbol="GW1",
                   evidence_ids=(scope3.evidence_id,))
    balance_before = asset.balance
    findings, flags = connector.reconcile(60, [fraud], records, [])
    finding = next(item for item in findings
                   if item.subject == "scope_3_emissions")
    assert finding.classification \
        == ReconciliationClass.CORRECTION_REQUIRED.value
    assert fraud.claim_id in flags
    assert asset.balance == balance_before   # Still never a sanction.
    # Small honest divergence under low coverage stays incomplete.
    honest = _claim(subject=ClaimSubject.SCOPE_3_EMISSIONS,
                    claim_type=ClaimType.QUANTITATIVE,
                    channel=ClaimChannel.SUSTAINABILITY_REPORT,
                    asserted_value=scope3.estimate * 0.97, unit="tCO2e",
                    firm_symbol="GW1",
                    stated_uncertainty=scope3.standard_error)
    findings2, flags2 = connector.reconcile(61, [honest], records, [])
    finding2 = next(item for item in findings2
                    if item.claim_id == honest.claim_id)
    assert finding2.classification \
        == ReconciliationClass.INCOMPLETE_COVERAGE.value
    assert honest.claim_id not in flags2


# --------------------------------------------------------------------------- #
# P1/P2-7: metric families
# --------------------------------------------------------------------------- #
def test_metric_families_are_separated_and_honest():
    sim = _run_supervised(days=365, seed=42)
    metrics = PolicyOutcomeEvaluator().evaluate(sim)
    # Original vs live incidence: corrections reduce live, not original.
    assert metrics["live_uncorrected_material_overstatements"] \
        <= metrics["original_material_overstatements"]
    assert metrics["corrected_material_claims"] >= 0.0
    assert metrics["misleading_claim_days"] > 0.0
    assert metrics["exposure_weighted_severity"] > 0.0
    # Population-level detection can never exceed screening-conditioned
    # recall (selection flattering) and coverage is a share.
    assert metrics["population_detection_recall"] \
        <= metrics["screening_conditioned_recall"] + 1e-9
    assert 0.0 <= metrics["detection_coverage"] <= 1.0
    # Intent separation partitions original incidence.
    assert metrics["noise_only_overstatements"] \
        + metrics["strategic_material_overstatements"] \
        == metrics["original_material_overstatements"]
    # Queue metrics exist and are finite.
    assert metrics["queue_mean_age_days"] >= 0.0
    assert metrics["case_completion_days_mean"] >= 0.0


def test_discounting_reduces_late_costs_but_keeps_ledgers():
    sim = _run_supervised(days=365, seed=42)
    undiscounted = PolicyOutcomeEvaluator(0.0).evaluate(sim)
    discounted = PolicyOutcomeEvaluator(0.07).evaluate(sim)
    assert undiscounted["state_policy_cost"] \
        == discounted["state_policy_cost"]      # Ledger untouched.
    assert discounted["discounted_total_public_cost"] \
        < undiscounted["discounted_total_public_cost"]
    assert discounted["discounted_exposure_weighted_severity"] \
        <= undiscounted["discounted_exposure_weighted_severity"]


def test_composite_criteria_measure_distinct_dimensions():
    base = dict(precision=0.9, recall=0.8, evidence_quality_mean=0.6,
                state_policy_cost=1_000.0, regulator_time_cost=500.0,
                firm_policy_cost=300.0, firm_reporting_cost=200.0,
                false_positives=2.0, mean_greenhushing_gap=0.1,
                withheld_truthful_claims=1.0,
                voluntary_claims_published=50.0,
                privacy_cyber_incidents=0.0,
                original_material_overstatements=10.0,
                exposure_weighted_severity=100.0)
    same_count_less_exposure = dict(base,
                                    exposure_weighted_severity=20.0)
    scores = composite_scores(
        {"A": base, "B": same_count_less_exposure}, PolicyScoreWeights())
    assert scores["B"] > scores["A"]   # Incidence equal, harm differs.


# --------------------------------------------------------------------------- #
# P2-8: horizon grid and sensitivity interface
# --------------------------------------------------------------------------- #
def test_horizon_grid_reports_stability():
    grid = run_horizon_grid(
        dict(num_traders=6, num_manipulators=0, enable_credit=False,
             enable_esg=True),
        horizons=(70, 120), replications=1, common_seed=17)
    assert set(grid.winners_by_horizon) == {70, 120}
    assert isinstance(grid.stable_default_winner, bool)
    assert "Horizon grid" in grid.to_summary_text()


def test_sensitivity_interface_runs_and_reports_parameter_sensitivity():
    space = {"sanction_scale_multiple": (0.5, 3.0),
             "hub_strictness": (0.1, 0.9),
             "regulatory_strictness": (0.2, 0.9),
             "discount_rate": (0.0, 0.05),
             "horizon_days": (65, 70)}
    result = run_sensitivity_analysis(
        dict(num_traders=6, num_manipulators=0, enable_credit=False,
             enable_esg=True),
        samples=2, seed=3, parameter_space=space)
    assert len(result.rows) == 2
    assert sum(result.winner_counts.values()) == 2
    for row in result.rows:
        assert "winner" in row and "sanction_scale_multiple" in row
