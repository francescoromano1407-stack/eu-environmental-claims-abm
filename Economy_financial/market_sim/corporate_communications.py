"""Corporate environmental communication and greenhushing decisions.

This module is active only with ``enable_greenwashing_supervision``.  The
firm may inspect its own physical ledger, but it publishes only structured
claims and evidence.  Downstream agents never receive the ledger itself.

Choice-grid coefficients are ``STYLIZATION`` values.  They model the joint
choice of real investment, communication volume, claim qualification,
evidence quality and overstatement; they are not legal or empirical facts.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
import itertools
import random
from typing import Iterable

from market_sim.constants import CORPORATE_BALANCE_FLOOR
from market_sim.environmental_claims import (
    ClaimAudience,
    ClaimChannel,
    ClaimSubject,
    ClaimType,
    EnvironmentalClaim,
    EvidenceRecord,
    EvidenceSource,
)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return min(upper, max(lower, float(value)))


@dataclass(frozen=True)
class CommunicationDecision:
    real_investment_increment: float
    communication_intensity: float
    qualification: float
    evidence_effort: float
    overstatement: float
    truthful_benchmark: float
    greenhushing_gap: float
    expected_private_value: float
    real_investment_cost: float = 0.0
    claim_preparation_cost: float = 0.0
    evidence_cost: float = 0.0


class CorporateCommunicationsPolicy:
    """Generate claims and evidence from a firm's joint policy choice."""

    def __init__(self, asset, strategy: str):
        self.asset = asset
        self.strategy = strategy
        self.claim_sequence = 0
        self.evidence_sequence = 0
        self.last_decision: CommunicationDecision | None = None

    def choose(self, regulatory_strictness: float,
               mandatory_report: bool,
               guidance_support: float = 0.0,
               evidence_support: float = 0.0,
               compliance_burden_scale: float = 1.0) -> CommunicationDecision:
        """Solve a small transparent joint discrete optimization problem."""
        asset = self.asset
        g = asset.true_green_score
        strictness = _clamp(regulatory_strictness)
        guidance = _clamp(guidance_support)
        evidence_support = _clamp(evidence_support)
        truthful_benchmark = _clamp(0.20 + 0.70 * g)
        investment_grid = (0.0, 0.002, 0.005)
        communication_grid = (0.0, 0.20, 0.40, 0.60, 0.80, 1.0)
        qualification_grid = (0.25, 0.60, 1.0)
        evidence_grid = (0.25, 0.50, 0.75, 1.0)
        if self.strategy == "honest":
            overstatement_grid = (0.0,)
            temptation = 0.0
            risk_aversion = 1.3
        elif self.strategy == "adaptive":
            overstatement_grid = (0.0, 0.03, 0.07, 0.12)
            temptation = 0.55
            risk_aversion = 1.0
        else:
            overstatement_grid = (0.0, 0.05, 0.10, 0.18, 0.25)
            temptation = 1.0
            risk_aversion = 0.75

        best: tuple[float, tuple[float, ...]] | None = None
        for investment, q, qualification, evidence, overstatement in \
                itertools.product(investment_grid, communication_grid,
                                  qualification_grid, evidence_grid,
                                  overstatement_grid):
            perceived_quality = _clamp(g + investment + overstatement)
            communication_gain = q * (0.25 + 0.75 * perceived_quality)
            investment_gain = 4.2 * investment * (0.5 + q)
            exaggeration_gain = temptation * q * 0.90 * overstatement
            missed_green_premium = 0.22 * max(0.0, truthful_benchmark - q)
            investment_cost = 5.5 * investment
            evidence_cost = q * (0.025 + 0.075 * evidence ** 2) \
                * (1.0 - 0.50 * evidence_support)
            qualification_cost = q * 0.035 * qualification
            # Regulatory burden chills even truthful voluntary speech at
            # extreme settings, generating greenhushing as a policy risk.
            compliance_burden = strictness * q * (
                0.025 + 0.15 * (1.0 - evidence)
                + 0.05 * qualification)
            compliance_burden += strictness ** 3 * q * 1.10
            compliance_burden *= (1.0 - 0.60 * guidance)
            # Part J sensitivity lever (STYLIZATION; default 1.0): scales
            # the perceived compliance burden that drives greenhushing.
            compliance_burden *= max(0.0, compliance_burden_scale)
            if mandatory_report:
                # Mandatory reporting has a fixed disclosure floor; this is
                # separate from voluntary marketing/investor intensity.
                compliance_burden += strictness * 0.025 \
                    * max(0.0, compliance_burden_scale)
            detection = _clamp(
                0.10 + 1.8 * overstatement + 0.25 * (1.0 - evidence)
                - 0.20 * qualification)
            expected_enforcement = (strictness * detection * risk_aversion
                                    * (1.5 * overstatement + 0.04 * q))
            value = (communication_gain + investment_gain
                     + exaggeration_gain - missed_green_premium
                     - investment_cost - evidence_cost - qualification_cost
                     - compliance_burden - expected_enforcement)
            candidate = (investment, q, qualification, evidence,
                         overstatement)
            if best is None or value > best[0]:
                best = (value, candidate)
        assert best is not None
        value, candidate = best
        investment, q, qualification, evidence, overstatement = candidate
        greenhushing_gap = max(0.0, truthful_benchmark - q)
        decision = CommunicationDecision(
            real_investment_increment=investment,
            communication_intensity=q,
            qualification=qualification,
            evidence_effort=evidence,
            overstatement=overstatement,
            truthful_benchmark=truthful_benchmark,
            greenhushing_gap=greenhushing_gap,
            expected_private_value=value,
        )
        self.last_decision = decision
        asset.q_truthful_benchmark = truthful_benchmark
        asset.greenhushing_gap = greenhushing_gap
        return decision

    def communicate(self, day: int, communication_date: date,
                    regulatory_strictness: float,
                    mandatory_report: bool,
                    rng: random.Random,
                    guidance_support: float = 0.0,
                    evidence_support: float = 0.0,
                    compliance_burden_scale: float = 1.0) -> tuple[
                        CommunicationDecision,
                        list[EnvironmentalClaim],
                        list[EvidenceRecord]]:
        decision = self.choose(
            regulatory_strictness, mandatory_report,
            guidance_support, evidence_support,
            compliance_burden_scale=compliance_burden_scale)
        asset = self.asset
        investment_cost = 0.0
        if decision.real_investment_increment > 0.0:
            investment_cost = asset.balance * 0.001 \
                * (decision.real_investment_increment / 0.005)
            asset.apply_green_transition(
                decision.real_investment_increment, investment_cost, day)
            asset.real_environmental_investment_spend += investment_cost

        # External data/preparation services are booked once. Coefficients
        # are STYLIZATION values and remain small relative to the balance.
        preparation_cost = asset.balance * 0.00002 \
            * decision.communication_intensity
        evidence_cost = asset.balance * 0.00003 \
            * decision.communication_intensity * decision.evidence_effort ** 2
        total_external_cost = preparation_cost + evidence_cost
        payable = min(total_external_cost, max(
            0.0, asset.balance - CORPORATE_BALANCE_FLOOR))
        if total_external_cost > 0.0 and payable < total_external_cost:
            scale = payable / total_external_cost
            preparation_cost *= scale
            evidence_cost *= scale
        asset.balance -= payable
        asset.communication_preparation_spend += preparation_cost
        asset.environmental_evidence_spend += evidence_cost
        decision = replace(
            decision,
            real_investment_cost=investment_cost,
            claim_preparation_cost=preparation_cost,
            evidence_cost=evidence_cost)
        self.last_decision = decision

        period_end = communication_date - timedelta(days=1)
        period_start = period_end - timedelta(days=364)
        # Re-anchor the physical ledger's reporting period without changing
        # its measurements.
        asset.environmental_facts.period_start = period_start
        asset.environmental_facts.period_end = period_end

        specs: list[tuple[ClaimChannel, ClaimAudience, ClaimType,
                          ClaimSubject, str]] = []
        if mandatory_report:
            specs.extend(self._report_specs())
        optional_count = int(round(decision.communication_intensity * 7))
        optional_specs = self._optional_specs()
        specs.extend(optional_specs[:optional_count])

        claims: list[EnvironmentalClaim] = []
        evidence: list[EvidenceRecord] = []
        for channel, audience, claim_type, subject, unit in specs:
            record = self._make_evidence(
                subject, period_start, period_end,
                decision.evidence_effort, rng, channel, audience)
            evidence.append(record)
            claim = self._make_claim(
                day, communication_date, channel, audience, claim_type,
                subject, unit, record, decision, period_start, period_end)
            claims.append(claim)

        if claims:
            green_claims = [claim for claim in claims
                            if claim.subject == ClaimSubject.GREEN_SCORE]
            if green_claims:
                asset.set_disclosed_score(green_claims[-1].asserted_value,
                                          day)
        asset.claim_history.extend(claims)
        asset.evidence_history.extend(evidence)
        return decision, claims, evidence

    @staticmethod
    def _report_specs() -> list[tuple[ClaimChannel, ClaimAudience,
                                      ClaimType, ClaimSubject, str]]:
        report = ClaimChannel.SUSTAINABILITY_REPORT
        audience = ClaimAudience.MIXED
        return [
            (report, audience, ClaimType.QUANTITATIVE,
             ClaimSubject.GREEN_SCORE, "score_0_1"),
            (report, audience, ClaimType.QUANTITATIVE,
             ClaimSubject.SCOPE_1_EMISSIONS, "tCO2e"),
            (report, audience, ClaimType.QUANTITATIVE,
             ClaimSubject.SCOPE_2_EMISSIONS, "tCO2e"),
            (report, audience, ClaimType.QUANTITATIVE,
             ClaimSubject.SCOPE_3_EMISSIONS, "tCO2e"),
            (report, audience, ClaimType.QUANTITATIVE,
             ClaimSubject.RENEWABLE_ENERGY_SHARE, "share_0_1"),
            (report, audience, ClaimType.TAXONOMY,
             ClaimSubject.TAXONOMY_ELIGIBILITY, "share_0_1"),
            (report, audience, ClaimType.TAXONOMY,
             ClaimSubject.TAXONOMY_ALIGNMENT, "share_0_1"),
            (report, audience, ClaimType.QUANTITATIVE,
             ClaimSubject.ENVIRONMENTAL_CAPEX, "EUR"),
            (report, audience, ClaimType.OFFSET_BASED,
             ClaimSubject.OFFSETS, "tCO2e"),
        ]

    @staticmethod
    def _optional_specs() -> list[tuple[ClaimChannel, ClaimAudience,
                                        ClaimType, ClaimSubject, str]]:
        return [
            (ClaimChannel.MARKETING, ClaimAudience.CONSUMERS,
             ClaimType.QUALITATIVE, ClaimSubject.GREEN_SCORE, "score_0_1"),
            (ClaimChannel.INVESTOR_COMMUNICATION, ClaimAudience.INVESTORS,
             ClaimType.TAXONOMY, ClaimSubject.TAXONOMY_ALIGNMENT,
             "share_0_1"),
            (ClaimChannel.MARKETING, ClaimAudience.CONSUMERS,
             ClaimType.QUANTITATIVE, ClaimSubject.RENEWABLE_ENERGY_SHARE,
             "share_0_1"),
            (ClaimChannel.INVESTOR_COMMUNICATION, ClaimAudience.INVESTORS,
             ClaimType.QUANTITATIVE, ClaimSubject.ENVIRONMENTAL_CAPEX,
             "EUR"),
            (ClaimChannel.MARKETING, ClaimAudience.GENERAL_PUBLIC,
             ClaimType.OFFSET_BASED, ClaimSubject.NET_ZERO,
             "net_emissions_ratio"),
            (ClaimChannel.INVESTOR_COMMUNICATION, ClaimAudience.INVESTORS,
             ClaimType.FUTURE_TARGET, ClaimSubject.SCOPE_1_EMISSIONS,
             "tCO2e"),
            (ClaimChannel.PRODUCT_LABEL, ClaimAudience.CONSUMERS,
             ClaimType.QUALITATIVE, ClaimSubject.GREEN_SCORE, "score_0_1"),
        ]

    def _make_evidence(self, subject: ClaimSubject, period_start: date,
                       period_end: date, effort: float,
                       rng: random.Random, channel: ClaimChannel,
                       audience: ClaimAudience) -> EvidenceRecord:
        facts = self.asset.environmental_facts
        truth = facts.value_for(subject)
        base_scale = max(abs(truth), 1.0)
        relative_error = 0.015 + 0.10 * (1.0 - effort)
        standard_error = base_scale * relative_error
        estimate = truth + rng.gauss(0.0, standard_error)
        if subject in {
            ClaimSubject.GREEN_SCORE, ClaimSubject.RENEWABLE_ENERGY_SHARE,
            ClaimSubject.RECYCLING_RATE, ClaimSubject.TAXONOMY_ELIGIBILITY,
            ClaimSubject.TAXONOMY_ALIGNMENT,
        }:
            estimate = _clamp(estimate)
        else:
            estimate = max(0.0, estimate)
        self.evidence_sequence += 1
        return EvidenceRecord(
            evidence_id=f"E-{self.asset.symbol}-{self.evidence_sequence}",
            firm_symbol=self.asset.symbol,
            subject=subject,
            period_start=period_start,
            period_end=period_end,
            estimate=estimate,
            standard_error=standard_error,
            source=EvidenceSource.COMPANY_RECORD,
            coverage=_clamp(0.55 + 0.45 * effort),
            independence=0.15,
            verified=False,
            notes="Management evidence; not independent assurance.",
            reliability_prior=_clamp(0.55 + 0.35 * effort),
            observation_method="estimated",
            accessible_to_consumers=audience in {
                ClaimAudience.CONSUMERS, ClaimAudience.GENERAL_PUBLIC,
                ClaimAudience.MIXED},
            accessible_to_investors=audience in {
                ClaimAudience.INVESTORS,
                ClaimAudience.PROFESSIONAL_INVESTORS,
                ClaimAudience.RETAIL_INVESTORS,
                ClaimAudience.MIXED},
            accessible_to_employees=True,
        )

    def _make_claim(self, day: int, communication_date: date,
                    channel: ClaimChannel, audience: ClaimAudience,
                    claim_type: ClaimType, subject: ClaimSubject, unit: str,
                    evidence: EvidenceRecord,
                    decision: CommunicationDecision,
                    period_start: date, period_end: date) -> EnvironmentalClaim:
        self.claim_sequence += 1
        asserted = evidence.estimate
        direction = -1.0 if subject in {
            ClaimSubject.SCOPE_1_EMISSIONS,
            ClaimSubject.SCOPE_2_EMISSIONS,
            ClaimSubject.SCOPE_3_EMISSIONS,
            ClaimSubject.WATER_INTENSITY,
            ClaimSubject.POLLUTION_INTENSITY,
            ClaimSubject.BIODIVERSITY_PRESSURE,
            ClaimSubject.NET_ZERO,
        } else 1.0
        magnitude = max(abs(evidence.estimate), 1.0)
        asserted += direction * decision.overstatement * magnitude
        if subject in {
            ClaimSubject.GREEN_SCORE, ClaimSubject.RENEWABLE_ENERGY_SHARE,
            ClaimSubject.RECYCLING_RATE, ClaimSubject.TAXONOMY_ELIGIBILITY,
            ClaimSubject.TAXONOMY_ALIGNMENT,
        }:
            asserted = _clamp(asserted)
        else:
            asserted = max(0.0, asserted)

        qualification = ""
        if decision.qualification >= 0.8:
            qualification = ("Estimate subject to the stated period, "
                             "boundary, methodology and uncertainty.")
        elif decision.qualification >= 0.5:
            qualification = "Estimate for the stated reporting boundary."
        target_date = None
        baseline_value = None
        if claim_type == ClaimType.FUTURE_TARGET:
            baseline_value = evidence.estimate
            asserted = max(0.0, asserted * 0.70)
            target_date = date(communication_date.year + 5, 12, 31)
        scope_boundary = "scope_1_2_3"
        if channel in {ClaimChannel.MARKETING, ClaimChannel.PRODUCT_LABEL} \
                and decision.qualification < 0.5:
            # An intentionally visible scope mismatch for the rule engine.
            scope_boundary = "scope_1_2"
        relies_on_offsets = claim_type == ClaimType.OFFSET_BASED
        return EnvironmentalClaim(
            claim_id=f"C-{self.asset.symbol}-{self.claim_sequence}",
            firm_symbol=self.asset.symbol,
            day=day,
            communication_date=communication_date,
            channel=channel,
            audience=audience,
            claim_type=claim_type,
            subject=subject,
            asserted_value=asserted,
            unit=unit,
            period_start=period_start,
            period_end=period_end,
            organizational_boundary="consolidated_group",
            operational_boundary=scope_boundary,
            evidence_ids=(evidence.evidence_id,),
            qualification=qualification,
            stated_uncertainty=evidence.standard_error
                * (1.0 if decision.qualification >= 0.5 else 0.25),
            baseline_value=baseline_value,
            target_date=target_date,
            relies_on_offsets=relies_on_offsets,
            offset_disclosed_separately=(not relies_on_offsets
                                         or decision.qualification >= 0.8),
        )
