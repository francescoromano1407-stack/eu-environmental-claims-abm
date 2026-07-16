"""Typed environmental information used by the opt-in supervision layer.

The module deliberately separates three information sets:

* :class:`EnvironmentalFactVector` is the firm's latent physical state;
* :class:`EvidenceRecord` is an observable, uncertain estimate of a fact;
* :class:`EnvironmentalClaim` is a communication made to an audience.

Consumers, investors and supervisors receive claims, evidence and published
assessments.  They must never be handed the latent fact vector directly.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Iterable, Mapping, Optional
import math


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return min(upper, max(lower, float(value)))


def meaningful_qualification(text: str) -> bool:
    """Part I.3 (EXPERIMENT): semantic-adequacy proxy for qualifications.

    A qualification counts only if it is long enough to say something and
    mentions at least one recognised scoping token (boundary, period,
    scope, uncertainty, estimate, method, basis, coverage). Placeholder
    strings ("x", "qualified") no longer satisfy any qualification-based
    rule -- the red-team showed token qualifications gamed both the rule
    engine and the pre-screening hub. This is a stylized text heuristic,
    not NLP; its limits are documented in the model documentation.
    """
    from market_sim.constants import (QUALIFICATION_MIN_LENGTH,
                                      QUALIFICATION_TOKENS)
    if not text or len(text.strip()) < QUALIFICATION_MIN_LENGTH:
        return False
    lowered = text.lower()
    return any(token in lowered for token in QUALIFICATION_TOKENS)


def sector_materiality_mask(sector: str) -> dict[str, Optional[bool]]:
    """Default ``STYLIZATION`` mask; non-material is distinct from zero."""
    mask: dict[str, Optional[bool]] = {
        subject.value: True for subject in ClaimSubject}
    normalized = sector.lower()
    if normalized in {"software", "professional_services", "financial"}:
        mask[ClaimSubject.BIODIVERSITY_PRESSURE.value] = False
        mask[ClaimSubject.WATER_INTENSITY.value] = False
        mask[ClaimSubject.SCOPE_3_EMISSIONS.value] = True
    elif normalized in {"agriculture", "mining", "chemicals"}:
        mask[ClaimSubject.BIODIVERSITY_PRESSURE.value] = True
        mask[ClaimSubject.WATER_INTENSITY.value] = True
        mask[ClaimSubject.POLLUTION_INTENSITY.value] = True
    return mask


class ClaimChannel(str, Enum):
    SUSTAINABILITY_REPORT = "sustainability_report"
    MARKETING = "marketing"
    INVESTOR_COMMUNICATION = "investor_communication"
    PRODUCT_LABEL = "product_label"


class ClaimAudience(str, Enum):
    GENERAL_PUBLIC = "general_public"
    CONSUMERS = "consumers"
    INVESTORS = "investors"
    REGULATORS = "regulators"
    EMPLOYEES = "employees"
    SUPPLIERS = "suppliers"
    PROFESSIONAL_INVESTORS = "professional_investors"
    RETAIL_INVESTORS = "retail_investors"
    MIXED = "mixed"


class ClaimType(str, Enum):
    QUANTITATIVE = "quantitative"
    COMPARATIVE = "comparative"
    FUTURE_TARGET = "future_target"
    QUALITATIVE = "qualitative"
    TAXONOMY = "taxonomy"
    OFFSET_BASED = "offset_based"


class ClaimSubject(str, Enum):
    GREEN_SCORE = "green_score"
    SCOPE_1_EMISSIONS = "scope_1_emissions"
    SCOPE_2_EMISSIONS = "scope_2_emissions"
    SCOPE_3_EMISSIONS = "scope_3_emissions"
    RENEWABLE_ENERGY_SHARE = "renewable_energy_share"
    WATER_INTENSITY = "water_intensity"
    RECYCLING_RATE = "recycling_rate"
    POLLUTION_INTENSITY = "pollution_intensity"
    BIODIVERSITY_PRESSURE = "biodiversity_pressure"
    TAXONOMY_ELIGIBILITY = "taxonomy_eligibility"
    TAXONOMY_ALIGNMENT = "taxonomy_alignment"
    ENVIRONMENTAL_CAPEX = "environmental_capex"
    OFFSETS = "offsets"
    NET_ZERO = "net_zero"


class EvidenceSource(str, Enum):
    COMPANY_RECORD = "company_record"
    LIMITED_ASSURANCE = "limited_assurance"
    THIRD_PARTY = "third_party"
    REGULATOR_ESTIMATE = "regulator_estimate"
    WHISTLEBLOWER = "whistleblower"
    PUBLIC_DATA = "public_data"
    # Part H, Regime C (EXPERIMENT): evidence transferred through the
    # certified public green data connector. High independence and a
    # tamper-evident provenance record, but never infallible: meter error,
    # mismatch, staleness and register errors keep its uncertainty > 0.
    CERTIFIED_PUBLIC_CONNECTOR = "certified_public_connector"


class AssessmentOutcome(str, Enum):
    SUPPORTED = "supported"
    SUPPORTED_WITH_QUALIFICATION = "supported_with_qualification"
    NOISE = "noise"
    INCONCLUSIVE = "inconclusive"
    CORRECTABLE_ERROR = "correctable_error"
    NEGLIGENCE = "negligence"
    OVERSTATEMENT = "overstatement"
    SYSTEMIC_ABUSE = "systemic_abuse"
    PROHIBITED_PRACTICE = "prohibited_practice"
    GREENHUSHING_SIGNAL = "greenhushing_signal"


class OmissionGround(str, Enum):
    SERIOUS_COMMERCIAL_PREJUDICE = "serious_commercial_prejudice"
    TRADE_SECRET = "trade_secret"
    CLASSIFIED_INFORMATION = "classified_information"
    PRIVACY_SECURITY_OR_OTHER_LAW = "privacy_security_or_other_law"


class RuleAuthority(str, Enum):
    UCPD_BASE = "ucpd_base"
    EMPOWERING_CONSUMERS_2024_825 = "directive_2024_825"
    CSRD = "csrd"
    MARKET_DISCLOSURE = "market_disclosure"
    CSDDD = "csddd"
    GREEN_CLAIMS_COUNTERFACTUAL = "green_claims_counterfactual"


class LegalTrack(str, Enum):
    CONSUMER = "consumer"
    SUSTAINABILITY_REPORTING = "sustainability_reporting"
    FINANCIAL_MARKETS = "financial_markets"
    DUE_DILIGENCE = "due_diligence"


class CaseState(str, Enum):
    SCREENED = "screened"
    EVIDENCE_REQUESTED = "evidence_requested"
    UNDER_ASSESSMENT = "under_assessment"
    CORRECTION_WINDOW = "correction_window"
    FORMAL_INVESTIGATION = "formal_investigation"
    # Part J (Workstream C): explicit procedural state for evidence-conflict
    # investigations. A conflict case consumes finite investigation
    # capacity, waits for source re-verification, and can only escalate on
    # corroborated evidence -- never straight to a sanction.
    CONFLICT_RESOLUTION = "conflict_resolution"
    DECIDED = "decided"
    PUBLISHED = "published"
    CLOSED = "closed"


@dataclass(frozen=True)
class FirmProfile:
    """Legal and economic identity of a simulated undertaking.

    ``legacy_firm_size`` exists only as an audit trail for tuple-profile
    migration.  New legal scope tests use turnover and average employees.
    """

    symbol: str
    green_score: float
    strategy: str = "honest"
    annual_net_turnover: float = 300_000_000.0
    average_employees: float = 800.0
    sector: str = "general"
    legacy_firm_size: Optional[float] = None
    group_annual_net_turnover: Optional[float] = None
    group_average_employees: Optional[float] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "green_score", _clamp(self.green_score))
        object.__setattr__(self, "annual_net_turnover",
                           max(0.0, float(self.annual_net_turnover)))
        object.__setattr__(self, "average_employees",
                           max(0.0, float(self.average_employees)))
        if self.group_annual_net_turnover is not None:
            object.__setattr__(self, "group_annual_net_turnover", max(
                0.0, float(self.group_annual_net_turnover)))
        if self.group_average_employees is not None:
            object.__setattr__(self, "group_average_employees", max(
                0.0, float(self.group_average_employees)))

    @classmethod
    def from_legacy(cls, value: Any, *, balance_proxy: float = 300_000.0,
                    legacy_size_threshold: float = 300_000.0) -> "FirmProfile":
        """Adapt old ``(symbol, score, strategy?, firm_size?)`` tuples.

        A supplied legacy size is mapped proportionally around the old size
        threshold.  This preserves the intent of old scenarios while making
        the new CSRD test explicit and two-dimensional.  Missing size data
        defaults to a voluntary, out-of-scope undertaking.
        """
        if isinstance(value, cls):
            return value
        if not isinstance(value, (tuple, list)) or len(value) < 2:
            raise TypeError("asset profile must be FirmProfile or a tuple")
        symbol = str(value[0])
        score = float(value[1])
        strategy = str(value[2]) if len(value) >= 3 else "honest"
        if len(value) < 4 or value[3] is None:
            return cls(symbol, score, strategy)
        legacy_size = max(0.0, float(value[3]))
        denominator = legacy_size_threshold if legacy_size_threshold > 0 \
            else max(1.0, balance_proxy)
        ratio = legacy_size / denominator
        return cls(
            symbol=symbol,
            green_score=score,
            strategy=strategy,
            annual_net_turnover=450_000_000.0 * ratio,
            average_employees=1000.0 * ratio,
            legacy_firm_size=legacy_size,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EnvironmentalFactVector:
    """Multidimensional latent physical state for one reporting period."""

    period_start: date
    period_end: date
    scope_1_emissions: float
    scope_2_emissions: float
    scope_3_emissions: float
    renewable_energy_share: float
    energy_use: float
    water_use: float
    water_intensity: float
    waste_generated: float
    recycling_rate: float
    pollution_intensity: float
    biodiversity_pressure: float
    taxonomy_eligible_turnover_share: float
    taxonomy_aligned_turnover_share: float
    taxonomy_eligible_capex_share: float
    taxonomy_aligned_capex_share: float
    taxonomy_eligible_opex_share: float
    taxonomy_aligned_opex_share: float
    environmental_capex: float
    offsets_retired: float
    organizational_boundary: str = "consolidated_group"
    operational_boundary: str = "scope_1_2_3"
    methodology: str = "simulation_physical_ledger_v1"
    uncertainty: dict[str, float] = field(default_factory=dict)
    geography: str = "EU"
    product_activity_boundary: str = "all_material_activities"
    evidence_quality: dict[str, float] = field(default_factory=dict)
    materiality_mask: dict[str, Optional[bool]] = field(default_factory=dict)

    @classmethod
    def from_green_score(cls, score: float, period_start: date,
                         period_end: date, turnover: float = 300_000_000.0,
                         scale: float = 1.0,
                         sector: str = "general") -> "EnvironmentalFactVector":
        """Create a coherent initial vector (``STYLIZATION``)."""
        g = _clamp(score)
        activity = max(0.1, float(scale))
        eligible = _clamp(0.25 + 0.60 * g)
        aligned = min(eligible, _clamp(0.05 + 0.75 * g))
        capex_eligible = _clamp(eligible + 0.05)
        capex_aligned = min(capex_eligible, _clamp(aligned + 0.08))
        opex_eligible = _clamp(eligible - 0.03)
        opex_aligned = min(opex_eligible, _clamp(aligned - 0.03))
        return cls(
            period_start=period_start,
            period_end=period_end,
            scope_1_emissions=100_000.0 * activity * (1.05 - 0.75 * g),
            scope_2_emissions=75_000.0 * activity * (1.05 - 0.80 * g),
            scope_3_emissions=280_000.0 * activity * (1.05 - 0.60 * g),
            renewable_energy_share=_clamp(0.05 + 0.90 * g),
            energy_use=250_000.0 * activity * (1.0 - 0.20 * g),
            water_use=180_000.0 * activity * (1.0 - 0.35 * g),
            water_intensity=max(0.0, 1.0 - 0.60 * g),
            waste_generated=70_000.0 * activity * (1.0 - 0.35 * g),
            recycling_rate=_clamp(0.20 + 0.70 * g),
            pollution_intensity=max(0.0, 1.0 - 0.80 * g),
            biodiversity_pressure=max(0.0, 1.0 - 0.50 * g),
            taxonomy_eligible_turnover_share=eligible,
            taxonomy_aligned_turnover_share=aligned,
            taxonomy_eligible_capex_share=capex_eligible,
            taxonomy_aligned_capex_share=capex_aligned,
            taxonomy_eligible_opex_share=opex_eligible,
            taxonomy_aligned_opex_share=opex_aligned,
            environmental_capex=max(0.0, turnover * (0.002 + 0.018 * g)),
            offsets_retired=15_000.0 * activity * g,
            uncertainty={subject.value: 0.04 for subject in ClaimSubject},
            evidence_quality={subject.value: 0.70
                              for subject in ClaimSubject},
            materiality_mask=sector_materiality_mask(sector),
        )

    def value_for(self, subject: ClaimSubject) -> float:
        mapping = {
            ClaimSubject.GREEN_SCORE: self.aggregate_score(),
            ClaimSubject.SCOPE_1_EMISSIONS: self.scope_1_emissions,
            ClaimSubject.SCOPE_2_EMISSIONS: self.scope_2_emissions,
            ClaimSubject.SCOPE_3_EMISSIONS: self.scope_3_emissions,
            ClaimSubject.RENEWABLE_ENERGY_SHARE: self.renewable_energy_share,
            ClaimSubject.WATER_INTENSITY: self.water_intensity,
            ClaimSubject.RECYCLING_RATE: self.recycling_rate,
            ClaimSubject.POLLUTION_INTENSITY: self.pollution_intensity,
            ClaimSubject.BIODIVERSITY_PRESSURE: self.biodiversity_pressure,
            ClaimSubject.TAXONOMY_ELIGIBILITY:
                self.taxonomy_eligible_turnover_share,
            ClaimSubject.TAXONOMY_ALIGNMENT:
                self.taxonomy_aligned_turnover_share,
            ClaimSubject.ENVIRONMENTAL_CAPEX: self.environmental_capex,
            ClaimSubject.OFFSETS: self.offsets_retired,
            ClaimSubject.NET_ZERO: self.net_emissions_ratio(),
        }
        return float(mapping[subject])

    def gross_emissions(self) -> float:
        return self.scope_1_emissions + self.scope_2_emissions \
            + self.scope_3_emissions

    def net_emissions_ratio(self) -> float:
        gross = self.gross_emissions()
        if gross <= 0.0:
            return 0.0
        return max(0.0, (gross - self.offsets_retired) / gross)

    def aggregate_score(self) -> float:
        """Compatibility indicator; enforcement uses named dimensions."""
        emissions_quality = 1.0 - _clamp(
            (self.scope_1_emissions + self.scope_2_emissions)
            / max(1.0, self.scope_1_emissions + self.scope_2_emissions
                  + 100_000.0))
        return _clamp((
            self.renewable_energy_share + self.recycling_rate
            + (1.0 - _clamp(self.water_intensity))
            + (1.0 - _clamp(self.pollution_intensity))
            + (1.0 - _clamp(self.biodiversity_pressure))
            + self.taxonomy_aligned_turnover_share + emissions_quality
        ) / 7.0)

    def evolve_toward_score(self, score: float, turnover: float) -> None:
        """Keep physical dimensions coherent with a real transition."""
        target = type(self).from_green_score(
            score, self.period_start, self.period_end, turnover)
        for name in (
            "scope_1_emissions", "scope_2_emissions", "scope_3_emissions",
            "renewable_energy_share", "energy_use", "water_use",
            "water_intensity", "waste_generated", "recycling_rate",
            "pollution_intensity", "biodiversity_pressure",
            "taxonomy_eligible_turnover_share",
            "taxonomy_aligned_turnover_share",
            "taxonomy_eligible_capex_share", "taxonomy_aligned_capex_share",
            "taxonomy_eligible_opex_share", "taxonomy_aligned_opex_share",
            "environmental_capex", "offsets_retired",
        ):
            current = float(getattr(self, name))
            setattr(self, name, current + 0.25 * (float(getattr(target, name))
                                                  - current))

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["period_start"] = self.period_start.isoformat()
        result["period_end"] = self.period_end.isoformat()
        return result


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    firm_symbol: str
    subject: ClaimSubject
    period_start: date
    period_end: date
    estimate: float
    standard_error: float
    source: EvidenceSource
    coverage: float = 1.0
    independence: float = 0.5
    verified: bool = False
    notes: str = ""
    reliability_prior: float = 0.70
    staleness_days: int = 0
    conflict: bool = False
    observation_method: str = "estimated"
    accessible_to_firm: bool = True
    accessible_to_regulator: bool = True
    accessible_to_consumers: bool = False
    accessible_to_investors: bool = False
    accessible_to_employees: bool = False

    @property
    def confidence(self) -> float:
        relative_error = self.standard_error / max(abs(self.estimate), 1.0)
        precision = 1.0 / (1.0 + 8.0 * relative_error)
        staleness = 1.0 / (1.0 + max(0, self.staleness_days) / 365.0)
        conflict = 0.55 if self.conflict else 1.0
        return _clamp(precision * _clamp(self.coverage)
                      * (0.6 + 0.4 * _clamp(self.independence))
                      * _clamp(self.reliability_prior) * staleness * conflict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["subject"] = self.subject.value
        result["source"] = self.source.value
        result["period_start"] = self.period_start.isoformat()
        result["period_end"] = self.period_end.isoformat()
        return result


@dataclass
class EnvironmentalClaim:
    claim_id: str
    firm_symbol: str
    day: int
    communication_date: date
    channel: ClaimChannel
    audience: ClaimAudience
    claim_type: ClaimType
    subject: ClaimSubject
    asserted_value: float
    unit: str
    period_start: date
    period_end: date
    organizational_boundary: str
    operational_boundary: str
    evidence_ids: tuple[str, ...] = ()
    qualification: str = ""
    stated_uncertainty: float = 0.0
    baseline_value: Optional[float] = None
    target_date: Optional[date] = None
    relies_on_offsets: bool = False
    offset_disclosed_separately: bool = True
    material: bool = True
    corrected_claim_id: Optional[str] = None
    withdrawn: bool = False
    review_day: Optional[int] = None
    geography: str = "EU"
    lifecycle_boundary: str = "operations"
    comparator: str = ""
    qualification_prominence: float = 0.0
    public_evidence: bool = True
    reach: float = 0.0
    repetition: int = 1
    marketing_spend: float = 0.0
    expected_commercial_benefit: float = 0.0
    synthetic_structured_claim: bool = True
    # Part I.3 -- immutable history (red-team P1-3). A regulatory
    # correction updates the LIVE public value prospectively but must
    # never erase what was originally asserted: the original value, the
    # correction day and the withdrawal day are preserved so incidence,
    # exposure duration and time-to-correction can be measured on the
    # historical record. `record_correction` is the ONLY sanctioned
    # mutation path for a published claim's value.
    original_asserted_value: Optional[float] = None
    corrected_day: Optional[int] = None
    correction_basis: str = ""
    withdrawn_day: Optional[int] = None

    def record_correction(self, day: int, corrected_value: float,
                          basis: str, qualification: str = "") -> None:
        """Apply a prospective public correction, preserving the original
        asserted value immutably (first correction wins the snapshot)."""
        if self.original_asserted_value is None:
            self.original_asserted_value = self.asserted_value
        self.asserted_value = corrected_value
        self.corrected_day = day
        self.correction_basis = basis
        if qualification and not self.qualification:
            self.qualification = qualification

    def record_withdrawal(self, day: int) -> None:
        """Withdraw the claim, preserving when exposure ended."""
        if self.original_asserted_value is None:
            self.original_asserted_value = self.asserted_value
        self.withdrawn = True
        if self.withdrawn_day is None:
            self.withdrawn_day = day

    @property
    def historical_asserted_value(self) -> float:
        """The value as ORIGINALLY published (research/audit use)."""
        return self.original_asserted_value \
            if self.original_asserted_value is not None \
            else self.asserted_value

    def exposure_days(self, horizon_day: int) -> int:
        """Days the original assertion was publicly live (0 for drafts
        withheld before publication)."""
        if self.withdrawn_day is not None and self.withdrawn_day <= self.day:
            return 0
        end = horizon_day
        if self.corrected_day is not None:
            end = min(end, self.corrected_day)
        if self.withdrawn_day is not None:
            end = min(end, self.withdrawn_day)
        return max(0, end - self.day)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("channel", "audience", "claim_type", "subject"):
            result[key] = getattr(self, key).value
        for key in ("communication_date", "period_start", "period_end",
                    "target_date"):
            value = getattr(self, key)
            result[key] = value.isoformat() if value is not None else None
        result["evidence_ids"] = list(self.evidence_ids)
        return result


@dataclass
class ClaimAssessment:
    assessment_id: str
    claim_id: str
    firm_symbol: str
    day: int
    outcome: AssessmentOutcome
    legal_track: LegalTrack
    authority: RuleAuthority
    estimated_fact: Optional[float]
    divergence: Optional[float]
    standard_error: Optional[float]
    standardized_divergence: Optional[float]
    materiality: float
    confidence: float
    reasons: tuple[str, ...] = ()
    corrective_action: str = "none"
    estimated_benefit: float = 0.0
    affected_revenue: float = 0.0
    penalty: float = 0.0
    published: bool = False
    rule_ids: tuple[str, ...] = ()
    factual_severity: float = 0.0
    legal_relevance: float = 0.0
    audience_impact: float = 0.0
    conduct_severity: float = 0.0
    # Part I.2 detector-hardening flags (additive, default-off).
    evidence_conflict: bool = False        # Unresolved cross-source conflict
    boundary_mismatch: bool = False        # Restricted, undisclosed boundary
    implausible_uncertainty: bool = False  # Self-declared sigma capped
    pattern_escalated: bool = False        # Repeat sub-threshold escalation
    # Part J (Workstream C): the two records behind an evidence conflict,
    # recorded so the conflict-resolution procedure can re-examine exactly
    # the file that produced the INCONCLUSIVE routing.
    conflict_independent_evidence_id: Optional[str] = None
    conflict_internal_evidence_id: Optional[str] = None

    @property
    def confirmed_abuse(self) -> bool:
        return self.outcome in {
            AssessmentOutcome.OVERSTATEMENT,
            AssessmentOutcome.SYSTEMIC_ABUSE,
            AssessmentOutcome.PROHIBITED_PRACTICE,
        }

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["outcome"] = self.outcome.value
        result["legal_track"] = self.legal_track.value
        result["authority"] = self.authority.value
        result["reasons"] = list(self.reasons)
        result["rule_ids"] = list(self.rule_ids)
        return result


@dataclass(frozen=True)
class ReportingOmission:
    """Claim-specific reporting omission; never a marketing safe harbour."""

    omission_id: str
    firm_symbol: str
    subject: ClaimSubject
    ground: OmissionGround
    reporting_period_end: date
    disclosed_use_of_exemption: bool
    reassessment_date: date
    fair_and_balanced_understanding_preserved: bool
    exceptional_serious_prejudice: bool = False
    conditions_documented: bool = False
    applies_only_to_report: bool = True

    def valid_for_report(self, on_date: date) -> bool:
        if not self.applies_only_to_report \
                or not self.disclosed_use_of_exemption \
                or not self.fair_and_balanced_understanding_preserved \
                or not self.conditions_documented \
                or self.reassessment_date < on_date:
            return False
        if self.ground == OmissionGround.SERIOUS_COMMERCIAL_PREJUDICE:
            return self.exceptional_serious_prejudice
        return True

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["subject"] = self.subject.value
        result["ground"] = self.ground.value
        result["reporting_period_end"] = \
            self.reporting_period_end.isoformat()
        result["reassessment_date"] = self.reassessment_date.isoformat()
        return result


@dataclass(frozen=True)
class PublicEnvironmentalSignal:
    """Information-safe signal available to markets and public bodies."""

    firm_symbol: str
    day: int
    supported_score: float
    credibility: float
    perceived_discrepancy: float
    controversy_discount: float
    source: str
    confirmed_abuse: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InvestorEnvironmentalContext:
    posterior_score: float
    credibility: float = 1.0
    controversy_discount: float = 0.0
    disclosure_age_days: int = 0
    confirmed_abuse: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "posterior_score",
                           _clamp(self.posterior_score))
        object.__setattr__(self, "credibility", _clamp(self.credibility))
        object.__setattr__(self, "controversy_discount",
                           _clamp(self.controversy_discount, 0.0, 0.95))


def best_evidence(records: Iterable[EvidenceRecord], subject: ClaimSubject,
                  period_start: date, period_end: date) -> Optional[EvidenceRecord]:
    """Select evidence by period overlap, confidence and independence."""
    candidates = []
    for record in records:
        if record.subject != subject:
            continue
        overlap_start = max(period_start, record.period_start)
        overlap_end = min(period_end, record.period_end)
        if overlap_end < overlap_start:
            continue
        candidates.append(record)
    if not candidates:
        return None
    return max(candidates, key=lambda item: (
        item.verified, item.confidence, item.independence, item.coverage))


def standardized_divergence(asserted: float, estimated: float,
                            evidence_error: float,
                            stated_uncertainty: float = 0.0,
                            materiality_floor: float = 0.0) -> tuple[float, float]:
    """Return signed divergence and its uncertainty-standardized magnitude."""
    divergence = float(asserted) - float(estimated)
    denominator = math.sqrt(max(1e-12, evidence_error ** 2
                                + stated_uncertainty ** 2
                                + materiality_floor ** 2))
    return divergence, abs(divergence) / denominator
