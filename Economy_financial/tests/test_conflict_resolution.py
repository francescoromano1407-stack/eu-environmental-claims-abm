"""Part J (Workstream C) adversarial tests: evidence-conflict resolution.

Covers: truthful firm vs erroneous public record; deceptive firm vs
accurate public record; repeated conflicts corroborating each other;
zero regulatory capacity; high backlog with and without the reserve;
source corrections arriving before and after the decision; and the
no-automatic-sanction guarantee.
"""

import random
from datetime import date

from market_sim.environmental_claims import (
    AssessmentOutcome,
    CaseState,
    ClaimAudience,
    ClaimChannel,
    ClaimSubject,
    ClaimType,
    EnvironmentalClaim,
    EvidenceRecord,
    EvidenceSource,
)
from market_sim.greenwashing_supervision import (
    GreenwashingSupervisor,
    SupervisionParameters,
)
from market_sim.models import Asset
from market_sim.regulation import LegalRegime

DATE = date(2027, 4, 5)
_SEQ = [0]


def _claim(value, firm="F", subject=ClaimSubject.GREEN_SCORE,
           channel=ClaimChannel.SUSTAINABILITY_REPORT, day=400,
           evidence_ids=()) -> EnvironmentalClaim:
    _SEQ[0] += 1
    return EnvironmentalClaim(
        claim_id=f"CF-{_SEQ[0]}", firm_symbol=firm, day=day,
        communication_date=DATE, channel=channel,
        audience=ClaimAudience.MIXED
        if channel == ClaimChannel.SUSTAINABILITY_REPORT
        else ClaimAudience.CONSUMERS,
        claim_type=ClaimType.QUANTITATIVE, subject=subject,
        asserted_value=value, unit="score_0_1",
        period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
        organizational_boundary="consolidated_group",
        operational_boundary="scope_1_2_3",
        evidence_ids=tuple(evidence_ids),
        qualification=("Estimate limited to the stated period, boundary "
                       "and methodology uncertainty."),
        stated_uncertainty=0.01)


def _internal(estimate, firm="F", se=0.02) -> EvidenceRecord:
    _SEQ[0] += 1
    return EvidenceRecord(
        evidence_id=f"INT-{_SEQ[0]}", firm_symbol=firm,
        subject=ClaimSubject.GREEN_SCORE,
        period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
        estimate=estimate, standard_error=se,
        source=EvidenceSource.COMPANY_RECORD, coverage=0.9,
        independence=0.2, verified=False, reliability_prior=0.8)


def _public(estimate, firm="F", se=0.01) -> EvidenceRecord:
    _SEQ[0] += 1
    return EvidenceRecord(
        evidence_id=f"PUB-{_SEQ[0]}", firm_symbol=firm,
        subject=ClaimSubject.GREEN_SCORE,
        period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
        estimate=estimate, standard_error=se,
        source=EvidenceSource.PUBLIC_DATA, coverage=0.95,
        independence=0.95, verified=True, reliability_prior=0.95)


def _third_party(estimate, firm="F", se=0.01) -> EvidenceRecord:
    _SEQ[0] += 1
    return EvidenceRecord(
        evidence_id=f"TP-{_SEQ[0]}", firm_symbol=firm,
        subject=ClaimSubject.GREEN_SCORE,
        period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
        estimate=estimate, standard_error=se,
        source=EvidenceSource.THIRD_PARTY, coverage=0.85,
        independence=0.90, verified=True, reliability_prior=0.90)


def _supervisor(**params) -> tuple[GreenwashingSupervisor, Asset]:
    defaults = dict(evidence_request_capacity=20,
                    investigation_capacity=5,
                    random_surveillance_share=0.0)
    defaults.update(params)
    supervisor = GreenwashingSupervisor(
        LegalRegime(), random.Random(7),
        SupervisionParameters(**defaults))
    asset = Asset("F", annual_net_turnover=500_000_000,
                  average_employees=1500)
    return supervisor, asset


def _open_conflict(supervisor, asset, *, claimed=0.52, internal_value=0.52,
                   public_value=0.20, day=400):
    internal = _internal(internal_value)
    public = _public(public_value)
    claim = _claim(claimed, day=day,
                   evidence_ids=(internal.evidence_id, public.evidence_id))
    assessments, cases = supervisor.process_period(
        day, DATE, {"F": asset}, [claim], [internal, public], set(),
        random.Random(3))
    return claim, internal, public, assessments[0], cases[0]


