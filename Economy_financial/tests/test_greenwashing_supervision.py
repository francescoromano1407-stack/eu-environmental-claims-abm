from datetime import date
import random

from market_sim.environmental_claims import (
    AssessmentOutcome,
    ClaimAssessment,
    ClaimAudience,
    ClaimChannel,
    ClaimSubject,
    ClaimType,
    EnvironmentalClaim,
    EvidenceRecord,
    EvidenceSource,
    LegalTrack,
    OmissionGround,
    ReportingOmission,
    RuleAuthority,
)
from market_sim.greenwashing_supervision import (
    EnvironmentalClaimRuleEngine,
    GreenwashingSupervisor,
    LimitedAssuranceService,
    PenaltyPolicy,
    SupervisionParameters,
)
from market_sim.models import Asset
from market_sim.regulation import LegalRegime


def _claim(identifier="C1", value=0.5, channel=ClaimChannel.MARKETING,
           claim_type=ClaimType.QUANTITATIVE,
           subject=ClaimSubject.GREEN_SCORE, qualification="scope stated"):
    return EnvironmentalClaim(
        claim_id=identifier, firm_symbol="F", day=1,
        communication_date=date(2027, 1, 1), channel=channel,
        audience=ClaimAudience.CONSUMERS
            if channel != ClaimChannel.SUSTAINABILITY_REPORT
            else ClaimAudience.MIXED,
        claim_type=claim_type, subject=subject,
        asserted_value=value, unit="score_0_1",
        period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
        organizational_boundary="group", operational_boundary="scope_1_2_3",
        evidence_ids=(f"E-{identifier}",), qualification=qualification,
        stated_uncertainty=0.01,
    )


def _evidence(claim, estimate=0.5, standard_error=0.02, verified=False):
    return EvidenceRecord(
        evidence_id=claim.evidence_ids[0], firm_symbol="F",
        subject=claim.subject, period_start=claim.period_start,
        period_end=claim.period_end, estimate=estimate,
        standard_error=standard_error, source=EvidenceSource.COMPANY_RECORD,
        coverage=1.0, independence=0.3, verified=verified)


def test_divergence_bands_separate_noise_inconclusive_and_overstatement():
    engine = EnvironmentalClaimRuleEngine(LegalRegime())
    noisy = _claim("N", 0.51)
    inconclusive = _claim("I", 0.58)
    abuse = _claim("A", 0.80)
    assert engine.assess(noisy, [_evidence(noisy, 0.50, 0.05)], 1,
                         date(2027, 1, 1)).outcome \
        == AssessmentOutcome.NOISE
    assert engine.assess(inconclusive, [_evidence(inconclusive, 0.50, 0.05)],
                         1, date(2027, 1, 1)).outcome \
        == AssessmentOutcome.INCONCLUSIVE
    result = engine.assess(abuse, [_evidence(abuse, 0.50, 0.02)], 1,
                           date(2027, 1, 1))
    assert result.outcome == AssessmentOutcome.OVERSTATEMENT
    assert result.standardized_divergence > 2.5


def test_lower_emissions_claim_uses_opposite_greener_direction():
    engine = EnvironmentalClaimRuleEngine(LegalRegime())
    claim = _claim("CO2", 60.0, subject=ClaimSubject.SCOPE_1_EMISSIONS)
    claim.unit = "tCO2e"
    result = engine.assess(claim, [_evidence(claim, 100.0, 5.0)], 1,
                           date(2027, 1, 1))
    assert result.divergence == 40.0
    assert result.outcome == AssessmentOutcome.OVERSTATEMENT


def test_offset_and_unverified_label_rules_start_on_application_date():
    engine = EnvironmentalClaimRuleEngine(LegalRegime())
    offset = _claim("OFF", 0.0, claim_type=ClaimType.OFFSET_BASED,
                    subject=ClaimSubject.NET_ZERO, qualification="")
    offset.relies_on_offsets = True
    offset.offset_disclosed_separately = False
    before = engine.assess(offset, [_evidence(offset, 0.0, 0.01)], 1,
                           date(2026, 9, 26))
    after = engine.assess(offset, [_evidence(offset, 0.0, 0.01)], 1,
                          date(2026, 9, 27))
    assert before.outcome != AssessmentOutcome.PROHIBITED_PRACTICE
    assert after.outcome == AssessmentOutcome.PROHIBITED_PRACTICE


