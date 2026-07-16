"""Assurance, surveillance and enforcement for environmental claims.

The module models four legally distinct tracks: consumer protection,
sustainability reporting, financial-market communications and due diligence.
The last track is not treated as a greenwashing penalty shortcut.  In
particular, the CSDDD 3% ceiling can only be selected for a due-diligence
case; it is never the cap for an ordinary environmental claim.

Capacity, prioritisation, z-score bands and ordinary penalty formulae are
``EXPERIMENT`` settings.  Dates, scope tests and legal labels come from
``LegalRegime``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import date
from decimal import Decimal
import heapq
import random
from typing import Any, Iterable, Mapping, Optional

from market_sim.constants import (
    CONFLICT_CAPACITY_SHARE,
    CONFLICT_CREDIBILITY_MARGIN,
    CONFLICT_PRIORITY,
    CONFLICT_RESOLUTION_DAYS,
    CONFLICT_REVERIFICATION_TIMEOUT_DAYS,
    CORPORATE_BALANCE_FLOOR,
    EVIDENCE_CONFLICT_Z,
    PENALTY_REPEAT_ESCALATION_CAP,
    PENALTY_REPEAT_ESCALATION_RATE,
    REPEAT_PATTERN_MIN_COUNT,
    REPEAT_PATTERN_MIN_MEAN_Z,
    REPEAT_PATTERN_WINDOW_DAYS,
    SIM_TURNOVER_BALANCE_MULTIPLE,
    UNCERTAINTY_PLAUSIBILITY_MULTIPLE,
)
from market_sim.environmental_claims import (
    AssessmentOutcome,
    CaseState,
    ClaimAssessment,
    ClaimAudience,
    ClaimChannel,
    ClaimSubject,
    ClaimType,
    EnvironmentalClaim,
    EvidenceRecord,
    EvidenceSource,
    LegalTrack,
    PublicEnvironmentalSignal,
    RuleAuthority,
    ReportingOmission,
    best_evidence,
    meaningful_qualification,
)
from market_sim.regulation import LegalRegime


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return min(upper, max(lower, float(value)))


LOWER_IS_GREENER = {
    ClaimSubject.SCOPE_1_EMISSIONS,
    ClaimSubject.SCOPE_2_EMISSIONS,
    ClaimSubject.SCOPE_3_EMISSIONS,
    ClaimSubject.WATER_INTENSITY,
    ClaimSubject.POLLUTION_INTENSITY,
    ClaimSubject.BIODIVERSITY_PRESSURE,
    ClaimSubject.NET_ZERO,
}


@dataclass(frozen=True)
class SupervisionParameters:
    evidence_request_capacity: int = 20       # EXPERIMENT / period
    investigation_capacity: int = 5           # EXPERIMENT / period
    random_surveillance_share: float = 0.10    # EXPERIMENT
    correction_window_days: int = 30           # EXPERIMENT
    ordinary_penalty_cap_rate: float = 0.01    # EXPERIMENT
    consumer_cross_border_cap_rate: float = 0.04
    csddd_cap_rate: float = 0.03
    benefit_multiplier: float = 1.5             # EXPERIMENT
    affected_revenue_rate: float = 0.02         # EXPERIMENT
    guidance_support_intensity: float = 0.35    # EXPERIMENT
    small_firm_evidence_support: float = 0.25   # EXPERIMENT
    qualified_claim_safe_harbor_enabled: bool = False  # EXPERIMENT
    # Part I.1 -- sanction-scale bridge (STYLIZATION, see constants.py):
    # monetary sanction bases use sim_turnover = multiple * balance; the
    # statutory `annual_net_turnover` stays confined to legal SCOPE tests.
    sim_turnover_balance_multiple: float = SIM_TURNOVER_BALANCE_MULTIPLE
    # Part I.1 -- repeat-offender escalation (EXPERIMENT): scales the
    # experimental amount, never pierces the track's legal ceiling.
    repeat_escalation_rate: float = PENALTY_REPEAT_ESCALATION_RATE
    repeat_escalation_cap: float = PENALTY_REPEAT_ESCALATION_CAP
    # Part J (Workstream C) -- evidence-conflict resolution (EXPERIMENT).
    # A conflict case consumes ONE slot of `investigation_capacity` when
    # opened, so data disputes and enforcement compete for the same finite
    # regulator resource.
    conflict_priority: float = CONFLICT_PRIORITY
    conflict_resolution_days: int = CONFLICT_RESOLUTION_DAYS
    conflict_reverification_timeout_days: int = \
        CONFLICT_REVERIFICATION_TIMEOUT_DAYS
    conflict_credibility_margin: float = CONFLICT_CREDIBILITY_MARGIN
    conflict_capacity_share: float = CONFLICT_CAPACITY_SHARE


@dataclass(frozen=True)
class ClaimCorrectionEvent:
    """Part I.3 -- one immutable row of the correction/withdrawal ledger."""

    day: int
    claim_id: str
    firm_symbol: str
    event: str                    # "correction" | "withdrawal"
    original_value: float
    corrected_value: Optional[float]
    exposure_days: int            # Public exposure of the original value.
    legal_track: str
    case_id: str
    basis: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RegulatoryCase:
    case_id: str
    firm_symbol: str
    claim_id: str
    opened_day: int
    legal_track: LegalTrack
    authority: RuleAuthority
    state: CaseState = CaseState.SCREENED
    priority: float = 0.0
    trigger: str = "risk_screening"
    assessment_id: Optional[str] = None
    correction_due_day: Optional[int] = None
    scheduled_compliance_day: Optional[int] = None
    decision_day: Optional[int] = None
    publication_day: Optional[int] = None
    closed_day: Optional[int] = None
    remedy: str = "none"
    calculated_penalty: float = 0.0
    applicable_cap: float = 0.0
    applied_penalty: float = 0.0
    redress: float = 0.0
    cross_border_consumer_case: bool = False
    state_history: list[tuple[int, str]] = field(default_factory=list)
    # Part J (Workstream C) -- conflict-resolution procedural record.
    conflict_case: bool = False
    conflict_investigation_day: Optional[int] = None
    conflict_resolution_due_day: Optional[int] = None
    conflict_resolved_day: Optional[int] = None
    conflict_outcome: str = ""    # confirmed_firm_claim |
    #                               external_register_corrected |
    #                               claim_corrected | dismissed_unresolved |
    #                               escalated_corroborated

    def transition(self, day: int, state: CaseState) -> None:
        self.state = state
        self.state_history.append((day, state.value))

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["legal_track"] = self.legal_track.value
        result["authority"] = self.authority.value
        result["state"] = self.state.value
        return result


class LimitedAssuranceService:
    """Limited assurance for every claim in each mandatory CSRD report."""

    def assure(self, claims: Iterable[EnvironmentalClaim],
               evidence: Iterable[EvidenceRecord],
               mandatory_firms: set[str], rng: random.Random) \
            -> list[EvidenceRecord]:
        evidence_by_id = {item.evidence_id: item for item in evidence}
        assured: list[EvidenceRecord] = []
        sequence = 0
        for claim in claims:
            if claim.firm_symbol not in mandatory_firms \
                    or claim.channel != ClaimChannel.SUSTAINABILITY_REPORT:
                continue
            underlying = next((evidence_by_id[eid]
                               for eid in claim.evidence_ids
                               if eid in evidence_by_id), None)
            if underlying is None:
                continue
            sequence += 1
            # Procedure-level re-performance: no latent fact is supplied.
            se = max(1e-9, underlying.standard_error * 0.75)
            estimate = underlying.estimate + rng.gauss(0.0, se * 0.25)
            if claim.subject not in LOWER_IS_GREENER \
                    and claim.unit == "share_0_1":
                estimate = _clamp(estimate)
            elif claim.subject in {ClaimSubject.GREEN_SCORE,
                                   ClaimSubject.TAXONOMY_ELIGIBILITY,
                                   ClaimSubject.TAXONOMY_ALIGNMENT,
                                   ClaimSubject.RENEWABLE_ENERGY_SHARE}:
                estimate = _clamp(estimate)
            else:
                estimate = max(0.0, estimate)
            assured.append(EvidenceRecord(
                evidence_id=f"LA-{claim.firm_symbol}-{claim.day}-{sequence}",
                firm_symbol=claim.firm_symbol,
                subject=claim.subject,
                period_start=claim.period_start,
                period_end=claim.period_end,
                estimate=estimate,
                standard_error=se,
                source=EvidenceSource.LIMITED_ASSURANCE,
                coverage=max(underlying.coverage, 0.80),
                independence=0.85,
                verified=True,
                notes=("Limited assurance over disclosed evidence and "
                       "reporting procedures; not reasonable assurance."),
                reliability_prior=0.90,
                observation_method="sampled_reperformance",
                accessible_to_investors=True,
            ))
        return assured


class EnvironmentalClaimRuleEngine:
    """Classify divergence, uncertainty, materiality and per-se rules.

    Part I.2 hardening (all thresholds EXPERIMENT, see constants.py):
      * self-declared uncertainty is credible only up to a plausibility
        multiple of the evidence standard error (anti-gaming, 4.1);
      * a restricted operational boundary can never reduce suspicion and
        escalates when undisclosed (4.2);
      * repeated one-sided sub-threshold findings escalate through a
        rolling-window pattern memory (4.3);
      * material cross-source evidence conflicts route to INCONCLUSIVE
        with an explanation, never to an automatic sanction (4.4);
      * feasible cross-period and baseline plausibility checks flag
        cherry-picked periods and unverifiable baselines (4.5).
    Residual blind spots (documented, NOT claimed as detectable):
    production-driven absolute reductions, intensity-vs-absolute framing
    without production evidence, coordinated multi-firm narratives, and
    audience-perception effects of technically true claims.
    """

    def __init__(self, legal_regime: LegalRegime):
        self.legal_regime = legal_regime
        self._firm_severe_findings: dict[str, int] = {}
        # Part I.2 (4.3): rolling memory of one-sided low-severity
        # findings per firm -- (day, standardized divergence) pairs.
        self._firm_low_findings: dict[str, list] = {}
        self._assessment_sequence = 0

    def legal_basis(self, claim: EnvironmentalClaim,
                    on_date: date) -> tuple[LegalTrack, RuleAuthority]:
        if claim.channel in {ClaimChannel.MARKETING,
                             ClaimChannel.PRODUCT_LABEL} \
                or claim.audience in {ClaimAudience.CONSUMERS,
                                      ClaimAudience.GENERAL_PUBLIC}:
            authority = RuleAuthority.EMPOWERING_CONSUMERS_2024_825 \
                if self.legal_regime.empowering_consumers_active(on_date) \
                else RuleAuthority.UCPD_BASE
            return LegalTrack.CONSUMER, authority
        if claim.channel == ClaimChannel.SUSTAINABILITY_REPORT:
            return LegalTrack.SUSTAINABILITY_REPORTING, RuleAuthority.CSRD
        return LegalTrack.FINANCIAL_MARKETS, RuleAuthority.MARKET_DISCLOSURE

    def assess(self, claim: EnvironmentalClaim,
               evidence_records: Iterable[EvidenceRecord], day: int,
               on_date: date,
               related_claims: Iterable[EnvironmentalClaim] = ()) \
            -> ClaimAssessment:
        track, authority = self.legal_basis(claim, on_date)
        firm_records = [record for record in evidence_records
                        if record.firm_symbol == claim.firm_symbol]
        record = best_evidence(firm_records, claim.subject,
                               claim.period_start, claim.period_end)
        reasons = self._prohibited_reasons(claim, related_claims, on_date,
                                           record)
        # Per-se prohibition is decided ONLY on the reasons produced by
        # the per-se rule set above; hardening notes appended later must
        # never masquerade as a prohibited practice.
        per_se_prohibited = bool(reasons)
        estimated = record.estimate if record is not None else None
        divergence = None
        z_score = None
        standard_error = record.standard_error if record is not None else None
        materiality = 0.0
        confidence = record.confidence if record is not None else 0.0
        has_meaningful_qualification = meaningful_qualification(
            claim.qualification)
        implausible_uncertainty = False
        # Part I.2 (4.2): a restricted boundary is legitimate ONLY when a
        # meaningful qualification discloses the restriction; it never
        # reduces suspicion (the old +0.30 comparability term, which made
        # z SMALLER for boundary mismatches, is removed).
        restricted_boundary = claim.operational_boundary not in {
            "scope_1_2_3", "consolidated_group"}
        boundary_mismatch = restricted_boundary \
            and not has_meaningful_qualification

        # Part I.2 (4.4): unresolved cross-source conflict detection. If
        # an independent record and the firm's own record disagree by more
        # than EVIDENCE_CONFLICT_Z combined standard errors, the file
        # cannot support a sanction: the case routes to INCONCLUSIVE with
        # an audit trail, and (for connector sources) the register-error
        # correction lifecycle is expected to resolve it prospectively.
        evidence_conflict = False
        conflict_note = ""
        conflict_independent_id: Optional[str] = None
        conflict_internal_id: Optional[str] = None
        if record is not None:
            independent = best_evidence(
                (item for item in firm_records if item.independence >= 0.6),
                claim.subject, claim.period_start, claim.period_end)
            internal = best_evidence(
                (item for item in firm_records if item.independence < 0.6),
                claim.subject, claim.period_start, claim.period_end)
            if independent is not None and internal is not None \
                    and independent.evidence_id != internal.evidence_id:
                gap = abs(independent.estimate - internal.estimate)
                conflict_sigma = max(1e-9, (independent.standard_error ** 2
                                            + internal.standard_error ** 2)
                                     ** 0.5)
                if gap > EVIDENCE_CONFLICT_Z * conflict_sigma:
                    evidence_conflict = True
                    conflict_independent_id = independent.evidence_id
                    conflict_internal_id = internal.evidence_id
                    conflict_note = (
                        f"Independent source {independent.evidence_id} "
                        f"({independent.source.value}, se="
                        f"{independent.standard_error:.3g}) and firm "
                        f"record {internal.evidence_id} disagree by "
                        f"{gap:.3g} (> {EVIDENCE_CONFLICT_Z:.1f} combined "
                        "sigma); conflict must be investigated before any "
                        "adverse finding.")

        if record is not None:
            raw = claim.asserted_value - record.estimate
            divergence = -raw if claim.subject in LOWER_IS_GREENER else raw
            comparability_multiplier = (
                1.0 + min(2.0, max(0, record.staleness_days) / 365.0)
                + (0.75 if record.conflict else 0.0))
            effective_evidence_error = max(
                1e-9, record.standard_error * comparability_multiplier)
            # Part I.2 (4.1): plausibility cap on self-declared
            # uncertainty (EXPERIMENT). Uncapped, a firm could hide any
            # overstatement by declaring an enormous sigma.
            credible_uncertainty = max(0.0, claim.stated_uncertainty)
            uncertainty_cap = UNCERTAINTY_PLAUSIBILITY_MULTIPLE \
                * effective_evidence_error
            if credible_uncertainty > uncertainty_cap:
                implausible_uncertainty = True
                reasons.append(
                    "Self-declared uncertainty "
                    f"({claim.stated_uncertainty:.3g}) exceeds "
                    f"{UNCERTAINTY_PLAUSIBILITY_MULTIPLE:.1f}x the "
                    "evidence-derived standard error; the excess is "
                    "disregarded (EXPERIMENT plausibility cap).")
                credible_uncertainty = uncertainty_cap
            combined_error = max(
                1e-9, (effective_evidence_error ** 2
                       + credible_uncertainty ** 2) ** 0.5)
            z_score = max(0.0, divergence) / combined_error
            standard_error = effective_evidence_error
            scale = 1.0 if claim.unit in {"share_0_1", "score_0_1",
                                          "net_emissions_ratio"} \
                else max(abs(record.estimate), 1.0)
            materiality = max(0.0, divergence) / scale

        # Part I.2 (4.5): feasible cross-period and baseline checks.
        period_flag, baseline_flag = self._cross_period_checks(
            claim, firm_records, has_meaningful_qualification, reasons)

        if per_se_prohibited:
            outcome = AssessmentOutcome.PROHIBITED_PRACTICE
        elif evidence_conflict:
            outcome = AssessmentOutcome.INCONCLUSIVE
            reasons.append(conflict_note)
            reasons.append(
                "Unresolved cross-source evidence conflict: no sanction "
                "may rest on a single conflicting record; requesting "
                "clarification / register correction.")
        elif record is None:
            outcome = AssessmentOutcome.INCONCLUSIVE
            reasons.append("No period-and-subject-matched evidence available.")
        elif divergence is not None and divergence <= 0.0:
            outcome = AssessmentOutcome.SUPPORTED_WITH_QUALIFICATION \
                if has_meaningful_qualification \
                else AssessmentOutcome.SUPPORTED
            reasons.append("Claim is not greener than the evidence estimate.")
        elif z_score is not None and z_score < 1.0:
            outcome = AssessmentOutcome.NOISE
            reasons.append("Divergence is within one combined standard error.")
        elif z_score is not None and z_score < 2.5:
            outcome = AssessmentOutcome.INCONCLUSIVE
            reasons.append("Evidence cannot separate overstatement from noise.")
        elif materiality < 0.02:
            outcome = AssessmentOutcome.CORRECTABLE_ERROR
            reasons.append("Statistically visible but low-materiality error.")
        elif z_score is not None and z_score < 4.0 \
                and has_meaningful_qualification:
            outcome = AssessmentOutcome.NEGLIGENCE
            reasons.append("Material divergence despite a qualified claim.")
        else:
            prior = self._firm_severe_findings.get(claim.firm_symbol, 0)
            outcome = AssessmentOutcome.SYSTEMIC_ABUSE if prior >= 2 \
                else AssessmentOutcome.OVERSTATEMENT
            reasons.append("Material greener-than-evidence representation.")

        # Part I.2 (4.2): an undisclosed restricted boundary can only
        # escalate, never soften. Clean statistical outcomes become a
        # correction demand (qualify the boundary), not a sanction.
        if boundary_mismatch and not evidence_conflict:
            reasons.append(
                "Operational boundary is narrower than the presentation "
                "implies and is not disclosed by a meaningful "
                "qualification.")
            if outcome in {AssessmentOutcome.SUPPORTED,
                           AssessmentOutcome.SUPPORTED_WITH_QUALIFICATION,
                           AssessmentOutcome.NOISE}:
                outcome = AssessmentOutcome.CORRECTABLE_ERROR

        # Part I.2 (4.5): cherry-picked period / implausible baseline
        # escalation floor (correction demand, never a direct sanction).
        if (period_flag or baseline_flag) and not evidence_conflict \
                and outcome in {AssessmentOutcome.SUPPORTED,
                                AssessmentOutcome.SUPPORTED_WITH_QUALIFICATION,
                                AssessmentOutcome.NOISE}:
            outcome = AssessmentOutcome.CORRECTABLE_ERROR

        # Part I.2 (4.5): future targets without plan data are never
        # "supported" on any track (the consumer track already treats
        # them as per-se prohibited after Directive (EU) 2024/825).
        if not per_se_prohibited and not evidence_conflict \
                and claim.claim_type == ClaimType.FUTURE_TARGET \
                and (claim.target_date is None
                     or claim.baseline_value is None
                     or not claim.evidence_ids) \
                and outcome in {AssessmentOutcome.SUPPORTED,
                                AssessmentOutcome.SUPPORTED_WITH_QUALIFICATION,
                                AssessmentOutcome.NOISE}:
            outcome = AssessmentOutcome.INCONCLUSIVE
            reasons.append(
                "Future target lacks a date, baseline or plan evidence; "
                "cannot be treated as supported on any track.")

        # Part I.2 (4.3): rolling-window escalation of repeated one-sided
        # sub-threshold findings (EXPERIMENT thresholds). Isolated noise
        # never escalates; a persistent positively-signed pattern does.
        pattern_escalated = False
        if not evidence_conflict and z_score is not None \
                and divergence is not None and divergence > 0.0 \
                and outcome in {AssessmentOutcome.NOISE,
                                AssessmentOutcome.INCONCLUSIVE,
                                AssessmentOutcome.CORRECTABLE_ERROR}:
            history = self._firm_low_findings.setdefault(
                claim.firm_symbol, [])
            history.append((day, z_score))
            cutoff = day - REPEAT_PATTERN_WINDOW_DAYS
            history[:] = [item for item in history if item[0] >= cutoff]
            if len(history) >= REPEAT_PATTERN_MIN_COUNT:
                mean_z = sum(z for _, z in history) / len(history)
                if mean_z >= REPEAT_PATTERN_MIN_MEAN_Z:
                    pattern_escalated = True
                    outcome = AssessmentOutcome.NEGLIGENCE
                    reasons.append(
                        f"Persistent one-sided sub-threshold divergence "
                        f"pattern: {len(history)} findings in "
                        f"{REPEAT_PATTERN_WINDOW_DAYS} days with mean "
                        f"z={mean_z:.2f} (EXPERIMENT escalation; isolated "
                        "noise is never escalated).")
                    history.clear()

        if outcome in {AssessmentOutcome.OVERSTATEMENT,
                       AssessmentOutcome.SYSTEMIC_ABUSE,
                       AssessmentOutcome.PROHIBITED_PRACTICE}:
            self._firm_severe_findings[claim.firm_symbol] = \
                self._firm_severe_findings.get(claim.firm_symbol, 0) + 1
        self._assessment_sequence += 1
        action = self._recommended_action(outcome, claim)
        if boundary_mismatch \
                and outcome == AssessmentOutcome.CORRECTABLE_ERROR:
            action = "qualify_and_correct"
        severity = self.severity(outcome)
        rule_ids = self._rule_ids(track, authority, reasons, claim)
        factual_severity = min(
            1.0, materiality * 2.0 + (z_score or 0.0) / 10.0)
        audience_impact = {
            ClaimChannel.MARKETING: 0.85,
            ClaimChannel.PRODUCT_LABEL: 0.90,
            ClaimChannel.INVESTOR_COMMUNICATION: 0.75,
            ClaimChannel.SUSTAINABILITY_REPORT: 0.65,
        }[claim.channel]
        affected_revenue = 0.0
        estimated_benefit = 0.0
        return ClaimAssessment(
            assessment_id=f"A-{day}-{self._assessment_sequence}",
            claim_id=claim.claim_id,
            firm_symbol=claim.firm_symbol,
            day=day,
            outcome=outcome,
            legal_track=track,
            authority=authority,
            estimated_fact=estimated,
            divergence=divergence,
            standard_error=standard_error,
            standardized_divergence=z_score,
            materiality=materiality,
            confidence=confidence,
            reasons=tuple(reasons),
            corrective_action=action,
            affected_revenue=affected_revenue,
            estimated_benefit=estimated_benefit,
            rule_ids=rule_ids,
            factual_severity=factual_severity,
            legal_relevance=1.0,
            audience_impact=audience_impact,
            conduct_severity=severity,
            evidence_conflict=evidence_conflict,
            boundary_mismatch=boundary_mismatch,
            implausible_uncertainty=implausible_uncertainty,
            pattern_escalated=pattern_escalated,
            conflict_independent_evidence_id=conflict_independent_id,
            conflict_internal_evidence_id=conflict_internal_id,
        )

    def _cross_period_checks(self, claim: EnvironmentalClaim,
                             firm_records: list,
                             has_meaningful_qualification: bool,
                             reasons: list) -> tuple[bool, bool]:
        """
        Part I.2 (4.5) -- feasible, evidence-based checks only:

        * cherry-picked period: a short claim period whose evidence is
          materially better than the firm's own adjacent prior-period
          evidence, with no qualification disclosing the selectivity;
        * comparative baseline plausibility: a disclosed baseline that
          contradicts available prior-period evidence, or that cannot be
          verified at all (informational reason only).

        Residual blind spots (documented, deliberately not claimed):
        production-driven absolute reductions and intensity-vs-absolute
        framing cannot be detected without production/output evidence,
        which the model does not give the supervisor.
        """
        period_flag = False
        baseline_flag = False
        claim_days = (claim.period_end - claim.period_start).days
        current = best_evidence(firm_records, claim.subject,
                                claim.period_start, claim.period_end)
        prior = None
        for item in firm_records:
            if item.subject != claim.subject:
                continue
            if item.period_end >= claim.period_start:
                continue
            if (claim.period_start - item.period_end).days > 365:
                continue
            if prior is None or item.period_end > prior.period_end:
                prior = item
        if current is not None and prior is not None \
                and claim_days < 200 and not has_meaningful_qualification:
            gap = current.estimate - prior.estimate
            if claim.subject in LOWER_IS_GREENER:
                gap = -gap
            sigma = max(1e-9, (current.standard_error ** 2
                               + prior.standard_error ** 2) ** 0.5)
            if gap > 2.0 * sigma:
                period_flag = True
                reasons.append(
                    "Selective reporting period: the chosen short period "
                    "is materially greener than the firm's own adjacent "
                    "prior-period evidence and the selectivity is not "
                    "disclosed (EXPERIMENT check).")
        if claim.claim_type == ClaimType.COMPARATIVE \
                and claim.baseline_value is not None:
            if prior is not None:
                gap = prior.estimate - claim.baseline_value
                if claim.subject in LOWER_IS_GREENER:
                    gap = -gap
                if gap > 2.0 * max(1e-9, prior.standard_error):
                    baseline_flag = True
                    reasons.append(
                        "Comparative baseline is materially more "
                        "flattering than the firm's own prior-period "
                        "evidence (EXPERIMENT check).")
            else:
                reasons.append(
                    "Comparative baseline cannot be verified against any "
                    "prior-period evidence (informational; residual "
                    "blind spot).")
        return period_flag, baseline_flag

    @staticmethod
    def _rule_ids(track: LegalTrack, authority: RuleAuthority,
                  reasons: Iterable[str], claim: EnvironmentalClaim) \
            -> tuple[str, ...]:
        ids = []
        if track == LegalTrack.CONSUMER:
            ids.extend(["UCPD-MISLEADING-ACTION",
                        "UCPD-MISLEADING-OMISSION"])
        elif track == LegalTrack.SUSTAINABILITY_REPORTING:
            ids.extend(["CSRD-REPORTING-SCOPE", "CSRD-LIMITED-ASSURANCE"])
        else:
            ids.append("ISSUER-CLEAR-FAIR-NOT-MISLEADING")
        joined = " ".join(reasons)
        mapping = {
            "generic environmental": "D2024-825-GENERIC-CLAIM",
            "offsets": "D2024-825-OFFSET-IMPACT-CLAIM",
            "Scope 3": "D2024-825-WHOLE-BUSINESS-OVERREACH",
            "Future environmental": "D2024-825-FUTURE-PERFORMANCE",
            "label": "D2024-825-SUSTAINABILITY-LABEL",
            "Taxonomy": "TAXONOMY-ELIGIBILITY-ALIGNMENT",
        }
        for fragment, rule_id in mapping.items():
            if fragment in joined:
                ids.append(rule_id)
        if claim.channel == ClaimChannel.INVESTOR_COMMUNICATION:
            ids.append("MAR-PROSPECTUS-TRANSPARENCY-SCOPE-SCREEN")
        return tuple(dict.fromkeys(ids))

    @staticmethod
    def omission_is_valid(omission: ReportingOmission,
                          claim: EnvironmentalClaim, on_date: date) -> bool:
        """A valid report omission never validates inconsistent advertising."""
        return (claim.channel == ClaimChannel.SUSTAINABILITY_REPORT
                and claim.subject == omission.subject
                and omission.valid_for_report(on_date))

    def _prohibited_reasons(self, claim: EnvironmentalClaim,
                            related_claims: Iterable[EnvironmentalClaim],
                            on_date: date,
                            evidence: Optional[EvidenceRecord]) -> list[str]:
        if not self.legal_regime.empowering_consumers_active(on_date):
            return []
        track, _ = self.legal_basis(claim, on_date)
        if track != LegalTrack.CONSUMER:
            return []
        reasons: list[str] = []
        if claim.claim_type == ClaimType.QUALITATIVE \
                and not meaningful_qualification(claim.qualification) \
                and (evidence is None or evidence.confidence < 0.55):
            reasons.append("Unsubstantiated generic environmental claim.")
        if claim.relies_on_offsets \
                and not claim.offset_disclosed_separately:
            reasons.append(
                "Impact-neutrality or reduction claim based on offsets "
                "without transparent separation.")
        if claim.subject == ClaimSubject.NET_ZERO \
                and claim.operational_boundary != "scope_1_2_3":
            reasons.append("Net-zero presentation omits Scope 3 boundary.")
        if claim.claim_type == ClaimType.FUTURE_TARGET \
                and (claim.target_date is None
                     or claim.baseline_value is None
                     or not claim.evidence_ids):
            reasons.append("Future environmental target lacks verifiable plan data.")
        if claim.channel == ClaimChannel.PRODUCT_LABEL \
                and (evidence is None or not evidence.verified):
            reasons.append("Sustainability label lacks independent verification.")
        if claim.subject == ClaimSubject.TAXONOMY_ALIGNMENT:
            eligibility = next((other for other in related_claims
                                if other.firm_symbol == claim.firm_symbol
                                and other.subject
                                == ClaimSubject.TAXONOMY_ELIGIBILITY
                                and other.period_start == claim.period_start),
                               None)
            if eligibility is not None \
                    and claim.asserted_value > eligibility.asserted_value:
                reasons.append("Taxonomy alignment exceeds disclosed eligibility.")
        return reasons

    @staticmethod
    def severity(outcome: AssessmentOutcome) -> float:
        return {
            AssessmentOutcome.SUPPORTED: 0.0,
            AssessmentOutcome.SUPPORTED_WITH_QUALIFICATION: 0.0,
            AssessmentOutcome.NOISE: 0.0,
            AssessmentOutcome.INCONCLUSIVE: 0.10,
            AssessmentOutcome.CORRECTABLE_ERROR: 0.20,
            AssessmentOutcome.NEGLIGENCE: 0.45,
            AssessmentOutcome.OVERSTATEMENT: 0.70,
            AssessmentOutcome.SYSTEMIC_ABUSE: 1.0,
            AssessmentOutcome.PROHIBITED_PRACTICE: 0.90,
            AssessmentOutcome.GREENHUSHING_SIGNAL: 0.0,
        }[outcome]

    @staticmethod
    def _recommended_action(outcome: AssessmentOutcome,
                            claim: EnvironmentalClaim) -> str:
        if outcome in {AssessmentOutcome.SUPPORTED,
                       AssessmentOutcome.SUPPORTED_WITH_QUALIFICATION,
                       AssessmentOutcome.GREENHUSHING_SIGNAL,
                       AssessmentOutcome.NOISE,
                       AssessmentOutcome.INCONCLUSIVE}:
            return "none"
        if outcome == AssessmentOutcome.CORRECTABLE_ERROR:
            return "correct"
        if outcome == AssessmentOutcome.NEGLIGENCE:
            return "qualify_and_correct"
        if claim.channel in {ClaimChannel.MARKETING,
                             ClaimChannel.PRODUCT_LABEL}:
            return "withdraw_publish_and_redress"
        return "correct_and_publish"


class PenaltyPolicy:
    """Experimental sanction calculator with track-specific ceilings.

    Part I.1 -- scale coherence: `sanction_base_turnover` must be the
    SIMULATION-SCALE turnover proxy (multiple x corporate balance), never
    the statutory legal-scope `annual_net_turnover`, so that the statutory
    ceiling RATES (which stay track-gated exactly as before) produce
    proportionate amounts inside the simulation's monetary economy.
    Repeat-offender escalation (EXPERIMENT) multiplies the experimental
    amount for prior severe findings but can never pierce the legal
    ceiling of the applicable track.
    """

    def __init__(self, parameters: SupervisionParameters):
        self.parameters = parameters

    def calculate(self, assessment: ClaimAssessment,
                  sanction_base_turnover: float,
                  estimated_benefit: float, affected_revenue: float,
                  *, cross_border_consumer_case: bool = False,
                  repeat_count: int = 0) -> tuple[float, float, float]:
        severity = EnvironmentalClaimRuleEngine.severity(assessment.outcome)
        confidence = _clamp(assessment.confidence)
        experiment = (self.parameters.benefit_multiplier
                      * max(0.0, estimated_benefit)
                      + self.parameters.affected_revenue_rate
                      * max(0.0, affected_revenue) * severity * confidence)
        escalation = min(self.parameters.repeat_escalation_cap,
                         1.0 + self.parameters.repeat_escalation_rate
                         * max(0, repeat_count))
        experiment *= escalation
        if assessment.legal_track == LegalTrack.DUE_DILIGENCE:
            cap_rate = self.parameters.csddd_cap_rate
        elif (assessment.legal_track == LegalTrack.CONSUMER
              and cross_border_consumer_case):
            cap_rate = self.parameters.consumer_cross_border_cap_rate
        else:
            cap_rate = self.parameters.ordinary_penalty_cap_rate
        cap = max(0.0, sanction_base_turnover) * cap_rate
        return experiment, cap, min(experiment, cap)


class GreenwashingSupervisor:
    """Finite-capacity risk-based supervisor with a persistent case queue."""

    def __init__(self, legal_regime: LegalRegime,
                 rng: random.Random,
                 parameters: SupervisionParameters | None = None):
        self.legal_regime = legal_regime
        self.rng = rng
        self.parameters = parameters or SupervisionParameters()
        self.assurance = LimitedAssuranceService()
        self.rules = EnvironmentalClaimRuleEngine(legal_regime)
        self.penalties = PenaltyPolicy(self.parameters)
        self.claims: dict[str, EnvironmentalClaim] = {}
        self.evidence: dict[str, EvidenceRecord] = {}
        self.assessments: dict[str, ClaimAssessment] = {}
        self.cases: list[RegulatoryCase] = []
        # Part I.3 -- immutable correction/withdrawal event ledger.
        self.correction_events: list[ClaimCorrectionEvent] = []
        self._case_by_claim: dict[str, RegulatoryCase] = {}
        self._investigation_queue: list[tuple[float, int, str]] = []
        self._case_sequence = 0
        self._queue_sequence = 0
        self._investigation_capacity_remaining = 0
        self.total_screened = 0
        self.total_assured_claims = 0
        self.total_evidence_requests = 0
        self.total_investigations = 0
        self.total_published = 0
        self.total_penalties = 0.0
        self.total_penalties_dec = Decimal("0")
        self.total_redress = 0.0
        # Part J (Workstream C) -- conflict-resolution machinery. The
        # re-verification service is an OPTIONAL callable installed by the
        # Simulation: (firm_symbol, subject, day) -> None. It asks the
        # evidence SOURCE (connector register or stylized third party) to
        # re-measure; the resulting EvidenceRecord arrives later through
        # the ordinary evidence flow or `register_external_evidence`. The
        # supervisor itself never measures anything and never sees latent
        # facts.
        self.reverification_service = None
        self.total_conflict_investigations = 0
        self.conflict_outcomes: dict[str, int] = {}
        self.conflict_resolution_delays: list[int] = []
        self._evidence_arrival_day: dict[str, int] = {}
        self._conflict_history: dict[tuple[str, str], int] = {}

    def process_period(self, day: int, on_date: date,
                       assets: Mapping[str, Any],
                       claims: Iterable[EnvironmentalClaim],
                       evidence: Iterable[EvidenceRecord],
                       mandatory_firms: set[str],
                       assurance_rng: random.Random,
                       complaints: Iterable[str] = (),
                       whistleblower_claims: Iterable[str] = (),
                       state: Any = None,
                       connector_flags: Iterable[str] = ()) -> tuple[
                           list[ClaimAssessment], list[RegulatoryCase]]:
        new_claims = list(claims)
        new_evidence = list(evidence)
        self._investigation_capacity_remaining = \
            self.parameters.investigation_capacity
        for claim in new_claims:
            self.claims[claim.claim_id] = claim
        for record in new_evidence:
            self.evidence[record.evidence_id] = record
            self._evidence_arrival_day.setdefault(record.evidence_id, day)

        assured = self.assurance.assure(
            new_claims, new_evidence, mandatory_firms, assurance_rng)
        self.total_assured_claims += len(assured)
        for record in assured:
            self.evidence[record.evidence_id] = record
        all_period_evidence = new_evidence + assured

        complaint_set = set(complaints)
        whistleblower_set = set(whistleblower_claims)
        connector_set = set(connector_flags)
        ranked: list[tuple[float, EnvironmentalClaim, str]] = []
        for claim in new_claims:
            self.total_screened += 1
            priority, trigger = self._screen_priority(
                claim, all_period_evidence, complaint_set,
                whistleblower_set, connector_set)
            ranked.append((priority, claim, trigger))
        ranked.sort(key=lambda item: (-item[0], item[1].claim_id))
        selected = ranked[:self.parameters.evidence_request_capacity]
        self.total_evidence_requests += len(selected)

        period_assessments: list[ClaimAssessment] = []
        opened_cases: list[RegulatoryCase] = []
        for priority, claim, trigger in selected:
            self._case_sequence += 1
            track, authority = self.rules.legal_basis(claim, on_date)
            case = RegulatoryCase(
                case_id=f"R-{day}-{self._case_sequence}",
                firm_symbol=claim.firm_symbol,
                claim_id=claim.claim_id,
                opened_day=day,
                legal_track=track,
                authority=authority,
                priority=priority,
                trigger=trigger,
            )
            case.transition(day, CaseState.SCREENED)
            case.transition(day, CaseState.EVIDENCE_REQUESTED)
            case.transition(day, CaseState.UNDER_ASSESSMENT)
            assessment = self.rules.assess(
                claim, all_period_evidence, day, on_date, new_claims)
            if (self.parameters.qualified_claim_safe_harbor_enabled
                    and assessment.outcome == AssessmentOutcome.NEGLIGENCE
                    and bool(claim.qualification)):
                matched = best_evidence(
                    (item for item in all_period_evidence
                     if item.firm_symbol == claim.firm_symbol),
                    claim.subject, claim.period_start, claim.period_end)
                if matched is not None and matched.verified \
                        and matched.confidence >= 0.55:
                    assessment.outcome = \
                        AssessmentOutcome.CORRECTABLE_ERROR
                    assessment.corrective_action = "correct"
                    assessment.reasons += (
                        "EXPERIMENT: qualified evidence-backed claim receives "
                        "safe-harbor-like correction treatment.",)
            case.assessment_id = assessment.assessment_id
            self.assessments[assessment.assessment_id] = assessment
            assets[claim.firm_symbol].assessment_history.append(assessment)
            period_assessments.append(assessment)
            self.cases.append(case)
            self._case_by_claim[claim.claim_id] = case
            opened_cases.append(case)

            if assessment.evidence_conflict:
                # Part J (Workstream C): an unresolved cross-source
                # conflict is a PROCEDURAL problem, not a free pass. The
                # case enters the shared finite investigation queue under
                # a transparent priority rule and will consume one
                # investigation slot when opened. The assessment outcome
                # stays INCONCLUSIVE and no sanction can be based on the
                # conflicting file (Part I.2/4.4 guarantee preserved).
                case.conflict_case = True
                case.priority = min(
                    0.94, max(case.priority,
                              self.parameters.conflict_priority))
                key = (claim.firm_symbol, claim.subject.value)
                self._conflict_history[key] = \
                    self._conflict_history.get(key, 0) + 1
                case.transition(day, CaseState.CONFLICT_RESOLUTION)
                self._queue_sequence += 1
                heapq.heappush(
                    self._investigation_queue,
                    (-case.priority, self._queue_sequence, case.case_id))
            elif assessment.outcome in {
                    AssessmentOutcome.SUPPORTED,
                    AssessmentOutcome.SUPPORTED_WITH_QUALIFICATION,
                    AssessmentOutcome.GREENHUSHING_SIGNAL,
                    AssessmentOutcome.NOISE,
                    AssessmentOutcome.INCONCLUSIVE}:
                case.transition(day, CaseState.CLOSED)
                case.closed_day = day
            elif assessment.outcome in {
                    AssessmentOutcome.CORRECTABLE_ERROR,
                    AssessmentOutcome.NEGLIGENCE}:
                case.remedy = assessment.corrective_action
                case.correction_due_day = day \
                    + self.parameters.correction_window_days
                case.scheduled_compliance_day = day \
                    + max(1, self.parameters.correction_window_days // 2)
                case.transition(day, CaseState.CORRECTION_WINDOW)
            else:
                self._queue_sequence += 1
                heapq.heappush(self._investigation_queue,
                               (-priority, self._queue_sequence, case.case_id))

        self._open_investigations(day, assets, state)
        return period_assessments, opened_cases

    def _screen_priority(self, claim: EnvironmentalClaim,
                         evidence: list[EvidenceRecord],
                         complaints: set[str], whistleblowers: set[str],
                         connector_flags: set[str] = frozenset()) \
            -> tuple[float, str]:
        if claim.claim_id in whistleblowers:
            return 1.0, "whistleblower"
        if claim.claim_id in complaints:
            return 0.95, "complaint"
        # Part H, Regime C: a material reconciliation finding routes the
        # claim into the ordinary queue with high priority. This is a
        # POLICY-CAUSED screening signal, not an automatic sanction: the
        # assessment, correction window, investigation and any penalty
        # still follow the unchanged procedural path below. Empty set =>
        # byte-identical control flow for the baseline arm.
        if claim.claim_id in connector_flags:
            return 0.90, "connector_reconciliation"
        priority = 0.20
        trigger = "risk_screening"
        if claim.channel in {ClaimChannel.MARKETING,
                             ClaimChannel.PRODUCT_LABEL}:
            priority += 0.20
        if claim.claim_type in {ClaimType.OFFSET_BASED,
                                ClaimType.TAXONOMY,
                                ClaimType.FUTURE_TARGET}:
            priority += 0.20
        priority += min(0.20, 0.05 * self.rules._firm_severe_findings.get(
            claim.firm_symbol, 0))
        record = best_evidence((item for item in evidence
                                if item.firm_symbol == claim.firm_symbol),
                               claim.subject,
                               claim.period_start, claim.period_end)
        if record is None:
            priority += 0.20
        else:
            raw = claim.asserted_value - record.estimate
            greener_gap = -raw if claim.subject in LOWER_IS_GREENER else raw
            priority += min(0.35, max(0.0, greener_gap)
                            / max(abs(record.estimate), 1.0))
        if self.rng.random() < self.parameters.random_surveillance_share:
            priority += 0.25
            trigger = "random_surveillance"
        return min(0.94, priority), trigger

    def _open_investigations(self, day: int,
                             assets: Mapping[str, Any], state: Any) -> None:
        case_lookup = {case.case_id: case for case in self.cases}
        # Part J (Workstream C): a share of the remaining capacity is
        # RESERVED for queued conflict investigations (a dedicated
        # data-dispute desk, EXPERIMENT), so an endless stream of
        # higher-priority enforcement cases cannot starve disputes
        # forever. Conflicts still compete for ordinary slots once the
        # reserve is used, and the reserve never exceeds the number of
        # conflicts actually waiting.
        waiting_conflicts = 0
        for _, _, queued_id in self._investigation_queue:
            queued = case_lookup.get(queued_id)
            if queued is not None \
                    and queued.state == CaseState.CONFLICT_RESOLUTION \
                    and queued.conflict_investigation_day is None:
                waiting_conflicts += 1
        reserved = min(waiting_conflicts, int(round(
            max(0.0, self.parameters.conflict_capacity_share)
            * self._investigation_capacity_remaining)))
        deferred: list[tuple[float, int, str]] = []
        while (self._investigation_capacity_remaining > 0
               and self._investigation_queue):
            entry = heapq.heappop(self._investigation_queue)
            _, _, case_id = entry
            case = case_lookup[case_id]
            if case.state == CaseState.CONFLICT_RESOLUTION \
                    and case.conflict_investigation_day is None:
                # A conflict investigation consumes one slot of the SAME
                # finite investigation capacity as an enforcement case.
                # The regulator asks the evidence source to re-measure
                # (when a service is installed) and sets the procedural
                # resolution clock; the decision itself happens in
                # `advance_day` once evidence or the timeout arrives.
                self._investigation_capacity_remaining -= 1
                reserved = max(0, reserved - 1)
                self.total_conflict_investigations += 1
                case.conflict_investigation_day = day
                case.conflict_resolution_due_day = day \
                    + self.parameters.conflict_resolution_days
                if self.reverification_service is not None:
                    claim = self.claims[case.claim_id]
                    self.reverification_service(
                        claim.firm_symbol, claim.subject, day)
                continue
            if case.state != CaseState.UNDER_ASSESSMENT:
                continue
            if self._investigation_capacity_remaining <= reserved:
                # Every remaining slot is held for a queued conflict;
                # this enforcement case keeps its queue position.
                deferred.append(entry)
                continue
            self._investigation_capacity_remaining -= 1
            self.total_investigations += 1
            case.transition(day, CaseState.FORMAL_INVESTIGATION)
            assessment = self.assessments[case.assessment_id]
            claim = self.claims[case.claim_id]
            asset = assets[case.firm_symbol]
            # Part I.1 sanction-scale bridge (STYLIZATION): all monetary
            # sanction bases live in SIMULATION-SCALE units. The statutory
            # annual_net_turnover (legal-scope units, ~1e8 EUR) is used
            # only for scope tests and must never price a penalty against
            # balances that are ~1e6 -- that unit mismatch made sanctions
            # near-total confiscations (red-team finding P0-1).
            sim_turnover = self.parameters.sim_turnover_balance_multiple \
                * max(0.0, asset.balance)
            affected_revenue = sim_turnover * {
                ClaimChannel.MARKETING: 0.04,
                ClaimChannel.PRODUCT_LABEL: 0.03,
                ClaimChannel.INVESTOR_COMMUNICATION: 0.015,
                ClaimChannel.SUSTAINABILITY_REPORT: 0.01,
            }[claim.channel]
            estimated_benefit = affected_revenue * min(
                0.10, max(0.0, assessment.materiality) * 0.10)
            assessment.affected_revenue = affected_revenue
            assessment.estimated_benefit = estimated_benefit
            repeat_count = max(
                0, self.rules._firm_severe_findings.get(
                    case.firm_symbol, 0) - 1)
            calculated, cap, penalty = self.penalties.calculate(
                assessment, sim_turnover, estimated_benefit,
                affected_revenue,
                cross_border_consumer_case=case.cross_border_consumer_case,
                repeat_count=repeat_count)
            case.calculated_penalty = calculated
            case.applicable_cap = cap
            headroom = max(0.0, asset.balance - CORPORATE_BALANCE_FLOOR)
            case.applied_penalty = round(min(penalty, headroom), 2)
            assessment.penalty = case.applied_penalty
            case.remedy = assessment.corrective_action
            # The outcome becomes final before any monetary transfer.
            case.decision_day = day
            case.transition(day, CaseState.DECIDED)
            if case.applied_penalty > 0.0:
                asset.balance -= case.applied_penalty
                if state is not None:
                    penalty_dec = Decimal(str(case.applied_penalty))
                    state.receive_penalty(penalty_dec)
                    self.total_penalties_dec += penalty_dec
                self.total_penalties += case.applied_penalty
            if "redress" in case.remedy:
                case.redress = round(max(0.0, min(
                    affected_revenue * 0.001,
                    headroom - case.applied_penalty)), 2)
                if case.redress > 0.0:
                    # Consumers are exogenous in this model, so redress is a
                    # separately logged external outflow, not State revenue.
                    asset.balance -= case.redress
                    self.total_redress += case.redress
            if "withdraw" in case.remedy:
                original = claim.historical_asserted_value
                claim.record_withdrawal(day)
                self.correction_events.append(ClaimCorrectionEvent(
                    day=day, claim_id=claim.claim_id,
                    firm_symbol=claim.firm_symbol, event="withdrawal",
                    original_value=original, corrected_value=None,
                    exposure_days=claim.exposure_days(day),
                    legal_track=case.legal_track.value,
                    case_id=case.case_id,
                    basis="ordered withdrawal after formal investigation"))
            self._publish(case, assessment, asset, day)
        # Enforcement cases skipped in favour of the conflict reserve go
        # back into the queue with their original priority and sequence.
        for entry in deferred:
            heapq.heappush(self._investigation_queue, entry)

    def register_external_evidence(self, record: EvidenceRecord,
                                   day: int) -> None:
        """Part J (Workstream C): out-of-cycle arrival of source evidence
        (register corrections, commissioned re-verifications). Only the
        uncertain EvidenceRecord output of the source's measurement
        apparatus ever reaches the supervisor."""
        self.evidence[record.evidence_id] = record
        self._evidence_arrival_day.setdefault(record.evidence_id, day)

    def advance_day(self, day: int, assets: Mapping[str, Any],
                    state: Any = None,
                    on_date: Optional[date] = None) -> None:
        """Process voluntary corrections, conflict resolutions and queued
        investigations."""
        if on_date is None:
            from datetime import timedelta
            anchor = getattr(self.legal_regime, "simulation_start_date",
                             date(2026, 1, 1))
            on_date = anchor + timedelta(days=max(0, int(day) - 1))
        for case in self.cases:
            if case.state == CaseState.CONFLICT_RESOLUTION \
                    and case.conflict_investigation_day is not None \
                    and case.conflict_resolution_due_day is not None \
                    and day >= case.conflict_resolution_due_day:
                self._resolve_conflict(case, day, assets, on_date)
        for case in self.cases:
            if case.state != CaseState.CORRECTION_WINDOW:
                continue
            if case.scheduled_compliance_day is not None \
                    and day >= case.scheduled_compliance_day:
                assessment = self.assessments[case.assessment_id]
                claim = self.claims[case.claim_id]
                if assessment.estimated_fact is not None:
                    # Part I.3: prospective public correction that
                    # preserves the original assertion immutably.
                    original = claim.historical_asserted_value
                    claim.record_correction(
                        day, assessment.estimated_fact,
                        basis=f"supervisory_correction:{case.case_id}",
                        qualification=("Corrected following supervisory "
                                       "evidence review."))
                    self.correction_events.append(ClaimCorrectionEvent(
                        day=day, claim_id=claim.claim_id,
                        firm_symbol=claim.firm_symbol, event="correction",
                        original_value=original,
                        corrected_value=assessment.estimated_fact,
                        exposure_days=claim.exposure_days(day),
                        legal_track=case.legal_track.value,
                        case_id=case.case_id,
                        basis="voluntary compliance in correction window"))
                case.decision_day = day
                case.transition(day, CaseState.DECIDED)
                self._publish(case, assessment, assets[case.firm_symbol], day)
            elif case.correction_due_day is not None \
                    and day > case.correction_due_day:
                self._queue_sequence += 1
                case.transition(day, CaseState.UNDER_ASSESSMENT)
                heapq.heappush(self._investigation_queue,
                               (-case.priority, self._queue_sequence,
                                case.case_id))
        self._open_investigations(day, assets, state)

    # ------------------------------------------------------------------ #
    # Part J (Workstream C): evidence-conflict resolution
    # ------------------------------------------------------------------ #
    _CONFLICT_INDEPENDENT_SOURCES = frozenset({
        EvidenceSource.THIRD_PARTY, EvidenceSource.PUBLIC_DATA,
        EvidenceSource.REGULATOR_ESTIMATE,
        EvidenceSource.CERTIFIED_PUBLIC_CONNECTOR,
    })

    def _resolve_conflict(self, case: RegulatoryCase, day: int,
                          assets: Mapping[str, Any],
                          on_date: date) -> None:
        """Decide one opened conflict investigation.

        Decision table (transparent, information-safe -- only
        EvidenceRecord outputs are read, never latent facts):

        1. A fresh TRULY INDEPENDENT record (third party, public data,
           regulator estimate or connector; assurance and company records
           are derived from the firm's own data and never corroborate)
           arrived after the case opened:
             - agrees with the firm's record  -> external register was
               wrong: confirmation + register correction;
             - agrees with the original independent record -> corroborated
               evidence: escalate through the ORDINARY procedural path
               (re-assessment on the independent file; formal
               investigation only if that assessment warrants one);
             - agrees with neither -> dismissal (still unresolved).
        2. No re-measurement within the timeout: procedural-credibility
           fallback. Without corroboration the case can NEVER escalate;
           the strongest available response is a correction demand.
        An automatic sanction from an unresolved source conflict is
        impossible by construction.
        """
        assessment = self.assessments[case.assessment_id]
        claim = self.claims[case.claim_id]
        independent = self.evidence.get(
            assessment.conflict_independent_evidence_id or "")
        internal = self.evidence.get(
            assessment.conflict_internal_evidence_id or "")
        opened = case.conflict_investigation_day \
            if case.conflict_investigation_day is not None \
            else case.opened_day
        timeout_day = opened \
            + self.parameters.conflict_reverification_timeout_days

        excluded_ids = {assessment.conflict_independent_evidence_id,
                        assessment.conflict_internal_evidence_id}
        fresh = [record for record in self.evidence.values()
                 if record.firm_symbol == claim.firm_symbol
                 and record.subject == claim.subject
                 and record.source in self._CONFLICT_INDEPENDENT_SOURCES
                 and record.evidence_id not in excluded_ids
                 and self._evidence_arrival_day.get(
                     record.evidence_id, -1) > case.opened_day]
        fresh.sort(key=lambda record: self._evidence_arrival_day.get(
            record.evidence_id, -1))
        newest = fresh[-1] if fresh else None

        def _agrees(first: Optional[EvidenceRecord],
                    second: Optional[EvidenceRecord]) -> bool:
            if first is None or second is None:
                return False
            sigma = max(1e-9, (first.standard_error ** 2
                               + second.standard_error ** 2) ** 0.5)
            return abs(first.estimate - second.estimate) \
                <= EVIDENCE_CONFLICT_Z * sigma

        outcome: Optional[str] = None
        if newest is not None:
            if _agrees(newest, internal):
                outcome = "external_register_corrected"
            elif _agrees(newest, independent):
                outcome = "escalated_corroborated"
            else:
                outcome = "dismissed_unresolved"
        elif day >= timeout_day:
            margin = self.parameters.conflict_credibility_margin
            independent_confidence = independent.confidence \
                if independent is not None else 0.0
            internal_confidence = internal.confidence \
                if internal is not None else 0.0
            if internal_confidence - independent_confidence >= margin:
                outcome = "confirmed_firm_claim"
            elif independent_confidence - internal_confidence >= margin:
                outcome = "claim_corrected"
            else:
                outcome = "dismissed_unresolved"
        if outcome is None:
            return    # Waiting for re-verification; queue age keeps growing.

        case.conflict_resolved_day = day
        case.conflict_outcome = outcome
        self.conflict_outcomes[outcome] = \
            self.conflict_outcomes.get(outcome, 0) + 1
        self.conflict_resolution_delays.append(
            max(0, day - case.opened_day))
        asset = assets[case.firm_symbol]

        if outcome in {"confirmed_firm_claim",
                       "external_register_corrected"}:
            # Public rehabilitation: consumers and investors learn that
            # the dispute ended in the firm's favour; the register error
            # (if any) is being corrected prospectively at the source.
            case.remedy = "none"
            case.decision_day = day
            case.transition(day, CaseState.DECIDED)
            asset.public_environmental_signals.append(
                PublicEnvironmentalSignal(
                    firm_symbol=case.firm_symbol, day=day,
                    supported_score=asset.supported_green_score,
                    credibility=max(0.05, assessment.confidence),
                    perceived_discrepancy=0.0,
                    controversy_discount=0.0,
                    source="conflict_resolution_confirmation",
                    confirmed_abuse=False))
            case.publication_day = day
            case.transition(day, CaseState.PUBLISHED)
            case.closed_day = day
            case.transition(day, CaseState.CLOSED)
            self.total_published += 1
        elif outcome == "claim_corrected":
            # Correction demand through the existing correction-window
            # machinery, targeting the independent estimate. Not a
            # sanction; non-compliance follows the ordinary escalation.
            if independent is not None:
                assessment.estimated_fact = independent.estimate
            assessment.corrective_action = "qualify_and_correct"
            case.remedy = "qualify_and_correct"
            case.correction_due_day = day \
                + self.parameters.correction_window_days
            case.scheduled_compliance_day = day \
                + max(1, self.parameters.correction_window_days // 2)
            case.transition(day, CaseState.CORRECTION_WINDOW)
        elif outcome == "escalated_corroborated":
            # Corroborated file: re-assess EXCLUDING the discredited
            # internal record; the resulting outcome follows the ordinary
            # procedural path. The conflict itself never sanctions.
            corroborated = list(fresh)
            if independent is not None:
                corroborated.append(independent)
            new_assessment = self.rules.assess(
                claim, corroborated, day, on_date)
            case.assessment_id = new_assessment.assessment_id
            self.assessments[new_assessment.assessment_id] = new_assessment
            asset.assessment_history.append(new_assessment)
            if new_assessment.outcome in {
                    AssessmentOutcome.CORRECTABLE_ERROR,
                    AssessmentOutcome.NEGLIGENCE}:
                case.remedy = new_assessment.corrective_action
                case.correction_due_day = day \
                    + self.parameters.correction_window_days
                case.scheduled_compliance_day = day \
                    + max(1, self.parameters.correction_window_days // 2)
                case.transition(day, CaseState.CORRECTION_WINDOW)
            elif new_assessment.confirmed_abuse:
                case.transition(day, CaseState.UNDER_ASSESSMENT)
                self._queue_sequence += 1
                heapq.heappush(
                    self._investigation_queue,
                    (-case.priority, self._queue_sequence, case.case_id))
            else:
                case.remedy = "none"
                case.closed_day = day
                case.transition(day, CaseState.CLOSED)
        else:   # dismissed_unresolved
            case.remedy = "none"
            case.closed_day = day
            case.transition(day, CaseState.CLOSED)

    def _publish(self, case: RegulatoryCase, assessment: ClaimAssessment,
                 asset: Any, day: int) -> None:
        assessment.published = True
        if assessment.estimated_fact is not None \
                and self.claims[case.claim_id].subject \
                == ClaimSubject.GREEN_SCORE:
            asset.supported_green_score = _clamp(assessment.estimated_fact)
        if assessment.confirmed_abuse:
            asset.supported_green_score = min(
                asset.supported_green_score,
                asset.disclosed_green_score * 0.75)
            asset.last_scandal_day = day
        signal = PublicEnvironmentalSignal(
            firm_symbol=case.firm_symbol,
            day=day,
            supported_score=asset.supported_green_score,
            credibility=max(0.05, assessment.confidence
                            * (0.45 if assessment.confirmed_abuse else 1.0)),
            perceived_discrepancy=max(0.0, assessment.materiality),
            controversy_discount=min(
                0.35, 0.30 * EnvironmentalClaimRuleEngine.severity(
                    assessment.outcome)),
            source="published_supervisory_decision",
            confirmed_abuse=assessment.confirmed_abuse,
        )
        asset.public_environmental_signals.append(signal)
        case.publication_day = day
        case.transition(day, CaseState.PUBLISHED)
        case.closed_day = day
        case.transition(day, CaseState.CLOSED)
        self.total_published += 1

    @property
    def pending_queue_length(self) -> int:
        # Conflict cases waiting IN the queue are counted through the
        # queue itself; opened-but-unresolved conflict investigations are
        # pending workload too (Part J).
        return len(self._investigation_queue) + sum(
            case.state == CaseState.CORRECTION_WINDOW
            or (case.state == CaseState.CONFLICT_RESOLUTION
                and case.conflict_investigation_day is not None)
            for case in self.cases)