# --------------------------------------------------------------------------- #
# Conflict cases enter the queue, consume capacity, never sanction
# --------------------------------------------------------------------------- #
def test_conflict_enters_procedural_state_and_consumes_capacity():
    supervisor, asset = _supervisor()
    claim, _, _, assessment, case = _open_conflict(supervisor, asset)
    assert assessment.evidence_conflict
    assert assessment.outcome == AssessmentOutcome.INCONCLUSIVE
    assert case.conflict_case
    assert case.state == CaseState.CONFLICT_RESOLUTION
    # Same-period capacity was consumed by opening the investigation.
    assert case.conflict_investigation_day == 400
    assert supervisor.total_conflict_investigations == 1
    assert case.applied_penalty == 0.0
    assert case.priority >= supervisor.parameters.conflict_priority


def test_zero_capacity_conflict_stays_queued_forever():
    supervisor, asset = _supervisor(investigation_capacity=0)
    _, _, _, _, case = _open_conflict(supervisor, asset)
    assert case.conflict_investigation_day is None
    assert supervisor.total_conflict_investigations == 0
    assert supervisor.pending_queue_length >= 1
    for day in range(401, 600, 7):
        supervisor.advance_day(day, {"F": asset}, on_date=DATE)
    assert case.state == CaseState.CONFLICT_RESOLUTION
    assert case.conflict_resolved_day is None
    assert case.applied_penalty == 0.0
    assert supervisor.total_penalties == 0.0


# --------------------------------------------------------------------------- #
# Truthful firm vs erroneous public record
# --------------------------------------------------------------------------- #
def test_truthful_firm_vs_wrong_register_confirmed_no_sanction():
    supervisor, asset = _supervisor()
    requests = []
    supervisor.reverification_service = \
        lambda firm, subject, day: requests.append((firm, subject, day))
    claim, internal, public, assessment, case = _open_conflict(
        supervisor, asset, claimed=0.52, internal_value=0.52,
        public_value=0.20)
    assert requests, "re-verification must be commissioned"
    # The commissioned re-measurement agrees with the firm.
    supervisor.register_external_evidence(_third_party(0.52), 430)
    supervisor.advance_day(431, {"F": asset}, on_date=DATE)
    assert case.conflict_outcome == "external_register_corrected"
    assert case.state == CaseState.CLOSED
    assert case.applied_penalty == 0.0
    assert supervisor.total_penalties == 0.0
    # Public rehabilitation reaches consumers/investors.
    signal = asset.public_environmental_signals[-1]
    assert signal.source == "conflict_resolution_confirmation"
    assert signal.controversy_discount == 0.0
    assert not signal.confirmed_abuse
    # The truthful claim was never corrected or withdrawn.
    assert claim.corrected_day is None and not claim.withdrawn
    delays = supervisor.conflict_resolution_delays
    assert delays and delays[0] == 31


# --------------------------------------------------------------------------- #
# Deceptive firm vs accurate public record: escalation only with
# corroboration, sanction only through the ordinary path
# --------------------------------------------------------------------------- #
def test_deceptive_firm_vs_accurate_register_escalates_then_sanctions():
    supervisor, asset = _supervisor()
    claim, internal, public, assessment, case = _open_conflict(
        supervisor, asset, claimed=0.80, internal_value=0.80,
        public_value=0.30)
    assert case.applied_penalty == 0.0
    # Corroborating third-party re-measurement agrees with the register.
    supervisor.register_external_evidence(_third_party(0.31), 430)
    supervisor.advance_day(431, {"F": asset}, on_date=DATE)
    assert case.conflict_outcome == "escalated_corroborated"
    new_assessment = supervisor.assessments[case.assessment_id]
    assert new_assessment.confirmed_abuse
    # The sanction arrives ONLY through the ordinary formal path.
    supervisor.advance_day(432, {"F": asset}, on_date=DATE)
    assert case.state == CaseState.CLOSED
    assert case.applied_penalty > 0.0
    assert supervisor.total_penalties > 0.0


