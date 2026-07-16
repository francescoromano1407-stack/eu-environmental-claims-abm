"""Part H: the two proposed State-intervention policy experiments.

This module implements the machinery of Regimes B and C of the three-regime
comparison:

  Regime A  Current EU-compliant supervision -- ALREADY implemented by
            ``greenwashing_supervision.py`` and untouched here. It is the
            control arm.
  Regime B  ``SMEPrescreeningHub`` -- a State-operated digital
            pre-screening service for voluntary ESG communications of
            smaller undertakings.
  Regime C  ``CertifiedGreenDataConnector`` -- public infrastructure that
            transfers authorized environmental data from verified sources
            into structured evidence and report fields, plus a
            reconciliation engine.

LEGAL STATUS (do not cite this module as EU law)
------------------------------------------------
Neither regime B nor regime C is required, established or endorsed by
Directive (EU) 2026/470 or by any other instrument in the model baseline
(UCPD, Directive (EU) 2024/825, CSRD as amended, Taxonomy Regulation, MAR,
CSDDD). Both are PROPOSED NATIONAL POLICY EXPERIMENTS:

* The only legal anchor used by the hub is the population it serves: the
  <= 1000 average-employee line of the "protected undertakings" in the
  value-chain cap and the Art. 29ca voluntary-use reporting standards
  introduced by Directive (EU) 2026/470 (recitals 12, 21-22; new
  Art. 29ca of Directive 2013/34/EU). Those provisions FACILITATE
  voluntary reporting by such firms; they do not create a pre-screening
  service, and the 1000-employee value-chain protection is NEVER treated
  here as an exemption from consumer law, investigations or
  substantiation duties.
* The connector stylizes technologically enabled public data
  infrastructure. No provision of Directive (EU) 2026/470 mandates data
  connections, certification methods or automatic transfers; national
  implementation, privacy law (GDPR), cybersecurity law (NIS2) and
  sector rules would govern a real deployment and are represented only
  as reduced-form states, costs and failure modes.

Information boundaries
----------------------
* The hub processes DRAFT structured claims WITHOUT any access to the
  latent ``EnvironmentalFactVector``. It may read only: the draft claim,
  evidence voluntarily submitted by the firm, previously published
  claims, prior corrections/decisions, and its own templates/checklists.
* The connector is a simulated *measurement apparatus*: like the firm's
  own meters (``CorporateCommunicationsPolicy._make_evidence``), its
  transfer function observes the physical ledger through an explicit
  error model (meter error, facility mismatch, staleness, register
  errors, downtime, cyber incidents) and emits ``EvidenceRecord`` objects
  with strictly positive uncertainty. No decision logic anywhere reads
  the latent vector, and connector data cover only the configured
  metrics -- they never validate whole-company claims, Taxonomy
  alignment, net-zero claims, lifecycle claims or future performance.

No State endorsement
--------------------
Passing pre-screening yields ``prescreening_status =
"non_binding_preventive_feedback"`` and the visible disclaimer below. It
is not legal approval, not assurance, does not preclude enforcement and
grants no conclusive safe harbour. A configurable safe-harbour-LIKE
experiment exists (default OFF) and can never protect deliberate
concealment, prohibited practices, repeated abuse, or claims contradicted
by evidence known to the firm.

Every behavioural coefficient read from ``constants`` in this module is
an ``EXPERIMENT`` value unless explicitly marked LEGAL-ANCHOR there.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
import random
from typing import Any, Iterable, Optional

from market_sim.constants import (
    CONNECTOR_CYBER_GOVERNANCE_DAILY_DEC,
    CONNECTOR_CYBER_INCIDENT_PROBABILITY,
    CONNECTOR_DOWNTIME_PROBABILITY,
    CONNECTOR_FIRM_INTEGRATION_COST_DEC,
    CONNECTOR_METER_RELATIVE_ERROR,
    CONNECTOR_MISMATCH_BIAS,
    CONNECTOR_MISMATCH_PROBABILITY,
    CONNECTOR_REGISTER_ERROR_PROBABILITY,
    CONNECTOR_CORRECTION_DELAY_DAYS,
    CONNECTOR_SELECTIVE_THRESHOLD,
    CONNECTOR_STALE_DAYS,
    CONNECTOR_STALE_PROBABILITY,
    CONNECTOR_STATE_DAILY_OPERATING_DEC,
    CONNECTOR_STATE_SETUP_COST_DEC,
    CONNECTOR_UPTAKE_ADAPTIVE,
    CONNECTOR_UPTAKE_GREENWASHER,
    CONNECTOR_UPTAKE_HONEST,
    CORPORATE_BALANCE_FLOOR,
    CREDIT_CENT_DEC,
    PRESCREEN_FIRM_COST_PER_SUBMISSION_DEC,
    PRESCREEN_FIRM_REVISION_COST_DEC,
    PRESCREEN_MAX_EMPLOYEES,
    PRESCREEN_NOISE_DEFAULT,
    PRESCREEN_PROCESSING_DELAY_DAYS,
    PRESCREEN_SAFE_HARBOR_ENABLED,
    PRESCREEN_STATE_COST_PER_SUBMISSION_DEC,
    PRESCREEN_STATE_SETUP_COST_DEC,
    PRESCREEN_STRICTNESS_DEFAULT,
    PRESCREEN_UPTAKE_ADAPTIVE,
    PRESCREEN_UPTAKE_AUTO_INVITE,
    PRESCREEN_UPTAKE_GREENWASHER,
    PRESCREEN_UPTAKE_HONEST,
    PRESCREEN_UPTAKE_SUBSIDIZED_BOOST,
    RECONCILE_CORRECTION_Z,
    RECONCILE_NOISE_Z,
    RECONCILE_REPEAT_THRESHOLD,
    RECONCILE_ROUNDING_REL,
    RECONCILE_SUSPICIOUS_Z,
    UNCERTAINTY_PLAUSIBILITY_MULTIPLE,
)
from market_sim.environmental_claims import (
    ClaimChannel,
    ClaimSubject,
    ClaimType,
    EnvironmentalClaim,
    EvidenceRecord,
    EvidenceSource,
    meaningful_qualification,
)

_ZERO = Decimal("0")


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return min(upper, max(lower, float(value)))


def _dec_cents(value: float) -> Decimal:
    return Decimal(str(round(float(value), 2))).quantize(CREDIT_CENT_DEC)


LOWER_IS_GREENER = {
    ClaimSubject.SCOPE_1_EMISSIONS,
    ClaimSubject.SCOPE_2_EMISSIONS,
    ClaimSubject.SCOPE_3_EMISSIONS,
    ClaimSubject.WATER_INTENSITY,
    ClaimSubject.POLLUTION_INTENSITY,
    ClaimSubject.BIODIVERSITY_PRESSURE,
    ClaimSubject.NET_ZERO,
}


class GreenwashingPolicyRegime(str, Enum):
    """The three comparable State-intervention regimes (plus an optional
    hybrid EXPERIMENT arm used only when explicitly requested)."""

    CURRENT_EU_SUPERVISION = "current_eu_supervision"
    SME_ALGORITHMIC_PRESCREENING = "sme_algorithmic_prescreening"
    CERTIFIED_GREEN_DATA_CONNECTOR = "certified_green_data_connector"
    # EXPERIMENT extra arm: both proposed instruments together, used to
    # answer the Section-9 hybrid question. Not part of the default
    # three-regime comparison.
    HYBRID_PRESCREENING_AND_CONNECTOR = "hybrid_prescreening_and_connector"


# --------------------------------------------------------------------------- #
# Regime B: SME voluntary-reporting algorithmic pre-screening hub
# --------------------------------------------------------------------------- #
class PrescreeningParticipationMode(str, Enum):
    VOLUNTARY = "voluntary"                       # Default.
    SUBSIDIZED = "subsidized"                     # State pays the firm fee.
    AUTO_INVITATION = "auto_invitation"           # Default-in, may decline.
    MANDATORY_COUNTERFACTUAL = "mandatory_counterfactual"  # Disabled default.


class DraftClaimState(str, Enum):
    DRAFT = "draft"
    SUBMITTED_TO_PRESCREENING = "submitted_to_prescreening"
    AUTOMATED_FEEDBACK = "automated_feedback"
    FIRM_REVISION_OR_REJECTION = "firm_revision_or_rejection"
    PUBLISHED_OR_WITHHELD = "published_or_withheld"


PRESCREENING_STATUS = "non_binding_preventive_feedback"
PRESCREENING_DISCLAIMER = (
    "Automated preventive feedback only. This service does not approve the "
    "claim, does not guarantee its accuracy, is not assurance within the "
    "meaning of Directive 2006/43/EC, does not preclude enforcement under "
    "consumer, reporting or market law, and confers no safe harbour.")


@dataclass(frozen=True)
class PrescreeningIssue:
    """One explainable finding of the screening algorithm."""

    issue_code: str
    explanation: str
    affected_field: str
    evidence_deficiency: str
    recommended_correction: str
    recommended_qualification: str
    confidence: float
    reference: str            # Legal or voluntary-standard reference.
    legally_material: bool    # False => merely informational.

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PrescreeningFeedback:
    claim_id: str
    firm_symbol: str
    day: int
    issues: tuple[PrescreeningIssue, ...]
    prescreening_status: str = PRESCREENING_STATUS
    disclaimer: str = PRESCREENING_DISCLAIMER
    processing_delay_days: int = PRESCREEN_PROCESSING_DELAY_DAYS

    @property
    def materially_flagged(self) -> bool:
        return any(issue.legally_material for issue in self.issues)


@dataclass
class PrescreeningEvent:
    """One row of the pre-screening event ledger."""

    event_id: str
    day: int
    firm_symbol: str
    claim_id: str
    subject: str
    channel: str
    participation_mode: str
    state_trace: tuple[str, ...]
    issues_total: int
    issues_material: int
    issue_codes: tuple[str, ...]
    action: str               # published_clean / revised / withdrawn /
                              # published_against_advice / declined
    firm_cost: float
    state_cost: float
    processing_delay_days: int
    prescreening_status: str = PRESCREENING_STATUS
    # Part I.5 -- honest prevention accounting.
    draft_value: Optional[float] = None
    published_value: Optional[float] = None
    spurious_only: bool = False   # Flags were informational/noise only.

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["state_trace"] = "|".join(self.state_trace)
        result["issue_codes"] = "|".join(self.issue_codes)
        return result


@dataclass(frozen=True)
class PrescreeningParameters:
    """All EXPERIMENT values; participation is voluntary by default and the
    mandatory mode exists only as an explicitly enabled counterfactual."""

    participation_mode: PrescreeningParticipationMode = \
        PrescreeningParticipationMode.VOLUNTARY
    strictness: float = PRESCREEN_STRICTNESS_DEFAULT
    noise: float = PRESCREEN_NOISE_DEFAULT
    max_employees: float = PRESCREEN_MAX_EMPLOYEES     # LEGAL-ANCHOR line.
    safe_harbor_enabled: bool = PRESCREEN_SAFE_HARBOR_ENABLED
    # Part J sensitivity levers (EXPERIMENT; defaults preserve behaviour):
    # multiplies every strategy's baseline participation propensity, and
    # sets the operational review delay of a submitted draft.
    participation_scale: float = 1.0
    processing_delay_days: int = PRESCREEN_PROCESSING_DELAY_DAYS
    state_setup_cost_dec: Decimal = PRESCREEN_STATE_SETUP_COST_DEC
    state_cost_per_submission_dec: Decimal = \
        PRESCREEN_STATE_COST_PER_SUBMISSION_DEC
    firm_cost_per_submission_dec: Decimal = \
        PRESCREEN_FIRM_COST_PER_SUBMISSION_DEC
    firm_revision_cost_dec: Decimal = PRESCREEN_FIRM_REVISION_COST_DEC


class SMEPrescreeningHub:
    """State-operated pre-publication screening of voluntary ESG claims.

    Workflow per draft claim::

        DRAFT -> SUBMITTED_TO_PRESCREENING -> AUTOMATED_FEEDBACK
              -> FIRM_REVISION_OR_REJECTION -> PUBLISHED_OR_WITHHELD

    The hub never receives latent truth; every check below reads only the
    draft claim, firm-submitted evidence, prior published claims and prior
    public decisions.
    """

    def __init__(self, parameters: Optional[PrescreeningParameters] = None):
        self.parameters = parameters or PrescreeningParameters()
        self.events: list[PrescreeningEvent] = []
        self.feedback_log: list[PrescreeningFeedback] = []
        self._event_sequence = 0
        self.setup_paid = False
        self.state_cost_dec = _ZERO
        self.firm_cost_dec: dict[str, Decimal] = {}
        self.submissions = 0
        self.revisions = 0
        self.withdrawals = 0
        self.published_against_advice = 0
        self.published_clean = 0
        self.declined_participations = 0
        # Part I.5 -- honest prevention accounting: a "revision" counts
        # as meaningful only when it responded to at least one legally
        # material issue; responses to purely informational or spurious
        # flags are tracked separately and never enter prevention metrics.
        self.meaningful_revisions = 0
        self.noise_flag_events = 0
        # Part I.5 -- ITT/TOT composition audit (research-only labels):
        # per corporate strategy: eligible firm-periods, participating
        # firm-periods, submissions, meaningful revisions, withdrawals,
        # publications against advice.
        self.composition: dict[str, dict[str, int]] = {}
        # Claim ids that were screened with no legally material issue at
        # publication time -- consumed only by the optional (default-off)
        # safe-harbour-like experiment.
        self.cleanly_prescreened: set[str] = set()
        # Per-firm feedback history for recurrence metrics.
        self.prior_issue_codes: dict[str, set[str]] = {}
        self.repeat_issue_count = 0

    # -- eligibility and participation ------------------------------------- #
    def is_eligible(self, average_employees: float,
                    mandatory_csrd: bool) -> bool:
        """<= 1000 average employees AND outside mandatory CSRD scope.

        LEGAL-ANCHOR: the employee line mirrors the protected-undertaking
        threshold of Directive (EU) 2026/470 (Art. 29ca / recital 12).
        Eligibility for this VOLUNTARY service is all it scopes: it is not
        an exemption from consumer law or substantiation duties.
        """
        return (average_employees <= self.parameters.max_employees
                and not mandatory_csrd)

    def participates(self, strategy: str, rng: random.Random) -> bool:
        mode = self.parameters.participation_mode
        if mode == PrescreeningParticipationMode.MANDATORY_COUNTERFACTUAL:
            return True
        base = {
            "honest": PRESCREEN_UPTAKE_HONEST,
            "adaptive": PRESCREEN_UPTAKE_ADAPTIVE,
            "greenwasher": PRESCREEN_UPTAKE_GREENWASHER,
        }.get(strategy, PRESCREEN_UPTAKE_ADAPTIVE)
        if mode == PrescreeningParticipationMode.SUBSIDIZED:
            base = _clamp(base * PRESCREEN_UPTAKE_SUBSIDIZED_BOOST)
        elif mode == PrescreeningParticipationMode.AUTO_INVITATION:
            base = max(base, PRESCREEN_UPTAKE_AUTO_INVITE)
        base = _clamp(base * max(0.0, self.parameters.participation_scale))
        return rng.random() < base

    # -- the screening algorithm (Section 4.3 checks) ------------------------ #
    def screen(self, claim: EnvironmentalClaim,
               evidence_by_id: dict[str, EvidenceRecord],
               prior_claims: Iterable[EnvironmentalClaim],
               prior_decisions: Iterable[Any],
               rng: random.Random, day: int) -> PrescreeningFeedback:
        """Rule-based, explainable screening of one draft claim."""
        issues: list[PrescreeningIssue] = []
        strict = _clamp(self.parameters.strictness)
        linked = [evidence_by_id[eid] for eid in claim.evidence_ids
                  if eid in evidence_by_id]
        record = linked[0] if linked else None

        def add(code: str, explanation: str, affected: str, deficiency: str,
                correction: str, qualification: str, confidence: float,
                reference: str, material: bool) -> None:
            issues.append(PrescreeningIssue(
                issue_code=code, explanation=explanation,
                affected_field=affected, evidence_deficiency=deficiency,
                recommended_correction=correction,
                recommended_qualification=qualification,
                confidence=_clamp(confidence), reference=reference,
                legally_material=material))

        # 0. Part I.3 semantic validation: a placeholder qualification
        # ("x", "qualified") satisfies nothing and is itself flagged.
        has_meaningful_qual = meaningful_qualification(claim.qualification)
        if claim.qualification and not has_meaningful_qual:
            add("MEANINGLESS_QUALIFICATION",
                "The qualification is a placeholder: too short or "
                "without any recognised scoping content.",
                "qualification",
                "Qualification does not state boundary, period, method "
                "or uncertainty.",
                "Replace with a substantive qualification naming the "
                "boundary, period and estimation basis.",
                "", 0.8, "UCPD Art. 7 (material information)", True)

        # 1-2. Vague/generic language and unsupported adjectives: a
        # qualitative claim with no meaningful qualification and weak/no
        # evidence.
        if claim.claim_type == ClaimType.QUALITATIVE:
            if not has_meaningful_qual:
                add("VAGUE_GENERIC_LANGUAGE",
                    "Generic environmental wording without recognised "
                    "specification of the underlying performance.",
                    "qualification",
                    "No qualifying statement restricting the claim.",
                    "State the metric, boundary and period the claim "
                    "rests on.",
                    "Add an explicit qualification of scope and basis.",
                    0.85, "Directive (EU) 2024/825, Annex I points",
                    True)
            if record is None or record.confidence < 0.45 + 0.20 * strict:
                add("UNSUPPORTED_ENVIRONMENTAL_ADJECTIVE",
                    "The qualitative assertion is not supported by "
                    "submitted evidence of adequate confidence.",
                    "evidence_ids",
                    "Missing or low-confidence supporting evidence.",
                    "Attach verifiable evidence or withdraw the "
                    "adjective.", "Qualify as an aspiration, not a fact.",
                    0.75, "UCPD Arts 6-7; Directive (EU) 2024/825", True)

        # 3-4. Missing quantitative metrics / units, periods, baselines,
        # boundaries.
        if claim.claim_type != ClaimType.QUALITATIVE:
            if not claim.unit:
                add("MISSING_UNIT",
                    "Quantitative claim carries no measurement unit.",
                    "unit", "Unit absent.",
                    "State the unit of measurement.", "", 0.95,
                    "VSME / Art. 29ca voluntary standard structure", True)
            if claim.period_end < claim.period_start:
                add("INVALID_PERIOD",
                    "Claim period is inverted or missing.", "period_start",
                    "Invalid observation period.",
                    "State the reporting period.", "", 0.95,
                    "VSME basic module", True)
        if claim.claim_type == ClaimType.COMPARATIVE \
                and claim.baseline_value is None:
            add("MISSING_BASELINE",
                "Comparative claim without a disclosed baseline.",
                "baseline_value", "No baseline value.",
                "Disclose the comparator baseline and its period.", "",
                0.9, "Directive (EU) 2024/825 comparative-claim rules",
                True)
        if claim.organizational_boundary not in {
                "consolidated_group", "single_entity"}:
            add("MISSING_BOUNDARY",
                "Organizational boundary is not stated in a recognised "
                "form.", "organizational_boundary",
                "Unclear reporting boundary.",
                "State the organizational boundary.", "", 0.7,
                "VSME basic module", False)

        # 5-6. Whole-company overreach from activity-level evidence and
        # product claims supported only by packaging-style narrow data.
        if record is not None and record.coverage < 0.60 \
                and claim.subject in {ClaimSubject.GREEN_SCORE,
                                      ClaimSubject.NET_ZERO}:
            add("WHOLE_COMPANY_OVERREACH",
                "Company-wide assertion rests on evidence covering only "
                "part of the activities.", "subject",
                f"Evidence coverage {record.coverage:.0%} of activities.",
                "Narrow the claim to the covered activities.",
                "Qualify the covered share of operations.",
                0.8, "Directive (EU) 2024/825; UCPD Art. 6", True)
        if claim.channel == ClaimChannel.PRODUCT_LABEL \
                and record is not None and record.coverage < 0.50:
            add("PRODUCT_CLAIM_PACKAGING_DATA",
                "Product-level claim supported only by narrow "
                "(packaging-level) data.", "channel",
                "Evidence does not cover the product life cycle stage "
                "claimed.",
                "Restrict the claim to the evidenced aspect.",
                "Name the aspect (e.g. packaging) explicitly.",
                0.75, "Directive (EU) 2024/825", True)

        # 7. Missing Scope 3 when material.
        if claim.subject in {ClaimSubject.SCOPE_1_EMISSIONS,
                             ClaimSubject.SCOPE_2_EMISSIONS,
                             ClaimSubject.NET_ZERO} \
                and claim.operational_boundary == "scope_1_2":
            add("MISSING_SCOPE_3",
                "Emissions presentation omits Scope 3 although likely "
                "material.", "operational_boundary",
                "No Scope 3 information in the stated boundary.",
                "Include Scope 3 or state its omission and materiality.",
                "Qualify the boundary as Scope 1-2 only.",
                0.8, "VSME comprehensive module; 2024/825", True)

        # 8. Taxonomy eligibility presented as alignment.
        if claim.subject == ClaimSubject.TAXONOMY_ALIGNMENT:
            eligibility = next(
                (item for item in prior_claims
                 if item.firm_symbol == claim.firm_symbol
                 and item.subject == ClaimSubject.TAXONOMY_ELIGIBILITY
                 and item.period_start == claim.period_start), None)
            if eligibility is not None \
                    and claim.asserted_value > eligibility.asserted_value:
                add("ELIGIBILITY_AS_ALIGNMENT",
                    "Asserted Taxonomy alignment exceeds disclosed "
                    "eligibility.", "asserted_value",
                    "Alignment cannot exceed eligibility.",
                    "Reduce alignment to at most the eligible share.",
                    "Present eligibility and alignment separately.",
                    0.9, "Regulation (EU) 2020/852 Arts 3, 8", True)

        # 9. Offsets not separated from gross emissions.
        if claim.relies_on_offsets and not claim.offset_disclosed_separately:
            add("OFFSETS_NOT_SEPARATED",
                "Offset reliance is not transparently separated from "
                "gross emissions.", "relies_on_offsets",
                "No separate gross/offset presentation.",
                "Report gross emissions and offsets separately.",
                "State the offset share explicitly.",
                0.9, "Directive (EU) 2024/825 offset rules", True)

        # 10-11. Unsupported future targets / missing implementation plan.
        if claim.claim_type == ClaimType.FUTURE_TARGET:
            if claim.target_date is None or claim.baseline_value is None:
                add("UNSUPPORTED_FUTURE_TARGET",
                    "Future environmental target lacks a date or "
                    "baseline.", "target_date",
                    "Missing target date or baseline.",
                    "State the target date and the baseline.",
                    "", 0.85, "Directive (EU) 2024/825", True)
            if not claim.evidence_ids:
                add("MISSING_IMPLEMENTATION_PLAN",
                    "No verifiable implementation-plan data accompany "
                    "the target.", "evidence_ids",
                    "No plan evidence submitted.",
                    "Attach the implementation plan or milestones.",
                    "", 0.8, "Directive (EU) 2024/825", True)

        # 12. Invalid or private sustainability labels.
        if claim.channel == ClaimChannel.PRODUCT_LABEL \
                and (record is None or not record.verified):
            add("UNVERIFIED_LABEL",
                "Sustainability label lacks independent verification or "
                "a recognised scheme.", "channel",
                "No independent verification of the label basis.",
                "Use a certified scheme or remove the label.",
                "", 0.85, "Directive (EU) 2024/825 label rules", True)

        # 13. Conflicting claims across channels.
        for other in prior_claims:
            if (other.firm_symbol == claim.firm_symbol
                    and other.subject == claim.subject
                    and other.claim_id != claim.claim_id
                    and not other.withdrawn
                    and other.period_start == claim.period_start
                    and other.unit == claim.unit):
                scale = max(abs(other.asserted_value), 1.0)
                if abs(claim.asserted_value - other.asserted_value) \
                        / scale > 0.10:
                    add("CROSS_CHANNEL_CONFLICT",
                        "The draft conflicts with another live "
                        "communication on the same metric and period.",
                        "asserted_value",
                        f"Diverges from {other.claim_id}.",
                        "Align the figures or explain the difference.",
                        "State the methodological difference.",
                        0.7, "UCPD Art. 7 (misleading omission)", True)
                    break

        # 14. Stale, incomplete, inconsistent or inaccessible evidence.
        if record is not None:
            if record.staleness_days > 365:
                add("STALE_EVIDENCE",
                    "Supporting evidence is older than one year.",
                    "evidence_ids",
                    f"Evidence is {record.staleness_days} days old.",
                    "Refresh the measurement.",
                    "Qualify the observation period.",
                    0.75, "VSME basic module", False)
            if record.conflict:
                add("CONFLICTING_EVIDENCE",
                    "Submitted evidence conflicts internally.",
                    "evidence_ids", "Conflicting records.",
                    "Resolve the conflict before publishing.",
                    "", 0.7, "UCPD Art. 6", True)
            if not record.accessible_to_regulator:
                add("INACCESSIBLE_EVIDENCE",
                    "Evidence is not accessible for verification.",
                    "evidence_ids", "Evidence not shared.",
                    "Grant access or replace the evidence.",
                    "", 0.7, "Substantiation duty (UCPD Art. 12)", True)

        # 14b. Claim value greener than the firm's OWN submitted evidence
        # by more than twice its standard error. Information-safe: the
        # comparator is the evidence the firm itself provided, never any
        # latent state. This is the hub's main lever against good-faith
        # numeric errors (and it makes deliberate inflation visible
        # before publication, without any power to block it).
        if record is not None \
                and claim.claim_type != ClaimType.FUTURE_TARGET:
            greener_gap = (record.estimate - claim.asserted_value
                           if claim.subject in LOWER_IS_GREENER
                           else claim.asserted_value - record.estimate)
            if greener_gap > 2.0 * max(record.standard_error, 1e-9):
                add("CLAIM_EXCEEDS_OWN_EVIDENCE",
                    "The asserted value is materially greener than the "
                    "firm's own submitted evidence.",
                    "asserted_value",
                    f"Gap of {greener_gap:.4g} vs evidence estimate "
                    f"{record.estimate:.4g} (se "
                    f"{record.standard_error:.4g}).",
                    "Align the figure with the evidence estimate or "
                    "submit stronger evidence.",
                    "State the estimation basis and uncertainty.",
                    0.85, "UCPD Arts 6-7; substantiation duty", True)

        # 15. Excessive uncertainty concealed by unqualified language.
        if record is not None and claim.stated_uncertainty \
                < 0.5 * record.standard_error and not has_meaningful_qual:
            add("CONCEALED_UNCERTAINTY",
                "The stated uncertainty is far below the evidence "
                "uncertainty and the claim is unqualified.",
                "stated_uncertainty",
                "Understated uncertainty.",
                "State the measurement uncertainty.",
                "Qualify the estimate with its uncertainty.",
                0.7, "VSME; UCPD Art. 7", strict > 0.60)

        # 15b. Part I.2 (4.1): MATERIALLY OVERSTATED uncertainty -- the
        # mirror gaming channel. Declaring a sigma far above the
        # evidence-derived error is the standard way to defeat z-tests.
        if record is not None and claim.stated_uncertainty \
                > UNCERTAINTY_PLAUSIBILITY_MULTIPLE \
                * max(record.standard_error, 1e-9):
            add("OVERSTATED_UNCERTAINTY",
                "The self-declared uncertainty is implausibly large "
                "relative to the submitted evidence and would shield the "
                "claim from divergence testing.",
                "stated_uncertainty",
                f"Declared {claim.stated_uncertainty:.3g} vs evidence "
                f"standard error {record.standard_error:.3g}.",
                "Justify the declared uncertainty with methodology "
                "evidence or reduce it to the evidence-derived level.",
                "State the estimation basis for the uncertainty.",
                0.8, "Substantiation duty (UCPD Art. 12); EXPERIMENT "
                "plausibility cap", True)

        # Screening noise: a spurious informational flag with probability
        # `noise` (EXPERIMENT). This models an imperfect algorithm; the
        # spurious issue is never legally material but still burdens the
        # firm -- the channel through which an over-strict or noisy hub
        # increases withdrawal and greenhushing.
        if rng.random() < _clamp(self.parameters.noise):
            add("ALGORITHMIC_FALSE_FLAG",
                "Automated heuristic flagged a pattern that manual "
                "review would likely clear.", "claim_id",
                "None identified on closer inspection.",
                "Review wording against the checklist.",
                "", 0.30, "Hub screening heuristic (EXPERIMENT)", False)

        # Strictness escalation: at high strictness, informational issues
        # are presented as potentially material (EXPERIMENT chilling lever).
        if strict > 0.75:
            issues = [
                PrescreeningIssue(
                    **{**issue.to_dict(), "legally_material": True})
                if not issue.legally_material else issue
                for issue in issues
            ]

        feedback = PrescreeningFeedback(
            claim_id=claim.claim_id, firm_symbol=claim.firm_symbol,
            day=day, issues=tuple(issues),
            processing_delay_days=max(
                0, int(self.parameters.processing_delay_days)))
        self.feedback_log.append(feedback)
        # Recurrence tracking (prevention metric): repeated issue codes.
        seen = self.prior_issue_codes.setdefault(claim.firm_symbol, set())
        for issue in issues:
            if issue.issue_code in seen:
                self.repeat_issue_count += 1
            seen.add(issue.issue_code)
        return feedback

    # -- firm response and ledger -------------------------------------------- #
    def process_firm_claims(self, day: int, asset: Any, strategy: str,
                            claims: list[EnvironmentalClaim],
                            evidence: list[EvidenceRecord],
                            mandatory_csrd: bool,
                            rng: random.Random,
                            state: Any = None) -> tuple[
                                list[EnvironmentalClaim],
                                list[EvidenceRecord]]:
        """Run the draft workflow over one firm's voluntary communications.

        Returns the claims that are actually published (revised in place
        where the firm accepted feedback) and the possibly augmented
        evidence list. Withheld drafts never reach the public claim log,
        the supervisor, consumers or investors.
        """
        params = self.parameters
        composition = self.composition.setdefault(strategy, {
            "eligible_firm_periods": 0, "participating_firm_periods": 0,
            "submissions": 0, "meaningful_revisions": 0,
            "withdrawals": 0, "published_against_advice": 0})
        if not self.is_eligible(asset.workforce.average_employees_365d,
                                mandatory_csrd):
            return claims, evidence
        composition["eligible_firm_periods"] += 1
        if not self.participates(strategy, rng):
            self.declined_participations += 1
            return claims, evidence
        composition["participating_firm_periods"] += 1
        if not self.setup_paid:
            self._book_state_cost(params.state_setup_cost_dec, state)
            self.setup_paid = True

        evidence_by_id = {record.evidence_id: record for record in evidence}
        for record in asset.evidence_history:
            evidence_by_id.setdefault(record.evidence_id, record)
        published: list[EnvironmentalClaim] = []
        prior_claims = list(asset.claim_history) + list(claims)
        prior_decisions = list(asset.public_environmental_signals)

        for claim in claims:
            # Mandatory-report channels are outside the hub (it serves
            # voluntary communications); pass them straight through.
            if claim.channel == ClaimChannel.SUSTAINABILITY_REPORT \
                    and mandatory_csrd:
                published.append(claim)
                continue
            trace = [DraftClaimState.DRAFT.value,
                     DraftClaimState.SUBMITTED_TO_PRESCREENING.value]
            self.submissions += 1
            composition["submissions"] += 1
            draft_value = claim.asserted_value
            submission_cost = params.firm_cost_per_submission_dec
            state_cost = params.state_cost_per_submission_dec
            if params.participation_mode \
                    == PrescreeningParticipationMode.SUBSIDIZED:
                state_cost += submission_cost
                submission_cost = _ZERO
            self._book_state_cost(state_cost, state)
            firm_cost = self._book_firm_cost(asset, submission_cost)

            feedback = self.screen(claim, evidence_by_id, prior_claims,
                                   prior_decisions, rng, day)
            trace.append(DraftClaimState.AUTOMATED_FEEDBACK.value)
            action, revision_cost = self._respond(
                claim, feedback, strategy, asset, evidence,
                evidence_by_id, rng)
            trace.append(DraftClaimState.FIRM_REVISION_OR_REJECTION.value)
            trace.append(DraftClaimState.PUBLISHED_OR_WITHHELD.value)
            firm_cost += self._book_firm_cost(asset, revision_cost)
            spurious_only = bool(feedback.issues) \
                and not feedback.materially_flagged

            if action != "withdrawn":
                # Part I.5 -- OPERATIONAL processing delay: a submitted
                # draft cannot become public before its review outcome is
                # available. The Simulation withholds the claim from
                # consumers, investors and the supervisor until
                # `review_day` (previously the delay was metadata only).
                claim.review_day = day + feedback.processing_delay_days
                published.append(claim)
                if not feedback.materially_flagged:
                    self.cleanly_prescreened.add(claim.claim_id)
            else:
                claim.record_withdrawal(day)
                self.withdrawals += 1
                composition["withdrawals"] += 1
                # A withheld voluntary claim reduces the firm's visible
                # communication footprint: the greenhushing gap grows by
                # one optional-claim slot (the communications policy emits
                # up to 7 optional claims at benchmark intensity).
                benchmark = max(0.0, asset.q_truthful_benchmark)
                if benchmark > 0.0:
                    asset.greenhushing_gap = _clamp(
                        asset.greenhushing_gap + benchmark / 7.0,
                        0.0, benchmark)
            if action == "revised":
                self.revisions += 1
                # Part I.5 -- honest prevention accounting: only a
                # response to a legally material issue counts.
                if feedback.materially_flagged:
                    self.meaningful_revisions += 1
                    composition["meaningful_revisions"] += 1
            elif action == "published_against_advice":
                self.published_against_advice += 1
                composition["published_against_advice"] += 1
            elif action == "published_clean":
                self.published_clean += 1
            if spurious_only:
                self.noise_flag_events += 1

            self._event_sequence += 1
            self.events.append(PrescreeningEvent(
                event_id=f"PS-{day}-{self._event_sequence}",
                day=day, firm_symbol=claim.firm_symbol,
                claim_id=claim.claim_id, subject=claim.subject.value,
                channel=claim.channel.value,
                participation_mode=params.participation_mode.value,
                state_trace=tuple(trace),
                issues_total=len(feedback.issues),
                issues_material=sum(issue.legally_material
                                    for issue in feedback.issues),
                issue_codes=tuple(issue.issue_code
                                  for issue in feedback.issues),
                action=action, firm_cost=float(firm_cost),
                state_cost=float(state_cost),
                processing_delay_days=feedback.processing_delay_days,
                draft_value=draft_value,
                published_value=(claim.asserted_value
                                 if action != "withdrawn" else None),
                spurious_only=spurious_only))
        return published, evidence

    def _respond(self, claim: EnvironmentalClaim,
                 feedback: PrescreeningFeedback, strategy: str, asset: Any,
                 evidence: list[EvidenceRecord],
                 evidence_by_id: dict[str, EvidenceRecord],
                 rng: random.Random) -> tuple[str, Decimal]:
        """The firm's decision: accept / improve evidence / quantify /
        qualify / narrow / withdraw / publish anyway. EXPERIMENT model."""
        issues = feedback.issues
        material = [issue for issue in issues if issue.legally_material]
        # Part I.5 -- purely informational or spurious flags never force
        # a value rewrite: the firm publishes unchanged (the flags still
        # burden it psychologically only through the strictness channel,
        # which escalates informational issues to material above 0.75).
        if not material:
            return "published_clean", _ZERO
        strict = _clamp(self.parameters.strictness)
        # Perceived compliance burden grows with every flag, including
        # spurious ones; withdrawal (greenhushing) grows with burden.
        burden = (0.05 + 0.10 * strict) * len(issues)
        revise_propensity = {
            "honest": 0.90, "adaptive": 0.70, "greenwasher": 0.30,
        }.get(strategy, 0.60)
        withdraw_probability = _clamp(
            burden * {"honest": 0.45, "adaptive": 0.55,
                      "greenwasher": 0.35}.get(strategy, 0.5))
        roll = rng.random()
        if roll < withdraw_probability:
            return "withdrawn", _ZERO
        if rng.random() > revise_propensity:
            return "published_against_advice", _ZERO
        # Accepted: apply the recommended corrections to the draft.
        record = next((evidence_by_id[eid] for eid in claim.evidence_ids
                       if eid in evidence_by_id), None)
        if record is not None:
            # Quantify / correct toward the firm's own submitted evidence
            # (the hub knows nothing truer than that).
            claim.asserted_value = record.estimate
            claim.stated_uncertainty = max(claim.stated_uncertainty,
                                           record.standard_error)
        codes = {issue.issue_code for issue in issues}
        if {"VAGUE_GENERIC_LANGUAGE", "CONCEALED_UNCERTAINTY",
                "UNSUPPORTED_ENVIRONMENTAL_ADJECTIVE"} & codes \
                or not claim.qualification:
            claim.qualification = (claim.qualification or "") + (
                " Revised after non-binding pre-screening feedback: "
                "estimate limited to the stated period, boundary and "
                "uncertainty.")
            claim.qualification_prominence = max(
                claim.qualification_prominence, 0.8)
        if "MISSING_SCOPE_3" in codes:
            claim.operational_boundary = "scope_1_2_3"
        if "OFFSETS_NOT_SEPARATED" in codes:
            claim.offset_disclosed_separately = True
        if "ELIGIBILITY_AS_ALIGNMENT" in codes:
            eligibility = next(
                (item for item in asset.claim_history
                 if item.subject == ClaimSubject.TAXONOMY_ELIGIBILITY
                 and item.period_start == claim.period_start), None)
            if eligibility is not None:
                claim.asserted_value = min(claim.asserted_value,
                                           eligibility.asserted_value)
        return "revised", self.parameters.firm_revision_cost_dec

    # -- cost booking ---------------------------------------------------------#
    def _book_state_cost(self, amount_dec: Decimal, state: Any) -> None:
        if amount_dec <= _ZERO:
            return
        self.state_cost_dec += amount_dec
        if state is not None:
            state.pay_policy_cost(amount_dec)

    def _book_firm_cost(self, asset: Any, amount_dec: Decimal) -> Decimal:
        if amount_dec <= _ZERO:
            return _ZERO
        headroom = max(0.0, asset.balance - CORPORATE_BALANCE_FLOOR)
        payable = min(float(amount_dec), headroom)
        if payable > 0.0:
            asset.balance -= payable
        paid = _dec_cents(payable)
        self.firm_cost_dec[asset.symbol] = self.firm_cost_dec.get(
            asset.symbol, _ZERO) + paid
        return paid


# --------------------------------------------------------------------------- #
# Regime C: certified public green data connector
# --------------------------------------------------------------------------- #
class ConnectorAuthorizationState(str, Enum):
    NOT_CONNECTED = "not_connected"
    CONSENT_REQUESTED = "consent_requested"
    AUTHORIZED = "authorized"
    ACTIVE = "active"
    SUSPENDED_OR_REVOKED = "suspended_or_revoked"


class DataSourceKind(str, Enum):
    ELECTRICITY_GRID = "electricity_grid_operator"
    GAS_HEAT_SUPPLIER = "gas_heat_supplier"
    REC_REGISTRY = "renewable_certificate_registry"
    WATER_AUTHORITY = "water_authority"
    WASTE_REGISTRY = "waste_management_registry"
    POLLUTION_REGISTER = "pollution_incident_register"
    EMISSIONS_FACTOR_DB = "public_emissions_factor_database"
    PERMIT_REGISTER = "environmental_permit_register"
    TRANSPORT_DATASET = "verified_transport_dataset"
    OTHER_PUBLIC = "other_authorized_public_source"


@dataclass(frozen=True)
class ConnectorSource:
    """Static metadata of one certified data source (Section 5.1)."""

    kind: DataSourceKind
    institution: str
    subject: ClaimSubject
    unit: str
    update_frequency_days: int
    methodology_version: str
    base_relative_uncertainty: float
    coverage: float                      # Share of the metric it observes.
    emissions_factor: Optional[float] = None
    certified: bool = True

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["kind"] = self.kind.value
        result["subject"] = self.subject.value
        return result


# Default configurable source set. Coverage below 1.0 encodes the
# incomplete observability of each register (Scope 3 in particular).
DEFAULT_CONNECTOR_SOURCES: tuple[ConnectorSource, ...] = (
    ConnectorSource(DataSourceKind.ELECTRICITY_GRID, "TSO/DSO metering",
                    ClaimSubject.SCOPE_2_EMISSIONS, "tCO2e", 30,
                    "grid_meter_v2", CONNECTOR_METER_RELATIVE_ERROR, 0.95,
                    emissions_factor=0.23),
    ConnectorSource(DataSourceKind.GAS_HEAT_SUPPLIER, "Gas/heat supplier",
                    ClaimSubject.SCOPE_1_EMISSIONS, "tCO2e", 30,
                    "fuel_billing_v1", 0.015, 0.85, emissions_factor=0.20),
    ConnectorSource(DataSourceKind.REC_REGISTRY,
                    "Renewable-certificate registry",
                    ClaimSubject.RENEWABLE_ENERGY_SHARE, "share_0_1", 90,
                    "rec_cancellation_v1", 0.008, 0.90),
    ConnectorSource(DataSourceKind.WATER_AUTHORITY, "Water authority",
                    ClaimSubject.WATER_INTENSITY, "intensity_0_1", 90,
                    "abstraction_meter_v1", 0.02, 0.80),
    ConnectorSource(DataSourceKind.WASTE_REGISTRY,
                    "Waste-management registry",
                    ClaimSubject.RECYCLING_RATE, "share_0_1", 90,
                    "waste_manifest_v1", 0.03, 0.75),
    ConnectorSource(DataSourceKind.POLLUTION_REGISTER,
                    "Pollution/incident register",
                    ClaimSubject.POLLUTION_INTENSITY, "intensity_0_1", 120,
                    "eprtr_style_v1", 0.04, 0.70),
    ConnectorSource(DataSourceKind.TRANSPORT_DATASET,
                    "Verified transport dataset",
                    ClaimSubject.SCOPE_3_EMISSIONS, "tCO2e", 90,
                    "logistics_v1", 0.06, 0.45),   # Deliberately partial.
    ConnectorSource(DataSourceKind.PERMIT_REGISTER,
                    "Environmental permit register",
                    ClaimSubject.ENVIRONMENTAL_CAPEX, "EUR", 180,
                    "permit_capex_v1", 0.05, 0.65),
)

# Subjects the connector may populate. It must NEVER auto-validate
# whole-company scores, Taxonomy legal classification, net zero, offsets
# or future performance (Section 5.4).
CONNECTOR_POPULATABLE_SUBJECTS = frozenset(
    source.subject for source in DEFAULT_CONNECTOR_SOURCES)
CONNECTOR_FORBIDDEN_SUBJECTS = frozenset({
    ClaimSubject.GREEN_SCORE, ClaimSubject.TAXONOMY_ELIGIBILITY,
    ClaimSubject.TAXONOMY_ALIGNMENT, ClaimSubject.NET_ZERO,
    ClaimSubject.OFFSETS,
})


@dataclass
class ConnectorProvenanceRecord:
    """Tamper-evident provenance of one automated transfer."""

    transfer_id: str
    day: int
    firm_symbol: str
    source_kind: str
    source_institution: str
    subject: str
    metric_unit: str
    estimate: float
    relative_uncertainty: float
    coverage: float
    observation_period_start: str
    observation_period_end: str
    methodology_version: str
    emissions_factor: Optional[float]
    integrity_hash: str
    integrity_ok: bool
    authorization_state: str
    staleness_days: int
    register_error: bool          # Known only after correction (research).
    correction_due_day: Optional[int]
    completeness: float
    corrects_transfer_id: Optional[str] = None   # Part I.6 correction link.

    def payload(self) -> str:
        """Canonical payload over which the integrity hash is computed.
        Any tampering with the stored estimate, methodology, institution
        or day breaks hash verification (Part I.6)."""
        return (f"{self.transfer_id}|{self.methodology_version}|"
                f"{self.estimate:.9f}|{self.source_institution}|{self.day}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReconciliationClass(str, Enum):
    MATCHED = "matched"
    ROUNDING_NOISE = "rounding_or_immaterial_noise"
    METHODOLOGY_EXPLAINED = "explainable_methodological_difference"
    INCOMPLETE_COVERAGE = "incomplete_connector_coverage"
    SOURCE_CONFLICT = "source_conflict"
    CORRECTION_REQUIRED = "correction_required"
    SUSPICIOUS_OVERRIDE = "suspicious_manual_override"
    MATERIAL_OVERSTATEMENT = "material_calculation_overstatement"
    REPEATED_MANIPULATION = "repeated_data_manipulation"


@dataclass
class ReconciliationFinding:
    finding_id: str
    day: int
    firm_symbol: str
    claim_id: str
    subject: str
    firm_value: float
    connector_value: Optional[float]
    other_evidence_value: Optional[float]
    absolute_divergence: float
    relative_divergence: float
    standardized_divergence: float
    coverage_adjusted_divergence: float
    methodology_mismatch: bool
    unit_mismatch: bool
    boundary_mismatch: bool
    staleness_days: int
    confidence: float
    unexplained_manual_adjustment: bool
    classification: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConnectorParameters:
    """EXPERIMENT configuration of the proposed public infrastructure."""

    sources: tuple[ConnectorSource, ...] = DEFAULT_CONNECTOR_SOURCES
    auto_populate_reports: bool = True
    meter_relative_error: float = CONNECTOR_METER_RELATIVE_ERROR
    mismatch_probability: float = CONNECTOR_MISMATCH_PROBABILITY
    mismatch_bias: float = CONNECTOR_MISMATCH_BIAS
    stale_probability: float = CONNECTOR_STALE_PROBABILITY
    stale_days: int = CONNECTOR_STALE_DAYS
    register_error_probability: float = CONNECTOR_REGISTER_ERROR_PROBABILITY
    correction_delay_days: int = CONNECTOR_CORRECTION_DELAY_DAYS
    downtime_probability: float = CONNECTOR_DOWNTIME_PROBABILITY
    cyber_incident_probability: float = CONNECTOR_CYBER_INCIDENT_PROBABILITY
    state_setup_cost_dec: Decimal = CONNECTOR_STATE_SETUP_COST_DEC
    state_daily_operating_dec: Decimal = CONNECTOR_STATE_DAILY_OPERATING_DEC
    cyber_governance_daily_dec: Decimal = CONNECTOR_CYBER_GOVERNANCE_DAILY_DEC
    firm_integration_cost_dec: Decimal = CONNECTOR_FIRM_INTEGRATION_COST_DEC
    # Part J sensitivity lever (EXPERIMENT; default preserves behaviour):
    # scales every source's observational coverage (clamped to
    # [0.05, 1.0]) so the campaign can test how much of the connector's
    # effect depends on how much of each metric the registers observe.
    coverage_scale: float = 1.0

    def effective_coverage(self, source: "ConnectorSource") -> float:
        return min(1.0, max(0.05, source.coverage
                            * max(0.0, self.coverage_scale)))


class CertifiedGreenDataConnector:
    """Public green data infrastructure with authorization, provenance,
    automatic report population and reconciliation (Sections 5.1-5.5).

    Privacy and access control: connector evidence is marked accessible to
    the regulator and (aggregated) to investors via the normal evidence
    accessibility flags; raw source records are never exposed to
    consumers, competitors or other firms. Consent can be withdrawn
    (SUSPENDED_OR_REVOKED) and every transfer is audit-logged.
    """

    def __init__(self, parameters: Optional[ConnectorParameters] = None):
        self.parameters = parameters or ConnectorParameters()
        # (firm, source-kind) -> authorization state machine.
        self.authorizations: dict[tuple[str, str], str] = {}
        self.provenance: list[ConnectorProvenanceRecord] = []
        self.findings: list[ReconciliationFinding] = []
        self._transfer_sequence = 0
        self._finding_sequence = 0
        self.setup_paid = False
        self.state_cost_dec = _ZERO
        self.firm_cost_dec: dict[str, Decimal] = {}
        self.cyber_incidents = 0
        self.downtime_events = 0
        self.transfers = 0
        self.manual_overrides: dict[str, int] = {}
        self.selective_connection_flags: set[str] = set()
        # Part I.6 -- register errors awaiting correction:
        # (firm, subject) -> {"due", "transfer_id", "kind"}. Consumed by
        # `process_corrections`, which issues a superseding record after
        # the correction delay (prospective only: no historical decision
        # is rewritten).
        self._pending_corrections: dict[tuple[str, str], dict] = {}
        self.corrections_issued = 0
        # Part I.6 -- tampering detection state (hashes are now VERIFIED,
        # not merely stored): transfer ids failing verification.
        self.tampered_transfer_ids: set[str] = set()
        # Part I.6 -- measurement history for MEANINGFUL staleness: a
        # stale read returns a genuinely old measured value when one
        # exists ((firm, subject) -> list[(day, measured_value)]).
        self._measurement_history: dict[tuple[str, str], list] = {}

    # -- authorization lifecycle --------------------------------------------- #
    def authorization_state(self, firm: str, kind: DataSourceKind) -> str:
        return self.authorizations.get(
            (firm, kind.value), ConnectorAuthorizationState.NOT_CONNECTED.value)

    def onboard_firm(self, asset: Any, strategy: str, rng: random.Random,
                     state: Any = None) -> None:
        """One-time consent workflow per firm.

        Data minimization: the firm authorizes per source, not wholesale.
        Greenwashers connect less and selectively (favourable sources
        only); an authorized share below CONNECTOR_SELECTIVE_THRESHOLD is
        flagged as detectable selective connection.
        """
        firm = asset.symbol
        if any(key[0] == firm for key in self.authorizations):
            return
        if not self.setup_paid:
            self._book_state_cost(self.parameters.state_setup_cost_dec,
                                  state)
            self.setup_paid = True
        uptake = {
            "honest": CONNECTOR_UPTAKE_HONEST,
            "adaptive": CONNECTOR_UPTAKE_ADAPTIVE,
            "greenwasher": CONNECTOR_UPTAKE_GREENWASHER,
        }.get(strategy, CONNECTOR_UPTAKE_ADAPTIVE)
        authorized_any = False
        active = 0
        for source in self.parameters.sources:
            key = (firm, source.kind.value)
            self.authorizations[key] = \
                ConnectorAuthorizationState.CONSENT_REQUESTED.value
            if rng.random() < uptake:
                self.authorizations[key] = \
                    ConnectorAuthorizationState.ACTIVE.value
                authorized_any = True
                active += 1
            else:
                self.authorizations[key] = \
                    ConnectorAuthorizationState.NOT_CONNECTED.value
        if authorized_any:
            self._book_firm_cost(
                asset, self.parameters.firm_integration_cost_dec)
        share = active / max(1, len(self.parameters.sources))
        if authorized_any and share < CONNECTOR_SELECTIVE_THRESHOLD:
            # Detectable pattern: the firm connected only a favourable
            # subset of available certified sources.
            self.selective_connection_flags.add(firm)

    def revoke(self, firm: str, kind: DataSourceKind) -> None:
        """Consent withdrawal (GDPR-style); historical provenance stays."""
        self.authorizations[(firm, kind.value)] = \
            ConnectorAuthorizationState.SUSPENDED_OR_REVOKED.value

    def active_sources(self, firm: str) -> int:
        return sum(1 for (f, _k), status in self.authorizations.items()
                   if f == firm
                   and status == ConnectorAuthorizationState.ACTIVE.value)

    # -- automated transfer (the measurement channel) -------------------------- #
    def transfer_period(self, day: int, on_date: date, asset: Any,
                        rng: random.Random,
                        state: Any = None) -> list[EvidenceRecord]:
        """Generate connector evidence for every ACTIVE source of a firm.

        The physical ledger is observed THROUGH an error model -- this is
        a simulated meter, not privileged truth access: strictly positive
        uncertainty, facility-mismatch bias, staleness, register errors
        with delayed corrections, downtime and cyber incidents.
        """
        params = self.parameters
        records: list[EvidenceRecord] = []
        facts = asset.environmental_facts
        period_start = facts.period_start
        period_end = facts.period_end
        for source in params.sources:
            key = (asset.symbol, source.kind.value)
            if self.authorizations.get(key) \
                    != ConnectorAuthorizationState.ACTIVE.value:
                continue
            if rng.random() < params.cyber_incident_probability:
                self.cyber_incidents += 1
                self.authorizations[key] = \
                    ConnectorAuthorizationState.SUSPENDED_OR_REVOKED.value
                continue
            if rng.random() < params.downtime_probability:
                self.downtime_events += 1
                continue
            truth = facts.value_for(source.subject)
            scale = max(abs(truth), 1e-6)
            relative_error = max(1e-4, source.base_relative_uncertainty)
            estimate = truth + rng.gauss(0.0, scale * relative_error)
            staleness = 0
            history_key = (asset.symbol, source.subject.value)
            if rng.random() < params.stale_probability:
                # Part I.6 -- MEANINGFUL staleness: return a genuinely old
                # measured value where the register holds one (its own
                # prior reading closest to `stale_days` ago). Only when no
                # history exists yet does the model fall back to a
                # drift-noised current reading (documented approximation).
                staleness = params.stale_days
                target_day = day - params.stale_days
                history = self._measurement_history.get(history_key, [])
                if history:
                    estimate = min(
                        history,
                        key=lambda item: abs(item[0] - target_day))[1]
                else:
                    estimate = truth * (1.0 + rng.gauss(0.0, 0.05))
            register_error = False
            correction_due: Optional[int] = None
            if rng.random() < params.mismatch_probability:
                # Wrong firm/facility matching: biased reading.
                estimate *= (1.0 + rng.choice((-1.0, 1.0))
                             * params.mismatch_bias)
                register_error = True
            elif rng.random() < params.register_error_probability:
                estimate *= (1.0 + rng.gauss(0.0, 0.10))
                register_error = True
            if source.unit in {"share_0_1", "intensity_0_1"}:
                estimate = _clamp(estimate)
            else:
                estimate = max(0.0, estimate)
            if not register_error and staleness == 0:
                history = self._measurement_history.setdefault(
                    history_key, [])
                history.append((day, estimate))
                if len(history) > 24:
                    del history[0]

            self._transfer_sequence += 1
            transfer_id = (f"GDC-{asset.symbol}-{day}"
                           f"-{self._transfer_sequence}")
            if register_error:
                correction_due = day + params.correction_delay_days
                self._pending_corrections[history_key] = {
                    "due": correction_due, "transfer_id": transfer_id,
                    "kind": source.kind.value}
            payload = (f"{transfer_id}|{source.methodology_version}|"
                       f"{estimate:.9f}|{source.institution}|{day}")
            integrity_hash = hashlib.sha256(payload.encode()).hexdigest()
            record = EvidenceRecord(
                evidence_id=transfer_id,
                firm_symbol=asset.symbol,
                subject=source.subject,
                period_start=period_start,
                period_end=period_end,
                estimate=estimate,
                standard_error=max(scale * relative_error, 1e-9),
                source=EvidenceSource.CERTIFIED_PUBLIC_CONNECTOR,
                coverage=params.effective_coverage(source),
                independence=0.95,
                verified=source.certified,
                notes=(f"Automated transfer from {source.institution} "
                       f"({source.methodology_version}); certified public "
                       "source, uncertainty and coverage limits apply."),
                reliability_prior=0.92,
                staleness_days=staleness,
                observation_method="certified_metered_transfer",
                accessible_to_regulator=True,
                accessible_to_investors=True,
                accessible_to_consumers=False,   # Confidentiality: raw
                accessible_to_employees=False,   # source data stay closed.
            )
            records.append(record)
            self.transfers += 1
            self.provenance.append(ConnectorProvenanceRecord(
                transfer_id=transfer_id, day=day,
                firm_symbol=asset.symbol,
                source_kind=source.kind.value,
                source_institution=source.institution,
                subject=source.subject.value, metric_unit=source.unit,
                estimate=estimate,
                relative_uncertainty=relative_error,
                coverage=params.effective_coverage(source),
                observation_period_start=period_start.isoformat(),
                observation_period_end=period_end.isoformat(),
                methodology_version=source.methodology_version,
                emissions_factor=source.emissions_factor,
                integrity_hash=integrity_hash, integrity_ok=True,
                authorization_state=self.authorizations[key],
                staleness_days=staleness, register_error=register_error,
                correction_due_day=correction_due,
                completeness=params.effective_coverage(source)))
        return records

    def book_period_operating(self, period_days: int,
                              state: Any = None) -> None:
        """Books the infrastructure operating + cyber-governance cost for
        one reporting period. Called ONCE per period by the Simulation --
        running the connector is a central service, not a per-firm fee."""
        operating = (self.parameters.state_daily_operating_dec
                     + self.parameters.cyber_governance_daily_dec) \
            * Decimal(max(1, int(period_days)))
        self._book_state_cost(operating.quantize(CREDIT_CENT_DEC), state)

    # -- Part I.6: tamper-evidence is now VERIFIED, not just stored ------------ #
    def verify_provenance(self) -> set[str]:
        """
        Recomputes every provenance record's integrity hash against its
        canonical payload and marks failures. Returns the set of tampered
        transfer ids; reconciliation excludes tampered records and never
        lets them support or trigger any finding.
        """
        tampered: set[str] = set()
        for record in self.provenance:
            expected = hashlib.sha256(
                record.payload().encode()).hexdigest()
            record.integrity_ok = expected == record.integrity_hash
            if not record.integrity_ok:
                tampered.add(record.transfer_id)
        self.tampered_transfer_ids = tampered
        return tampered

    # -- Part I.6: register-error correction lifecycle ------------------------- #
    def process_corrections(self, day: int, assets: dict,
                            rng: random.Random) -> list[EvidenceRecord]:
        """
        Issues superseding records for register errors whose correction
        delay has elapsed. Prospective only: the corrected record carries
        `corrects_transfer_id` provenance and enters FUTURE evidence
        batches; no historical decision or record is rewritten. Firms are
        never sanctioned on the strength of the erroneous record alone in
        the meantime (unresolved cross-source conflicts route to
        INCONCLUSIVE in the rule engine, Part I.2/4.4).
        """
        corrected: list[EvidenceRecord] = []
        due_keys = [key for key, info in self._pending_corrections.items()
                    if info["due"] <= day]
        for key in due_keys:
            info = self._pending_corrections.pop(key)
            firm, subject_value = key
            asset = assets.get(firm)
            if asset is None:
                continue
            source = next((item for item in self.parameters.sources
                           if item.kind.value == info["kind"]), None)
            if source is None:
                continue
            facts = asset.environmental_facts
            truth = facts.value_for(source.subject)
            scale = max(abs(truth), 1e-6)
            relative_error = max(1e-4, source.base_relative_uncertainty)
            estimate = truth + rng.gauss(0.0, scale * relative_error)
            if source.unit in {"share_0_1", "intensity_0_1"}:
                estimate = _clamp(estimate)
            else:
                estimate = max(0.0, estimate)
            self._transfer_sequence += 1
            transfer_id = (f"GDC-{firm}-{day}-{self._transfer_sequence}")
            payload = (f"{transfer_id}|{source.methodology_version}|"
                       f"{estimate:.9f}|{source.institution}|{day}")
            record = EvidenceRecord(
                evidence_id=transfer_id, firm_symbol=firm,
                subject=source.subject,
                period_start=facts.period_start,
                period_end=facts.period_end,
                estimate=estimate,
                standard_error=max(scale * relative_error, 1e-9),
                source=EvidenceSource.CERTIFIED_PUBLIC_CONNECTOR,
                coverage=self.parameters.effective_coverage(source),
                independence=0.95,
                verified=source.certified,
                notes=(f"Register correction superseding "
                       f"{info['transfer_id']} after the source-error "
                       "dispute; prospective effect only."),
                reliability_prior=0.92,
                observation_method="certified_metered_transfer",
                accessible_to_regulator=True,
                accessible_to_investors=True)
            corrected.append(record)
            self.corrections_issued += 1
            self.transfers += 1
            self.provenance.append(ConnectorProvenanceRecord(
                transfer_id=transfer_id, day=day, firm_symbol=firm,
                source_kind=source.kind.value,
                source_institution=source.institution,
                subject=source.subject.value, metric_unit=source.unit,
                estimate=estimate, relative_uncertainty=relative_error,
                coverage=self.parameters.effective_coverage(source),
                observation_period_start=facts.period_start.isoformat(),
                observation_period_end=facts.period_end.isoformat(),
                methodology_version=source.methodology_version,
                emissions_factor=source.emissions_factor,
                integrity_hash=hashlib.sha256(
                    payload.encode()).hexdigest(),
                integrity_ok=True,
                authorization_state=self.authorizations.get(
                    (firm, source.kind.value),
                    ConnectorAuthorizationState.ACTIVE.value),
                staleness_days=0, register_error=False,
                correction_due_day=None,
                completeness=self.parameters.effective_coverage(source),
                corrects_transfer_id=info["transfer_id"]))
            history = self._measurement_history.setdefault(key, [])
            history.append((day, estimate))
        return corrected

    # -- Part J (Workstream C): supervisory re-verification request ------------ #
    def request_verification(self, firm_symbol: str, subject: Any,
                             day: int) -> bool:
        """The supervisor asks the register to re-measure a disputed
        metric. Returns True when a covering ACTIVE source exists; the
        superseding record then arrives through the ordinary
        `process_corrections` lifecycle after the correction delay --
        prospective effect only, exactly like a register-error dispute.
        """
        subject_value = getattr(subject, "value", str(subject))
        for source in self.parameters.sources:
            if source.subject.value != subject_value:
                continue
            key = (firm_symbol, source.kind.value)
            if self.authorizations.get(key) \
                    != ConnectorAuthorizationState.ACTIVE.value:
                continue
            history_key = (firm_symbol, subject_value)
            pending = self._pending_corrections.get(history_key)
            if pending is None:
                last_transfer = next(
                    (record.transfer_id
                     for record in reversed(self.provenance)
                     if record.firm_symbol == firm_symbol
                     and record.subject == subject_value), "")
                self._pending_corrections[history_key] = {
                    "due": day + self.parameters.correction_delay_days,
                    "transfer_id": last_transfer,
                    "kind": source.kind.value}
            return True
        return False

    # -- automatic report population ------------------------------------------ #
    def auto_populate(self, claims: list[EnvironmentalClaim],
                      connector_records: list[EvidenceRecord],
                      strategy: str, rng: random.Random) -> int:
        """Populate covered report metrics from authorized data.

        Only quantitative claims on populatable subjects are touched;
        estimates, offsets, targets, Taxonomy classifications and
        qualitative claims stay separate (Section 5.4). A greenwasher may
        keep its manual figure (a detectable override) -- the connector
        reduces calculation greenwashing but never validates it away.
        Returns the number of populated claims.
        """
        if not self.parameters.auto_populate_reports:
            return 0
        by_subject = {record.subject: record
                      for record in connector_records}
        populated = 0
        for claim in claims:
            if claim.subject in CONNECTOR_FORBIDDEN_SUBJECTS \
                    or claim.subject not in by_subject \
                    or claim.claim_type not in {ClaimType.QUANTITATIVE,
                                                ClaimType.COMPARATIVE}:
                continue
            if claim.channel != ClaimChannel.SUSTAINABILITY_REPORT \
                    and claim.channel != ClaimChannel.INVESTOR_COMMUNICATION:
                continue
            record = by_subject[claim.subject]
            override_probability = {
                "honest": 0.02, "adaptive": 0.15, "greenwasher": 0.45,
            }.get(strategy, 0.10)
            if rng.random() < override_probability:
                # Manual override kept: separate, detectable, counted.
                self.manual_overrides[claim.firm_symbol] = \
                    self.manual_overrides.get(claim.firm_symbol, 0) + 1
                claim.evidence_ids = tuple(claim.evidence_ids) \
                    + (record.evidence_id,)
                continue
            claim.asserted_value = record.estimate
            claim.stated_uncertainty = max(claim.stated_uncertainty,
                                           record.standard_error)
            claim.evidence_ids = tuple(claim.evidence_ids) \
                + (record.evidence_id,)
            populated += 1
        return populated

    # -- reconciliation engine (Section 5.5) ------------------------------------#
    def reconcile(self, day: int, claims: list[EnvironmentalClaim],
                  connector_records: list[EvidenceRecord],
                  other_evidence: list[EvidenceRecord]) \
            -> tuple[list[ReconciliationFinding], set[str]]:
        """Compare firm-reported values against connector and other
        evidence. NO sanction follows from any classification here:
        material classes only receive screening priority in the existing
        procedurally fair supervision system (returned as claim-id flags).
        """
        # Part I.6: hashes are verified before any record can support a
        # finding; tampered records are excluded outright.
        tampered = self.verify_provenance()
        by_firm_subject: dict[tuple[str, str], EvidenceRecord] = {}
        for record in connector_records:
            if record.evidence_id in tampered:
                continue
            by_firm_subject[(record.firm_symbol,
                             record.subject.value)] = record
        unit_by_subject = {source.subject.value: source.unit
                           for source in self.parameters.sources}
        other_by_firm_subject: dict[tuple[str, str], EvidenceRecord] = {}
        for record in other_evidence:
            key = (record.firm_symbol, record.subject.value)
            existing = other_by_firm_subject.get(key)
            if existing is None or record.confidence > existing.confidence:
                other_by_firm_subject[key] = record

        flags: set[str] = set()
        new_findings: list[ReconciliationFinding] = []
        for claim in claims:
            key = (claim.firm_symbol, claim.subject.value)
            record = by_firm_subject.get(key)
            if record is None:
                continue
            other = other_by_firm_subject.get(key)
            divergence = claim.asserted_value - record.estimate
            greener = -divergence if claim.subject in LOWER_IS_GREENER \
                else divergence
            scale = max(abs(record.estimate), 1.0)
            relative = abs(divergence) / scale
            combined_error = max(1e-9, (record.standard_error ** 2
                                        + claim.stated_uncertainty ** 2)
                                 ** 0.5)
            z_score = max(0.0, greener) / combined_error
            # Part I.6 -- coverage-ADJUSTED inference (red-team C1): low
            # coverage widens the effective uncertainty (dividing the
            # error by coverage), it never immunizes. A divergence that
            # stays suspicious even under the widened error produces a
            # targeted-investigation state instead of a clean pass.
            coverage_adjusted = max(0.0, greener) / (
                combined_error / max(record.coverage, 0.05))
            source_unit = unit_by_subject.get(claim.subject.value)
            unit_mismatch = (source_unit is not None
                             and claim.unit != source_unit)
            boundary_mismatch = claim.operational_boundary not in {
                "scope_1_2_3", "consolidated_group"}
            methodology_mismatch = boundary_mismatch \
                or claim.organizational_boundary != "consolidated_group"
            override = record.evidence_id in claim.evidence_ids \
                and abs(divergence) > combined_error
            confidence = record.confidence

            if unit_mismatch:
                # No conversion evidence exists in-model: a unit mismatch
                # blocks numerical comparison and is reported as a
                # methodological difference (documented limitation).
                classification = ReconciliationClass.METHODOLOGY_EXPLAINED
            elif record.coverage < 0.60:
                classification = (
                    ReconciliationClass.CORRECTION_REQUIRED
                    if coverage_adjusted >= RECONCILE_SUSPICIOUS_Z
                    else ReconciliationClass.INCOMPLETE_COVERAGE)
            elif other is not None and abs(
                    other.estimate - record.estimate) \
                    > 2.0 * max(other.standard_error,
                                record.standard_error):
                classification = ReconciliationClass.SOURCE_CONFLICT
            elif relative <= RECONCILE_ROUNDING_REL:
                classification = ReconciliationClass.MATCHED \
                    if relative <= RECONCILE_ROUNDING_REL / 5.0 \
                    else ReconciliationClass.ROUNDING_NOISE
            elif z_score < RECONCILE_NOISE_Z:
                classification = ReconciliationClass.ROUNDING_NOISE
            elif methodology_mismatch and z_score < RECONCILE_SUSPICIOUS_Z:
                classification = ReconciliationClass.METHODOLOGY_EXPLAINED
            elif z_score < RECONCILE_CORRECTION_Z:
                classification = ReconciliationClass.CORRECTION_REQUIRED
            elif z_score < RECONCILE_SUSPICIOUS_Z:
                classification = ReconciliationClass.SUSPICIOUS_OVERRIDE \
                    if override else ReconciliationClass.CORRECTION_REQUIRED
            else:
                classification = \
                    ReconciliationClass.MATERIAL_OVERSTATEMENT
            if classification in {
                    ReconciliationClass.SUSPICIOUS_OVERRIDE,
                    ReconciliationClass.MATERIAL_OVERSTATEMENT}:
                overrides = self.manual_overrides.get(
                    claim.firm_symbol, 0) + sum(
                    1 for item in self.findings
                    if item.firm_symbol == claim.firm_symbol
                    and item.classification in {
                        ReconciliationClass.SUSPICIOUS_OVERRIDE.value,
                        ReconciliationClass
                        .MATERIAL_OVERSTATEMENT.value})
                if overrides >= RECONCILE_REPEAT_THRESHOLD:
                    classification = \
                        ReconciliationClass.REPEATED_MANIPULATION

            self._finding_sequence += 1
            finding = ReconciliationFinding(
                finding_id=f"RC-{day}-{self._finding_sequence}",
                day=day, firm_symbol=claim.firm_symbol,
                claim_id=claim.claim_id, subject=claim.subject.value,
                firm_value=claim.asserted_value,
                connector_value=record.estimate,
                other_evidence_value=other.estimate
                if other is not None else None,
                absolute_divergence=abs(divergence),
                relative_divergence=relative,
                standardized_divergence=z_score,
                coverage_adjusted_divergence=coverage_adjusted,
                methodology_mismatch=methodology_mismatch,
                unit_mismatch=unit_mismatch,
                boundary_mismatch=boundary_mismatch,
                staleness_days=record.staleness_days,
                confidence=confidence,
                unexplained_manual_adjustment=override,
                classification=classification.value)
            new_findings.append(finding)
            self.findings.append(finding)
            if classification in {
                    ReconciliationClass.CORRECTION_REQUIRED,
                    ReconciliationClass.SUSPICIOUS_OVERRIDE,
                    ReconciliationClass.MATERIAL_OVERSTATEMENT,
                    ReconciliationClass.REPEATED_MANIPULATION}:
                flags.add(claim.claim_id)
        return new_findings, flags

    # -- cost booking ---------------------------------------------------------#
    def _book_state_cost(self, amount_dec: Decimal, state: Any) -> None:
        if amount_dec <= _ZERO:
            return
        self.state_cost_dec += amount_dec
        if state is not None:
            state.pay_policy_cost(amount_dec)

    def _book_firm_cost(self, asset: Any, amount_dec: Decimal) -> None:
        if amount_dec <= _ZERO:
            return
        headroom = max(0.0, asset.balance - CORPORATE_BALANCE_FLOOR)
        payable = min(float(amount_dec), headroom)
        if payable > 0.0:
            asset.balance -= payable
        self.firm_cost_dec[asset.symbol] = self.firm_cost_dec.get(
            asset.symbol, _ZERO) + _dec_cents(payable)


# --------------------------------------------------------------------------- #
# Ledger exports
# --------------------------------------------------------------------------- #
def export_prescreening_ledger(sim: Any, csv_path: str) -> None:
    """One row per hub event (Section 10, output 2)."""
    import csv as _csv
    fields = ["event_id", "day", "firm_symbol", "claim_id", "subject",
              "channel", "participation_mode", "state_trace",
              "issues_total", "issues_material", "issue_codes", "action",
              "firm_cost", "state_cost", "processing_delay_days",
              "prescreening_status", "policy_regime"]
    hub = getattr(sim, "prescreening_hub", None)
    events = hub.events if hub is not None else []
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = _csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for event in events:
            row = event.to_dict()
            row["policy_regime"] = sim.policy_regime.value
            writer.writerow(row)
    print(f"Pre-screening event ledger exported to '{csv_path}'.")


def export_connector_ledgers(sim: Any, provenance_path: str,
                             reconciliation_path: str) -> None:
    """Provenance and reconciliation ledgers (Section 10, output 3)."""
    import csv as _csv
    connector = getattr(sim, "green_data_connector", None)
    provenance = connector.provenance if connector is not None else []
    findings = connector.findings if connector is not None else []
    if provenance:
        fields = list(provenance[0].to_dict().keys()) + ["policy_regime"]
    else:
        fields = ["transfer_id", "policy_regime"]
    with open(provenance_path, "w", newline="", encoding="utf-8") as handle:
        writer = _csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in provenance:
            row = record.to_dict()
            row["policy_regime"] = sim.policy_regime.value
            writer.writerow(row)
    if findings:
        fields = list(findings[0].to_dict().keys()) + ["policy_regime"]
    else:
        fields = ["finding_id", "policy_regime"]
    with open(reconciliation_path, "w", newline="",
              encoding="utf-8") as handle:
        writer = _csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for finding in findings:
            row = finding.to_dict()
            row["policy_regime"] = sim.policy_regime.value
            writer.writerow(row)
    print(f"Connector ledgers exported to '{provenance_path}' and "
          f"'{reconciliation_path}'.")