def test_limited_assurance_covers_every_mandatory_report_claim():
    claims = [_claim(f"R{i}", 0.5,
                     channel=ClaimChannel.SUSTAINABILITY_REPORT)
              for i in range(8)]
    evidence = [_evidence(claim) for claim in claims]
    assured = LimitedAssuranceService().assure(
        claims, evidence, {"F"}, random.Random(1))
    assert len(assured) == len(claims)
    assert all(record.verified
               and record.source == EvidenceSource.LIMITED_ASSURANCE
               for record in assured)


def test_supervisor_screens_all_but_respects_evidence_and_case_capacity():
    parameters = SupervisionParameters(
        evidence_request_capacity=3, investigation_capacity=1,
        random_surveillance_share=0.10)
    supervisor = GreenwashingSupervisor(
        LegalRegime(), random.Random(2), parameters)
    claims = [_claim(f"C{i}", 0.90,
                     channel=ClaimChannel.SUSTAINABILITY_REPORT)
              for i in range(10)]
    evidence = [_evidence(claim, 0.40, 0.01) for claim in claims]
    asset = Asset("F", annual_net_turnover=500_000_000,
                  average_employees=1500)
    assessments, cases = supervisor.process_period(
        400, date(2027, 4, 5), {"F": asset}, claims, evidence, {"F"},
        random.Random(3))
    assert supervisor.total_screened == 10
    assert supervisor.total_assured_claims == 10
    assert supervisor.total_evidence_requests == 3
    assert len(assessments) == len(cases) == 3
    assert supervisor.total_investigations == 1
    assert supervisor.pending_queue_length == 2


def test_penalty_caps_do_not_reuse_csddd_three_percent_for_greenwashing():
    params = SupervisionParameters()
    policy = PenaltyPolicy(params)
    consumer = ClaimAssessment(
        "A", "C", "F", 1, AssessmentOutcome.SYSTEMIC_ABUSE,
        LegalTrack.CONSUMER, RuleAuthority.UCPD_BASE,
        0.3, 0.5, 0.01, 50.0, 0.5, 1.0)
    _, ordinary_cap, ordinary = policy.calculate(
        consumer, 100_000_000, 10_000_000, 50_000_000)
    _, cross_cap, cross = policy.calculate(
        consumer, 100_000_000, 10_000_000, 50_000_000,
        cross_border_consumer_case=True)
    due_diligence = ClaimAssessment(
        "D", "C", "F", 1, AssessmentOutcome.SYSTEMIC_ABUSE,
        LegalTrack.DUE_DILIGENCE, RuleAuthority.CSDDD,
        0.3, 0.5, 0.01, 50.0, 0.5, 1.0)
    _, csddd_cap, csddd = policy.calculate(
        due_diligence, 100_000_000, 10_000_000, 50_000_000)
    assert ordinary_cap == ordinary == 1_000_000
    assert cross_cap == cross == 4_000_000
    assert csddd_cap == csddd == 3_000_000


def test_supported_claim_and_conflicting_stale_evidence_confidence():
    engine = EnvironmentalClaimRuleEngine(LegalRegime())
    claim = _claim("SUPPORTED", 0.45)
    fresh = _evidence(claim, 0.50, 0.02, verified=True)
    stale = EvidenceRecord(
        **{**fresh.__dict__, "evidence_id": "STALE",
           "staleness_days": 730, "conflict": True})
    result = engine.assess(claim, [fresh], 1, date(2027, 1, 1))
    assert result.outcome in {
        AssessmentOutcome.SUPPORTED,
        AssessmentOutcome.SUPPORTED_WITH_QUALIFICATION}
    assert fresh.confidence > stale.confidence
    assert result.rule_ids


def test_valid_report_omission_never_legalizes_marketing_claim():
    engine = EnvironmentalClaimRuleEngine(LegalRegime())
    omission = ReportingOmission(
        "O1", "F", ClaimSubject.SCOPE_3_EMISSIONS,
        OmissionGround.SERIOUS_COMMERCIAL_PREJUDICE,
        date(2026, 12, 31), True, date(2027, 12, 31), True,
        exceptional_serious_prejudice=True, conditions_documented=True)
    report = _claim("REPORT", 100.0,
                    channel=ClaimChannel.SUSTAINABILITY_REPORT,
                    subject=ClaimSubject.SCOPE_3_EMISSIONS)
    marketing = _claim("MARKETING", 100.0,
                       channel=ClaimChannel.MARKETING,
                       subject=ClaimSubject.SCOPE_3_EMISSIONS)
    assert engine.omission_is_valid(omission, report, date(2027, 1, 1))
    assert not engine.omission_is_valid(
        omission, marketing, date(2027, 1, 1))