def test_unresolved_conflict_without_corroboration_never_escalates():
    supervisor, asset = _supervisor()
    _, _, _, _, case = _open_conflict(
        supervisor, asset, claimed=0.80, internal_value=0.80,
        public_value=0.30)
    # No re-verification ever arrives; credibility margins are decisive
    # for the register (verified, high independence), so the strongest
    # outcome is a correction demand -- never an escalation or sanction.
    timeout = 400 + supervisor.parameters \
        .conflict_reverification_timeout_days
    supervisor.advance_day(timeout + 1, {"F": asset}, on_date=DATE)
    assert case.conflict_outcome == "claim_corrected"
    assert case.state == CaseState.CORRECTION_WINDOW
    assert case.applied_penalty == 0.0
    assert supervisor.total_penalties == 0.0


def test_balanced_credibility_conflict_is_dismissed():
    supervisor, asset = _supervisor()
    internal = _internal(0.60, se=0.01)
    # An unverified, less independent external record of similar quality:
    # inside the credibility margin -> dismissal.
    _SEQ[0] += 1
    outside = EvidenceRecord(
        evidence_id=f"PUB-{_SEQ[0]}", firm_symbol="F",
        subject=ClaimSubject.GREEN_SCORE,
        period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
        estimate=0.30, standard_error=0.01,
        source=EvidenceSource.PUBLIC_DATA, coverage=0.9,
        independence=0.65, verified=False, reliability_prior=0.8)
    claim = _claim(0.60, evidence_ids=(internal.evidence_id,
                                       outside.evidence_id))
    _, cases = supervisor.process_period(
        400, DATE, {"F": asset}, [claim], [internal, outside], set(),
        random.Random(3))
    case = cases[0]
    assert case.conflict_case
    timeout = 400 + supervisor.parameters \
        .conflict_reverification_timeout_days
    supervisor.advance_day(timeout + 1, {"F": asset}, on_date=DATE)
    assert case.conflict_outcome == "dismissed_unresolved"
    assert case.state == CaseState.CLOSED
    assert case.applied_penalty == 0.0


# --------------------------------------------------------------------------- #
# Repeated conflicts corroborate each other across periods
# --------------------------------------------------------------------------- #
def test_repeated_conflicts_provide_corroboration():
    supervisor, asset = _supervisor()
    _, _, public_one, _, case_one = _open_conflict(
        supervisor, asset, claimed=0.80, internal_value=0.80,
        public_value=0.30, day=400)
    # Second reporting period: the firm repeats the pattern; a NEW
    # independent register reading again contradicts it.
    _, _, public_two, _, case_two = _open_conflict(
        supervisor, asset, claimed=0.80, internal_value=0.80,
        public_value=0.31, day=460)
    assert supervisor._conflict_history[("F", "green_score")] == 2
    # Case one's resolution now sees period two's independent record as
    # fresh corroboration of its own register record.
    supervisor.advance_day(461, {"F": asset}, on_date=DATE)
    assert case_one.conflict_outcome == "escalated_corroborated"


# --------------------------------------------------------------------------- #
# High backlog: the reserve keeps disputes moving; without it they starve
# --------------------------------------------------------------------------- #
def _backlog_setup(**params):
    """One conflict case (firm F) competing with a whistleblower case on
    a SEPARATE firm G, so only F carries the cross-source conflict."""
    supervisor, asset = _supervisor(**params)
    other = Asset("G", annual_net_turnover=500_000_000,
                  average_employees=1500)
    internal = _internal(0.52)
    public = _public(0.20)
    conflict_claim = _claim(0.52, evidence_ids=(internal.evidence_id,
                                                public.evidence_id))
    whistle_internal = _internal(0.40, firm="G")
    whistle_claim = _claim(0.90, firm="G", channel=ClaimChannel.MARKETING,
                           evidence_ids=(whistle_internal.evidence_id,))
    supervisor.process_period(
        400, DATE, {"F": asset, "G": other},
        [conflict_claim, whistle_claim],
        [internal, public, whistle_internal], set(), random.Random(3),
        whistleblower_claims=[whistle_claim.claim_id])
    conflict_case = next(case for case in supervisor.cases
                         if case.conflict_case)
    whistle_case = next(case for case in supervisor.cases
                        if case.trigger == "whistleblower")
    assert not whistle_case.conflict_case
    return supervisor, conflict_case, whistle_case


def test_reserve_shields_conflicts_from_high_priority_backlog():
    supervisor, conflict_case, whistle_case = _backlog_setup(
        investigation_capacity=1, conflict_capacity_share=1.0)
    # The single slot went to the conflict; the whistleblower case keeps
    # its queue position for the next period.
    assert conflict_case.conflict_investigation_day == 400
    assert whistle_case.state == CaseState.UNDER_ASSESSMENT
    assert supervisor.pending_queue_length >= 1


def test_without_reserve_conflicts_wait_behind_higher_priority():
    supervisor, conflict_case, whistle_case = _backlog_setup(
        investigation_capacity=1, conflict_capacity_share=0.0)
    # Whistleblower priority (1.0) outranks the conflict (0.85): the
    # conflict is starved when no capacity is reserved.
    assert conflict_case.conflict_investigation_day is None
    assert supervisor.total_conflict_investigations == 0
    assert whistle_case.state == CaseState.CLOSED


# --------------------------------------------------------------------------- #
# Source correction arriving before vs after the decision
# --------------------------------------------------------------------------- #
def test_correction_before_decision_resolves_conflict():
    supervisor, asset = _supervisor()
    _, _, _, _, case = _open_conflict(supervisor, asset, claimed=0.52,
                                      internal_value=0.52,
                                      public_value=0.20)
    # The register's superseding correction arrives BEFORE resolution.
    supervisor.register_external_evidence(_third_party(0.52), 410)
    supervisor.advance_day(
        case.conflict_resolution_due_day, {"F": asset}, on_date=DATE)
    assert case.conflict_outcome == "external_register_corrected"
    assert case.applied_penalty == 0.0


def test_correction_after_decision_never_rewrites_the_case():
    supervisor, asset = _supervisor()
    internal = _internal(0.60, se=0.01)
    _SEQ[0] += 1
    outside = EvidenceRecord(
        evidence_id=f"PUB-{_SEQ[0]}", firm_symbol="F",
        subject=ClaimSubject.GREEN_SCORE,
        period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
        estimate=0.30, standard_error=0.01,
        source=EvidenceSource.PUBLIC_DATA, coverage=0.9,
        independence=0.65, verified=False, reliability_prior=0.8)
    claim = _claim(0.60, evidence_ids=(internal.evidence_id,
                                       outside.evidence_id))
    _, cases = supervisor.process_period(
        400, DATE, {"F": asset}, [claim], [internal, outside], set(),
        random.Random(3))
    case = cases[0]
    timeout = 400 + supervisor.parameters \
        .conflict_reverification_timeout_days
    supervisor.advance_day(timeout + 1, {"F": asset}, on_date=DATE)
    assert case.conflict_outcome == "dismissed_unresolved"
    closed_day = case.closed_day
    # A late correction arrives AFTER the dismissal: prospective only.
    supervisor.register_external_evidence(_third_party(0.60), timeout + 20)
    supervisor.advance_day(timeout + 21, {"F": asset}, on_date=DATE)
    assert case.conflict_outcome == "dismissed_unresolved"
    assert case.closed_day == closed_day
    assert case.state == CaseState.CLOSED


# --------------------------------------------------------------------------- #
# Connector-integrated end-to-end conflict flow
# --------------------------------------------------------------------------- #
def test_connector_regime_resolves_conflicts_in_full_simulation():
    from market_sim.simulation import Simulation
    from market_sim.policy_regimes import GreenwashingPolicyRegime
    random.seed(42)
    sim = Simulation(
        days=365, num_traders=8, num_manipulators=0, enable_credit=False,
        enable_esg=True, enable_greenwashing_supervision=True,
        greenwashing_policy_regime=GreenwashingPolicyRegime
        .CERTIFIED_GREEN_DATA_CONNECTOR)
    sim.run()
    supervisor = sim.greenwashing_supervisor
    assert supervisor.total_conflict_investigations > 0
    assert supervisor.conflict_outcomes
    # No sanction is ever booked while a case sits in conflict state.
    for case in supervisor.cases:
        if case.conflict_case and case.conflict_outcome in {
                "", "dismissed_unresolved", "confirmed_firm_claim",
                "external_register_corrected"}:
            assert case.applied_penalty == 0.0
