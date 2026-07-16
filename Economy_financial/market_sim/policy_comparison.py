"""Part H: comparative evaluation of the three State-intervention regimes.

`run_greenwashing_policy_comparison` executes paired replications of the
same economy under each `GreenwashingPolicyRegime`, using common random
numbers: every arm of a replication shares the SAME global market seed and
the SAME `supervision_seed` (so firms, latent environmental trajectories,
corporate strategies, macro shocks, consumer/workforce/investor draws are
identical), while the hub and connector consume their own dedicated policy
streams. Divergence between arms is therefore either the direct effect of
the policy instrument or an endogenous behavioural response to it -- never
an accidental difference in unrelated RNG consumption.

The `PolicyOutcomeEvaluator` is a RESEARCH-ONLY component: it reads the
latent-truth snapshot (`sim._evaluation_truth_by_claim`) strictly after
the simulation has finished. No policy system, regulator or agent ever
receives that dictionary during the run.

Efficiency is deliberately multi-dimensional (Sections 8-9): greenwashing
incidence and severity, detection quality, prevention, greenhushing,
public/firm cost and proportionality, and real-economy outcomes. The
composite `policy_efficiency` score is an EXPERIMENT with configurable,
clearly labelled weights; raw metrics, alternative weight scenarios, a
Pareto frontier and a ranking-stability warning are always reported next
to it so trade-offs are never concealed inside a single number.
"""

from __future__ import annotations

import csv
import math
import random
import statistics
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional, Sequence

from market_sim.constants import (
    EVAL_MATERIALITY_THRESHOLD,
    EVAL_REGULATOR_COST_PER_CASE,
    EVAL_REGULATOR_COST_PER_CONFLICT,
    EVAL_REGULATOR_COST_PER_INVESTIGATION,
    SOCIAL_DISCOUNT_RATE_DEFAULT,
)
from market_sim.environmental_claims import (
    ClaimAudience,
    ClaimChannel,
    ClaimSubject,
    ClaimType,
    EvidenceSource,
)
from market_sim.policy_regimes import GreenwashingPolicyRegime

_LOWER_IS_GREENER = {
    ClaimSubject.SCOPE_1_EMISSIONS,
    ClaimSubject.SCOPE_2_EMISSIONS,
    ClaimSubject.SCOPE_3_EMISSIONS,
    ClaimSubject.WATER_INTENSITY,
    ClaimSubject.POLLUTION_INTENSITY,
    ClaimSubject.BIODIVERSITY_PRESSURE,
    ClaimSubject.NET_ZERO,
}

_AUDIENCE_WEIGHT = {
    ClaimChannel.MARKETING: 0.85,
    ClaimChannel.PRODUCT_LABEL: 0.90,
    ClaimChannel.INVESTOR_COMMUNICATION: 0.75,
    ClaimChannel.SUSTAINABILITY_REPORT: 0.65,
}


def _true_overstatement(claim, truth: float) -> float:
    """Signed greener-than-truth divergence of the LIVE (possibly
    corrected) public value, on a unit-aware scale."""
    raw = claim.asserted_value - truth
    if claim.subject in _LOWER_IS_GREENER:
        raw = -raw
    scale = 1.0 if claim.unit in {"share_0_1", "score_0_1",
                                  "net_emissions_ratio"} \
        else max(abs(truth), 1.0)
    return raw / scale


def _original_overstatement(claim, truth: float) -> float:
    """Signed greener-than-truth divergence of the value as ORIGINALLY
    published (Part I.3: corrections never erase historical misconduct
    from incidence measurement)."""
    raw = claim.historical_asserted_value - truth
    if claim.subject in _LOWER_IS_GREENER:
        raw = -raw
    scale = 1.0 if claim.unit in {"share_0_1", "score_0_1",
                                  "net_emissions_ratio"} \
        else max(abs(truth), 1.0)
    return raw / scale


# --------------------------------------------------------------------------- #
# Research-only outcome evaluator (Section 8)
# --------------------------------------------------------------------------- #
class PolicyOutcomeEvaluator:
    """Computes the Section-8 metric battery from a FINISHED simulation.

    Uses latent truth (and the research-only intent snapshot) strictly
    ex post. Part I.7 metric families and their honest definitions:

    * incidence is measured on ORIGINAL published values (corrections
      never launder history); live-uncorrected and corrected-historical
      counts are reported separately;
    * `precision`/`recall` are SCREENING-CONDITIONED (capacity-selected
      assessed claims only) and are exported under explicit aliases;
      population-level detection recall and coverage are computed against
      every originally-material published claim;
    * exposure is duration-weighted (misleading-claim days,
      exposure-weighted severity, time-to-correction);
    * intent is separated using the quarantined evaluator-only intent
      snapshot: measurement-noise overstatements (no deliberate
      component) vs strategic material overstatements;
    * public costs are reported both undiscounted (accounting ledger) and
      discounted at the configurable EXPERIMENT social discount rate.
    """

    def __init__(self, discount_rate_annual: float =
                 SOCIAL_DISCOUNT_RATE_DEFAULT):
        self.discount_rate_annual = max(0.0, float(discount_rate_annual))

    def _discount(self, day: float) -> float:
        if self.discount_rate_annual <= 0.0:
            return 1.0
        return (1.0 + self.discount_rate_annual) ** (-day / 365.0)

    def evaluate(self, sim: Any) -> dict[str, float]:
        truth = sim._evaluation_truth_by_claim
        supervisor = sim.greenwashing_supervisor
        published = [claim for claim in sim.claim_log
                     if not claim.withdrawn]
        withheld = list(sim._withheld_draft_claims)
        hub = sim.prescreening_hub
        connector = sim.green_data_connector

        # ---- greenwashing outcomes (Part I.7: ORIGINAL values) --------- #
        intent = sim._evaluation_intent_by_claim
        material: list = []                 # Originally material.
        live_material = 0                   # Still materially wrong now.
        corrected_material = 0              # Was material, later fixed.
        severity_weighted = 0.0             # On original values.
        exposure_weighted_severity = 0.0
        discounted_exposure_severity = 0.0
        misleading_claim_days = 0.0
        time_to_correction: list[float] = []
        noise_only = 0
        strategic_material = 0
        calculation_greenwashing = 0
        consumer_exposure = 0
        investor_exposure = 0
        for claim in published:
            true_value = truth.get(claim.claim_id)
            if true_value is None:
                continue
            original = _original_overstatement(claim, true_value)
            live = _true_overstatement(claim, true_value)
            if live >= EVAL_MATERIALITY_THRESHOLD \
                    and not claim.withdrawn:
                live_material += 1
            if original >= EVAL_MATERIALITY_THRESHOLD:
                material.append(claim)
                weight = _AUDIENCE_WEIGHT[claim.channel]
                severity_weighted += original * weight
                days_exposed = claim.exposure_days(sim.days)
                misleading_claim_days += days_exposed
                exposure_weighted_severity += original * weight \
                    * days_exposed
                discounted_exposure_severity += original * weight \
                    * days_exposed * self._discount(claim.day)
                if claim.corrected_day is not None \
                        or claim.withdrawn_day is not None:
                    corrected_material += 1
                    end_day = claim.corrected_day \
                        if claim.corrected_day is not None \
                        else claim.withdrawn_day
                    time_to_correction.append(max(0, end_day - claim.day))
                # Intent separation (research-only snapshot): a material
                # divergence with NO deliberate overstatement component
                # is measurement noise, not strategic conduct.
                if intent.get(claim.claim_id, 0.0) > 0.0:
                    strategic_material += 1
                else:
                    noise_only += 1
                if claim.channel == ClaimChannel.SUSTAINABILITY_REPORT \
                        and claim.claim_type in {ClaimType.QUANTITATIVE,
                                                 ClaimType.COMPARATIVE}:
                    calculation_greenwashing += 1
                if claim.audience in {ClaimAudience.CONSUMERS,
                                      ClaimAudience.GENERAL_PUBLIC,
                                      ClaimAudience.MIXED}:
                    consumer_exposure += 1
                if claim.audience in {ClaimAudience.INVESTORS,
                                      ClaimAudience.PROFESSIONAL_INVESTORS,
                                      ClaimAudience.RETAIL_INVESTORS,
                                      ClaimAudience.MIXED}:
                    investor_exposure += 1
        unsupported_generic = sum(
            1 for claim in published
            if claim.claim_type == ClaimType.QUALITATIVE
            and not claim.qualification)

        assessments = list(supervisor.assessments.values()) \
            if supervisor is not None else []
        abuse_by_firm: dict[str, int] = {}
        benefit_before_detection = 0.0
        detection_delays: list[float] = []
        for assessment in assessments:
            if assessment.confirmed_abuse:
                abuse_by_firm[assessment.firm_symbol] = \
                    abuse_by_firm.get(assessment.firm_symbol, 0) + 1
                benefit_before_detection += assessment.estimated_benefit
                claim = supervisor.claims.get(assessment.claim_id)
                if claim is not None:
                    detection_delays.append(
                        max(0, assessment.day - claim.day))
        repeated_abuse_firms = sum(1 for count in abuse_by_firm.values()
                                   if count >= 2)
        cases = supervisor.cases if supervisor is not None else []
        correction_delays = [
            case.decision_day - case.opened_day for case in cases
            if case.decision_day is not None
            and case.remedy not in {"none", ""}]

        # ---- detection quality --------------------------------------- #
        # Family 1 (Part I.7): SCREENING-CONDITIONED confusion matrix --
        # computed over capacity-selected assessed claims only, on
        # ORIGINAL published values. Overstates system performance by
        # construction (selection), hence the explicit naming and the
        # population-level family below.
        tp = fp = tn = fn = 0
        unresolved = 0
        detected_material_ids: set[str] = set()
        assessed_ids: set[str] = set()
        for assessment in assessments:
            claim = supervisor.claims[assessment.claim_id]
            assessed_ids.add(claim.claim_id)
            true_value = truth.get(claim.claim_id)
            if true_value is None:
                continue
            actually_material = _original_overstatement(
                claim, true_value) >= EVAL_MATERIALITY_THRESHOLD
            if assessment.outcome.value == "prohibited_practice":
                actually_material = True
            if assessment.outcome.value == "inconclusive":
                unresolved += 1
            predicted = assessment.confirmed_abuse
            if predicted and actually_material:
                tp += 1
                detected_material_ids.add(claim.claim_id)
            elif predicted:
                fp += 1
            elif actually_material:
                fn += 1
            else:
                tn += 1
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        specificity = tn / (tn + fp) if tn + fp else 1.0

        # Family 2 (Part I.7): POPULATION-LEVEL detection against every
        # originally-material published claim, whether or not capacity
        # ever selected it for assessment.
        material_ids = {claim.claim_id for claim in material}
        population_detection_recall = (
            len(detected_material_ids & material_ids) / len(material_ids)
            if material_ids else 1.0)
        detection_coverage = (
            len(assessed_ids & material_ids) / len(material_ids)
            if material_ids else 1.0)
        severity_by_id = {}
        for claim in material:
            true_value = truth.get(claim.claim_id)
            severity_by_id[claim.claim_id] = _original_overstatement(
                claim, true_value) * _AUDIENCE_WEIGHT[claim.channel]
        total_severity = sum(severity_by_id.values())
        severity_weighted_detection_recall = (
            sum(severity_by_id[cid]
                for cid in detected_material_ids & material_ids)
            / total_severity if total_severity > 0.0 else 1.0)

        # Queue age, tail backlog and completion times (Part I.7).
        pending_cases = [case for case in cases
                         if case.closed_day is None]
        pending_ages = sorted(sim.days - case.opened_day
                              for case in pending_cases)
        completion_times = [case.closed_day - case.opened_day
                            for case in cases
                            if case.closed_day is not None]
        queue_mean_age = statistics.fmean(pending_ages) \
            if pending_ages else 0.0
        queue_tail_age = pending_ages[
            max(0, int(0.9 * len(pending_ages)) - 1)] \
            if pending_ages else 0.0

        # ---- prevention -------------------------------------------------- #
        prevented_overstatements = 0
        withheld_truthful = 0
        for claim in withheld:
            true_value = truth.get(claim.claim_id)
            if true_value is None:
                continue
            if _true_overstatement(claim, true_value) \
                    >= EVAL_MATERIALITY_THRESHOLD:
                prevented_overstatements += 1
            else:
                withheld_truthful += 1
        company_evidence = [record for record in sim.evidence_log
                            if record.source == EvidenceSource.COMPANY_RECORD]
        evidence_quality = statistics.fmean(
            record.confidence for record in company_evidence) \
            if company_evidence else 0.0
        mandatory_syms = set()
        if sim.venues is not None:
            final_date = sim.date_for_day(sim.days)
            for venue in sim.venues:
                if sim.legal_regime.csrd_in_scope(
                        venue.asset.firm_profile, final_date,
                        venue.asset.workforce.average_employees_365d):
                    mandatory_syms.add(venue.symbol)
        voluntary_published = sum(
            1 for claim in published
            if claim.firm_symbol not in mandatory_syms
            or claim.channel != ClaimChannel.SUSTAINABILITY_REPORT)

        # ---- greenhushing ------------------------------------------------ #
        gap_series = sim.log_greenhushing_gap or [0.0]
        mean_gap = statistics.fmean(gap_series)
        # EXPERIMENT proxy: a fraction of the consumer green premium and
        # of the investor greenium is foregone in proportion to the mean
        # unexpressed truthful performance.
        foregone_consumer_premium = mean_gap \
            * sim.consumer_daily_budget * len(gap_series) * 0.25
        uncommunicated_real_performance = mean_gap

        # ---- costs and proportionality ----------------------------------- #
        state_policy_cost = 0.0
        firm_policy_cost = 0.0
        reporting_delay = 0.0
        if hub is not None:
            state_policy_cost += float(hub.state_cost_dec)
            firm_policy_cost += float(sum(hub.firm_cost_dec.values(),
                                          Decimal("0")))
            if hub.events:
                reporting_delay = statistics.fmean(
                    event.processing_delay_days for event in hub.events)
        if connector is not None:
            state_policy_cost += float(connector.state_cost_dec)
            firm_policy_cost += float(sum(connector.firm_cost_dec.values(),
                                          Decimal("0")))
        conflict_investigations = supervisor.total_conflict_investigations \
            if supervisor is not None else 0
        regulator_time_cost = (len(cases) * EVAL_REGULATOR_COST_PER_CASE
                               + (supervisor.total_investigations
                                  if supervisor is not None else 0)
                               * EVAL_REGULATOR_COST_PER_INVESTIGATION
                               + conflict_investigations
                               * EVAL_REGULATOR_COST_PER_CONFLICT)
        firm_reporting_cost = sum(
            venue.asset.communication_preparation_spend
            + venue.asset.environmental_evidence_spend
            for venue in sim.venues) if sim.venues is not None else 0.0
        sme_burden = 0.0
        if sim.venues is not None:
            for venue in sim.venues:
                if venue.symbol in mandatory_syms:
                    continue
                sme_burden += (venue.asset.communication_preparation_spend
                               + venue.asset.environmental_evidence_spend)
                if hub is not None:
                    sme_burden += float(hub.firm_cost_dec.get(
                        venue.symbol, Decimal("0")))
                if connector is not None:
                    sme_burden += float(connector.firm_cost_dec.get(
                        venue.symbol, Decimal("0")))
        # Part I.5/I.7 -- honest prevention: only revisions that answered
        # a legally material issue count toward "prevented" greenwashing;
        # noise-driven rewrites of already-truthful claims do not.
        meaningful_revisions = hub.meaningful_revisions \
            if hub is not None else 0
        prevented = prevented_overstatements + meaningful_revisions
        cost_per_prevented = (state_policy_cost + firm_policy_cost) \
            / max(1, prevented)
        cost_per_detected = (state_policy_cost + regulator_time_cost) \
            / max(1, tp)
        cyber_risk_events = 0.0
        if connector is not None:
            cyber_risk_events = connector.cyber_incidents \
                + 0.2 * connector.downtime_events

        # Part I.8 -- discounted public cost (EXPERIMENT social discount
        # rate; the undiscounted accounting ledgers are preserved in the
        # metrics alongside). Policy-cost increments come from the daily
        # cumulative series; regulator costs are booked at case opening
        # and at the formal-investigation transition day.
        discounted_public_cost = 0.0
        previous = 0.0
        for index, cumulative in enumerate(sim.log_policy_state_cost):
            increment = max(0.0, cumulative - previous)
            previous = cumulative
            if increment > 0.0:
                discounted_public_cost += increment \
                    * self._discount(index + 1)
        for case in cases:
            discounted_public_cost += EVAL_REGULATOR_COST_PER_CASE \
                * self._discount(case.opened_day)
            investigation_day = next(
                (event_day for event_day, state_name in case.state_history
                 if state_name == "formal_investigation"), None)
            if investigation_day is not None:
                discounted_public_cost += \
                    EVAL_REGULATOR_COST_PER_INVESTIGATION \
                    * self._discount(investigation_day)
            if case.conflict_investigation_day is not None:
                discounted_public_cost += EVAL_REGULATOR_COST_PER_CONFLICT \
                    * self._discount(case.conflict_investigation_day)

        # Part J (Workstream C): conflict-investigation battery.
        conflict_cases = [case for case in cases if case.conflict_case]
        conflict_outcomes = dict(supervisor.conflict_outcomes) \
            if supervisor is not None else {}
        conflict_delays = supervisor.conflict_resolution_delays \
            if supervisor is not None else []
        conflict_pending = sum(
            1 for case in conflict_cases if case.conflict_resolved_day
            is None and case.closed_day is None)

        # Part I.5/I.7 -- hub ITT/TOT split (strategy labels are
        # research-only): participation composition plus
        # treatment-on-the-treated revision rates per strategy.
        hub_participation_rate = 0.0
        hub_noise_flag_share = 0.0
        hub_tot_meaningful_revision_rate = 0.0
        tot_by_strategy = {"honest": 0.0, "adaptive": 0.0,
                           "greenwasher": 0.0}
        if hub is not None:
            eligible_periods = sum(
                item.get("eligible_firm_periods", 0)
                for item in hub.composition.values())
            participating_periods = sum(
                item.get("participating_firm_periods", 0)
                for item in hub.composition.values())
            hub_participation_rate = participating_periods \
                / eligible_periods if eligible_periods else 0.0
            hub_noise_flag_share = hub.noise_flag_events \
                / hub.submissions if hub.submissions else 0.0
            hub_tot_meaningful_revision_rate = hub.meaningful_revisions \
                / hub.submissions if hub.submissions else 0.0
            for strategy, item in hub.composition.items():
                submissions = item.get("submissions", 0)
                if strategy in tot_by_strategy and submissions:
                    tot_by_strategy[strategy] = \
                        item.get("meaningful_revisions", 0) / submissions

        # ---- economic effects -------------------------------------------- #
        consumer_misallocation = statistics.fmean(
            sim.log_consumer_perceived_discrepancy) \
            if sim.log_consumer_perceived_discrepancy else 0.0
        green_welfare = 0.0
        total_revenue = 0.0
        investor_distortion_terms: list[float] = []
        real_investment = 0.0
        gross_emissions = 0.0
        replacement_cost = 0.0
        if sim.venues is not None:
            for venue in sim.venues:
                revenue = sum(venue.log_consumer_revenue)
                total_revenue += revenue
                green_welfare += revenue * venue.asset.true_green_score
                pairs = zip(venue.log_green_score, venue.log_true_score)
                investor_distortion_terms.append(statistics.fmean(
                    abs(disclosed - true) for disclosed, true in pairs))
                real_investment += (
                    venue.asset.real_environmental_investment_spend
                    + (float(venue.policy.total_transition_spend_dec)
                       if venue.policy is not None else 0.0))
                gross_emissions += \
                    venue.asset.environmental_facts.gross_emissions()
                replacement_cost += venue.asset.workforce.replacement_cost
        green_welfare_share = green_welfare / total_revenue \
            if total_revenue > 0.0 else 0.0
        investor_signal_distortion = statistics.fmean(
            investor_distortion_terms) if investor_distortion_terms else 0.0
        subsidy_misallocation = sim.total_subsidies_paid \
            * investor_signal_distortion
        bank = sim.commercial_bank
        bank_misallocation = 0.0
        if bank is not None and sim.esg_regulation is not None \
                and sim.venues is not None:
            primary = sim.venues[0].asset
            bank_misallocation = abs(
                sim.esg_regulation.risk_weight(
                    primary.disclosed_green_score)
                - sim.esg_regulation.risk_weight(
                    primary.true_green_score)) * bank.required_reserves
        employee_trust = statistics.fmean(sim.log_workforce_trust) \
            if sim.log_workforce_trust else 1.0

        return {
            # Greenwashing outcomes (Part I.7: incidence on ORIGINAL
            # published values; corrections never launder history).
            "true_material_overstatements": float(len(material)),
            "original_material_overstatements": float(len(material)),
            "live_uncorrected_material_overstatements": float(
                live_material),
            "corrected_material_claims": float(corrected_material),
            "severity_weighted_greenwashing": severity_weighted,
            "misleading_claim_days": misleading_claim_days,
            "exposure_weighted_severity": exposure_weighted_severity,
            "discounted_exposure_weighted_severity":
                discounted_exposure_severity,
            "time_to_correction_mean": statistics.fmean(
                time_to_correction) if time_to_correction else 0.0,
            "noise_only_overstatements": float(noise_only),
            "strategic_material_overstatements": float(strategic_material),
            "strategic_share_of_material": (
                strategic_material / len(material) if material else 0.0),
            "repeated_abuse_firms": float(repeated_abuse_firms),
            "calculation_greenwashing": float(calculation_greenwashing),
            "unsupported_generic_claims": float(unsupported_generic),
            "mean_days_to_correction": statistics.fmean(correction_delays)
            if correction_delays else 0.0,
            "benefit_before_detection": benefit_before_detection,
            "consumer_exposure": float(consumer_exposure),
            "investor_exposure": float(investor_exposure),
            "published_claims": float(len(published)),
            # Detection quality -- screening-conditioned family
            # (capacity-selected assessed claims only; see Part I.7).
            "true_positives": float(tp),
            "false_positives": float(fp),
            "true_negatives": float(tn),
            "false_negatives": float(fn),
            "precision": precision,
            "recall": recall,
            "screening_conditioned_precision": precision,
            "screening_conditioned_recall": recall,
            "false_positive_rate_assessed": (
                fp / (fp + tn) if fp + tn else 0.0),
            "specificity": specificity,
            # Detection quality -- population-level family (all
            # originally-material published claims).
            "population_detection_recall": population_detection_recall,
            "detection_coverage": detection_coverage,
            "severity_weighted_detection_recall":
                severity_weighted_detection_recall,
            "backlog_pending_cases": float(len(pending_cases)),
            "queue_mean_age_days": queue_mean_age,
            "queue_tail_age_days_p90": float(queue_tail_age),
            "case_completion_days_mean": statistics.fmean(
                completion_times) if completion_times else 0.0,
            "unresolved_uncertainty": float(unresolved),
            # Part J (Workstream C): conflict-investigation family.
            "conflict_cases_opened": float(len(conflict_cases)),
            "conflict_investigations": float(conflict_investigations),
            "conflict_pending_unresolved": float(conflict_pending),
            "conflict_resolution_delay_mean": statistics.fmean(
                conflict_delays) if conflict_delays else 0.0,
            "conflict_confirmed_firm_claim": float(
                conflict_outcomes.get("confirmed_firm_claim", 0)),
            "conflict_register_corrected": float(
                conflict_outcomes.get("external_register_corrected", 0)),
            "conflict_claim_corrected": float(
                conflict_outcomes.get("claim_corrected", 0)),
            "conflict_dismissed_unresolved": float(
                conflict_outcomes.get("dismissed_unresolved", 0)),
            "conflict_escalated_corroborated": float(
                conflict_outcomes.get("escalated_corroborated", 0)),
            "detection_delay_days": statistics.fmean(detection_delays)
            if detection_delays else 0.0,
            "correction_delay_days": statistics.fmean(correction_delays)
            if correction_delays else 0.0,
            # Prevention.
            "prepublication_revisions": float(
                hub.revisions if hub is not None else 0),
            "prepublication_meaningful_revisions": float(
                meaningful_revisions),
            "prepublication_noise_flag_share": hub_noise_flag_share,
            "hub_participation_rate": hub_participation_rate,
            "hub_tot_meaningful_revision_rate":
                hub_tot_meaningful_revision_rate,
            "hub_tot_revision_rate_honest": tot_by_strategy["honest"],
            "hub_tot_revision_rate_adaptive": tot_by_strategy["adaptive"],
            "hub_tot_revision_rate_greenwasher":
                tot_by_strategy["greenwasher"],
            "prepublication_withheld_overstatements": float(
                prevented_overstatements),
            "evidence_quality_mean": evidence_quality,
            "manual_overrides": float(sum(
                connector.manual_overrides.values())
                if connector is not None else 0),
            "voluntary_claims_published": float(voluntary_published),
            "connector_active_source_share": (
                sum(connector.active_sources(venue.symbol)
                    for venue in sim.venues)
                / max(1, len(sim.venues)
                      * len(connector.parameters.sources))
                if connector is not None and sim.venues is not None
                else 0.0),
            "recurrence_after_feedback": float(
                hub.repeat_issue_count if hub is not None else 0),
            # Greenhushing.
            "mean_greenhushing_gap": mean_gap,
            "withheld_truthful_claims": float(withheld_truthful),
            "voluntary_reporting_declines": float(
                hub.declined_participations if hub is not None else 0),
            "foregone_consumer_premium": foregone_consumer_premium,
            "uncommunicated_real_performance":
                uncommunicated_real_performance,
            # Costs and proportionality (undiscounted accounting ledger
            # plus the Part I.8 discounted comparison value).
            "state_policy_cost": state_policy_cost,
            "regulator_time_cost": regulator_time_cost,
            "discounted_total_public_cost": discounted_public_cost,
            "discount_rate_annual": self.discount_rate_annual,
            "firm_policy_cost": firm_policy_cost,
            "firm_reporting_cost": firm_reporting_cost,
            "sme_burden": sme_burden,
            "cost_per_prevented_material_claim": cost_per_prevented,
            "cost_per_detected_material_claim": cost_per_detected,
            "mean_reporting_delay_days": reporting_delay,
            "privacy_cyber_incidents": cyber_risk_events,
            # Economic effects.
            "consumer_perceived_misallocation": consumer_misallocation,
            "green_welfare_share": green_welfare_share,
            "investor_signal_distortion": investor_signal_distortion,
            "employee_trust_mean": employee_trust,
            "turnover_replacement_cost": replacement_cost,
            "subsidy_misallocation": subsidy_misallocation,
            "bank_benefit_misallocation": bank_misallocation,
            "real_environmental_investment": real_investment,
            "gross_emissions_final": gross_emissions,
        }


# --------------------------------------------------------------------------- #
# Multi-criteria score (Section 9) -- all weights EXPERIMENT
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PolicyScoreWeights:
    """EXPERIMENT weights of the composite policy-efficiency score."""

    name: str = "default_experiment"
    greenwashing_reduction: float = 1.0
    severity_weighted_harm_avoided: float = 1.0
    accuracy_gain: float = 0.8
    reporting_quality_gain: float = 0.6
    public_cost: float = 0.8
    firm_compliance_cost: float = 0.6
    false_positive_cost: float = 0.7
    greenhushing_cost: float = 0.8
    reporting_participation_loss: float = 0.6
    privacy_and_cyber_risk_cost: float = 0.5

    def to_dict(self) -> dict[str, float]:
        return {key: value for key, value in asdict(self).items()
                if key != "name"}


DEFAULT_WEIGHT_SCENARIOS: tuple[PolicyScoreWeights, ...] = (
    PolicyScoreWeights(),
    PolicyScoreWeights(name="cost_focused", public_cost=1.6,
                       firm_compliance_cost=1.2),
    PolicyScoreWeights(name="accuracy_focused", accuracy_gain=1.8,
                       false_positive_cost=1.2),
    PolicyScoreWeights(name="sme_protective", firm_compliance_cost=1.6,
                       reporting_participation_loss=1.4,
                       greenhushing_cost=1.2),
    PolicyScoreWeights(name="anti_greenhushing", greenhushing_cost=1.8,
                       reporting_participation_loss=1.5),
)

# Criterion -> (metric key, direction). +1 = higher metric is better for
# the criterion; -1 = higher metric is worse (a cost).
#
# Part I.7 repairs (red-team §18): the two greenwashing criteria now
# measure DISTINCT harm dimensions -- incidence of originally-material
# claims vs duration-weighted exposure severity -- instead of two nearly
# identical restatements of the same count with swapped labels. Accuracy
# combines screening-conditioned precision with POPULATION detection
# recall (selection-flattered recall no longer enters the score). The
# public-cost criterion uses the discounted comparison value; the
# undiscounted ledgers remain in the metrics. The greenhushing index
# still mixes a gap share with a scaled count; this is an EXPERIMENT
# aggregation documented as such.
_CRITERION_MAP: dict[str, tuple[str, int]] = {
    "greenwashing_reduction": ("original_material_overstatements", -1),
    "severity_weighted_harm_avoided": ("exposure_weighted_severity", -1),
    "accuracy_gain": ("accuracy_index", +1),
    "reporting_quality_gain": ("evidence_quality_mean", +1),
    "public_cost": ("comparison_public_cost", -1),
    "firm_compliance_cost": ("total_firm_cost", -1),
    "false_positive_cost": ("false_positives", -1),
    "greenhushing_cost": ("greenhushing_index", -1),
    "reporting_participation_loss": ("voluntary_claims_published", +1),
    "privacy_and_cyber_risk_cost": ("privacy_cyber_incidents", -1),
}


def _derive_score_inputs(metrics: Mapping[str, float]) -> dict[str, float]:
    """Add the composite intermediate quantities used by the score.

    Uses `.get` fallbacks so synthetic metric dictionaries (tests,
    external users) remain valid without the full evaluator battery.
    """
    result = dict(metrics)
    population_recall = metrics.get("population_detection_recall",
                                    metrics.get("recall", 1.0))
    result["accuracy_index"] = 0.5 * (metrics["precision"]
                                      + population_recall)
    result["total_public_cost"] = metrics["state_policy_cost"] \
        + metrics["regulator_time_cost"]
    result["comparison_public_cost"] = metrics.get(
        "discounted_total_public_cost", result["total_public_cost"])
    result["total_firm_cost"] = metrics["firm_policy_cost"] \
        + metrics["firm_reporting_cost"]
    result["greenhushing_index"] = metrics["mean_greenhushing_gap"] \
        + 0.02 * metrics["withheld_truthful_claims"]
    result.setdefault("original_material_overstatements",
                      metrics.get("true_material_overstatements", 0.0))
    result.setdefault("exposure_weighted_severity",
                      metrics.get("severity_weighted_greenwashing", 0.0))
    return result


def composite_scores(mean_metrics: Mapping[str, Mapping[str, float]],
                     weights: PolicyScoreWeights) -> dict[str, float]:
    """Min-max-normalized weighted score per regime (EXPERIMENT).

    Normalization runs across the regimes under comparison, so the score
    is meaningful only WITHIN one comparison run -- it is a ranking
    device, not an absolute welfare number.
    """
    inputs = {regime: _derive_score_inputs(metrics)
              for regime, metrics in mean_metrics.items()}
    scores = {regime: 0.0 for regime in inputs}
    weight_map = weights.to_dict()
    for criterion, (metric_key, direction) in _CRITERION_MAP.items():
        values = {regime: data[metric_key]
                  for regime, data in inputs.items()}
        low, high = min(values.values()), max(values.values())
        span = high - low
        for regime, value in values.items():
            if span <= 1e-12:
                normalized = 0.5
            else:
                normalized = (value - low) / span
            if direction < 0:
                normalized = 1.0 - normalized
            scores[regime] += weight_map[criterion] * normalized
    return scores


def pareto_frontier(mean_metrics: Mapping[str, Mapping[str, float]]) \
        -> set[str]:
    """Non-dominated regimes on the four headline axes: severity-weighted
    greenwashing (min), total cost (min), greenhushing index (min),
    accuracy index (max)."""
    inputs = {regime: _derive_score_inputs(metrics)
              for regime, metrics in mean_metrics.items()}
    axes = (("severity_weighted_greenwashing", -1),
            ("total_public_cost", -1),
            ("greenhushing_index", -1),
            ("accuracy_index", +1))

    def dominates(a: Mapping[str, float], b: Mapping[str, float]) -> bool:
        at_least_as_good = all(
            (a[key] <= b[key] if direction < 0 else a[key] >= b[key])
            for key, direction in axes)
        strictly_better = any(
            (a[key] < b[key] if direction < 0 else a[key] > b[key])
            for key, direction in axes)
        return at_least_as_good and strictly_better

    frontier = set()
    for regime, data in inputs.items():
        if not any(dominates(other, data)
                   for other_regime, other in inputs.items()
                   if other_regime != regime):
            frontier.add(regime)
    return frontier


# --------------------------------------------------------------------------- #
# Comparison runner (Section 7)
# --------------------------------------------------------------------------- #
@dataclass
class RegimeRunResult:
    regime: str
    replication: int
    market_seed: int
    supervision_seed: int
    metrics: dict[str, float]


@dataclass
class PolicyComparisonReport:
    rows: list[RegimeRunResult]
    mean_metrics: dict[str, dict[str, float]]
    ci_halfwidth: dict[str, dict[str, float]]
    scores_by_scenario: dict[str, dict[str, float]]
    rankings_by_scenario: dict[str, list[str]]
    pareto_regimes: set[str]
    warnings: list[str]
    conclusions: dict[str, str]
    # Part I (P0-2): paired inference vs the first (baseline) regime.
    # paired_statistics[metric][regime] holds: n, mean_diff (baseline -
    # regime, positive = policy better for a lower-is-better metric),
    # sd_diff, ci95_halfwidth, prob_improvement.
    paired_statistics: dict[str, dict[str, dict[str, float]]] = \
        field(default_factory=dict)
    replications: int = 0

    def to_summary_text(self) -> str:
        lines = ["Greenwashing policy-regime comparison (EXPERIMENT)"]
        lines.append(f"  replications: {self.replications} (paired, "
                     "common random numbers within replication)")
        for scenario, ranking in self.rankings_by_scenario.items():
            lines.append(f"  ranking[{scenario}]: {' > '.join(ranking)}")
        lines.append(f"  Pareto-efficient: {sorted(self.pareto_regimes)}")
        for metric, per_regime in self.paired_statistics.items():
            for regime, stats in per_regime.items():
                lines.append(
                    f"  paired[{metric}] baseline-vs-{regime}: "
                    f"diff={stats['mean_diff']:+.3f} "
                    f"sd={stats['sd_diff']:.3f} "
                    f"ci95=+/-{stats['ci95_halfwidth']:.3f} "
                    f"P(improve)={stats['prob_improvement']:.0%} "
                    f"(n={int(stats['n'])})")
        for warning in self.warnings:
            lines.append(f"  WARNING: {warning}")
        for key, value in self.conclusions.items():
            lines.append(f"  {key}: {value}")
        return "\n".join(lines)


# Headline lower-is-better metrics for paired inference (P0-2). The
# baseline for differences is the FIRST regime passed to the runner.
PAIRED_STAT_METRICS: tuple[str, ...] = (
    "severity_weighted_greenwashing",
    "original_material_overstatements",
    "exposure_weighted_severity",
    "mean_greenhushing_gap",
)


def run_greenwashing_policy_comparison(
        base_config: Optional[Mapping[str, Any]] = None,
        regimes: Sequence[GreenwashingPolicyRegime] = (
            GreenwashingPolicyRegime.CURRENT_EU_SUPERVISION,
            GreenwashingPolicyRegime.SME_ALGORITHMIC_PRESCREENING,
            GreenwashingPolicyRegime.CERTIFIED_GREEN_DATA_CONNECTOR,
        ),
        replications: int = 3,
        common_seed: int = 42,
        weight_scenarios: Sequence[PolicyScoreWeights] =
        DEFAULT_WEIGHT_SCENARIOS,
        csv_path: Optional[str] = None,
        dashboard_path: Optional[str] = None,
        discount_rate: float = SOCIAL_DISCOUNT_RATE_DEFAULT) \
        -> PolicyComparisonReport:
    """Paired-replication comparison with common random numbers.

    Every arm of replication ``r`` seeds the global market RNG with
    ``common_seed + 1000 * r`` and uses the identical supervision seed, so
    initial firms, latent trajectories, strategies, macro shocks and the
    consumer/workforce/investor populations are the same; only the State
    intervention mechanism (and its dedicated policy RNG streams) differs.
    """
    from market_sim.simulation import Simulation   # Local: avoid cycles.

    config = dict(base_config or {})
    config.setdefault("num_traders", 30)
    config.setdefault("num_manipulators", 0)
    config.setdefault("enable_credit", False)
    config.setdefault("enable_esg", True)
    config.setdefault("days", 365)
    config["enable_greenwashing_supervision"] = True
    base_supervision_seed = int(config.pop("supervision_seed", 104729))

    evaluator = PolicyOutcomeEvaluator(discount_rate_annual=discount_rate)
    rows: list[RegimeRunResult] = []
    for replication in range(replications):
        # Part I (P0-2) deterministic seed schedule: every replication
        # draws an INDEPENDENT full stochastic environment (market AND
        # supervision/claims/consumer/workforce layers), while all policy
        # arms inside one replication share both seeds exactly (common
        # random numbers). The old runner held the supervision seed fixed
        # across replications, which made every "replication" repeat the
        # identical claims process and produced degenerate (zero-variance)
        # confidence intervals -- red-team finding P0-2.
        market_seed = common_seed + 1000 * replication
        replication_supervision_seed = base_supervision_seed \
            + 7919 * replication
        for regime in regimes:
            regime = GreenwashingPolicyRegime(regime)
            random.seed(market_seed)
            sim = Simulation(
                supervision_seed=replication_supervision_seed,
                greenwashing_policy_regime=regime, **config)
            sim.run()
            metrics = evaluator.evaluate(sim)
            rows.append(RegimeRunResult(
                regime=regime.value, replication=replication,
                market_seed=market_seed,
                supervision_seed=replication_supervision_seed,
                metrics=metrics))

    regime_names = [GreenwashingPolicyRegime(regime).value
                    for regime in regimes]
    metric_keys = sorted(rows[0].metrics.keys()) if rows else []
    mean_metrics: dict[str, dict[str, float]] = {}
    ci_halfwidth: dict[str, dict[str, float]] = {}
    for name in regime_names:
        samples = [row.metrics for row in rows if row.regime == name]
        means, cis = {}, {}
        for key in metric_keys:
            values = [sample[key] for sample in samples]
            means[key] = statistics.fmean(values)
            if len(values) > 1:
                sd = statistics.stdev(values)
                cis[key] = 1.96 * sd / math.sqrt(len(values))
            else:
                cis[key] = 0.0
        mean_metrics[name] = means
        ci_halfwidth[name] = cis

    scores_by_scenario: dict[str, dict[str, float]] = {}
    rankings_by_scenario: dict[str, list[str]] = {}
    for weights in weight_scenarios:
        scores = composite_scores(mean_metrics, weights)
        scores_by_scenario[weights.name] = scores
        rankings_by_scenario[weights.name] = sorted(
            scores, key=scores.get, reverse=True)

    pareto = pareto_frontier(mean_metrics)
    warnings: list[str] = []
    winners = {ranking[0] for ranking in rankings_by_scenario.values()}
    if len(winners) > 1:
        warnings.append(
            "The identity of the 'best' regime changes across reasonable "
            f"weight scenarios ({sorted(winners)}); no single regime is "
            "robustly superior under the tested weights.")

    # Part I (P0-2): paired inference vs the first (baseline) regime.
    baseline_name = regime_names[0]
    paired_statistics: dict[str, dict[str, dict[str, float]]] = {}
    degenerate = replications > 1
    for metric in PAIRED_STAT_METRICS:
        if not rows or metric not in rows[0].metrics:
            continue
        base_series = [row.metrics[metric] for row in rows
                       if row.regime == baseline_name]
        per_regime: dict[str, dict[str, float]] = {}
        for name in regime_names[1:]:
            series = [row.metrics[metric] for row in rows
                      if row.regime == name]
            diffs = [b - x for b, x in zip(base_series, series)]
            n = len(diffs)
            mean_diff = statistics.fmean(diffs) if diffs else 0.0
            sd_diff = statistics.stdev(diffs) if n > 1 else 0.0
            ci95 = 1.96 * sd_diff / math.sqrt(n) if n > 1 else 0.0
            per_regime[name] = {
                "n": float(n), "mean_diff": mean_diff,
                "sd_diff": sd_diff, "ci95_halfwidth": ci95,
                "prob_improvement": (sum(d > 0 for d in diffs) / n)
                if n else 0.0,
            }
            if sd_diff > 1e-9:
                degenerate = False
        paired_statistics[metric] = per_regime
    if replications > 1 and degenerate:
        warnings.append(
            "Insufficient effective variation across replications: all "
            "paired differences have ~zero variance. Check that the "
            "stochastic environment truly varies (seed schedule) before "
            "interpreting confidence intervals.")
    elif replications < 2:
        warnings.append(
            "Single replication: no variance estimate is possible; "
            "confidence intervals and probabilities of improvement are "
            "not statistically meaningful.")

    def _argmin(key: str) -> str:
        return min(mean_metrics, key=lambda name: mean_metrics[name][key])

    def _argmax(key: str) -> str:
        return max(mean_metrics, key=lambda name: mean_metrics[name][key])

    derived = {name: _derive_score_inputs(metrics)
               for name, metrics in mean_metrics.items()}
    conclusions = {
        "minimizes_greenwashing":
            _argmin("severity_weighted_greenwashing"),
        "most_accurate": max(
            derived, key=lambda name: derived[name]["accuracy_index"]),
        "least_costly": min(
            derived, key=lambda name: derived[name]["total_public_cost"]
            + derived[name]["total_firm_cost"]),
        "best_sme_protection": _argmin("sme_burden"),
        "minimizes_greenhushing": min(
            derived,
            key=lambda name: derived[name]["greenhushing_index"]),
        "hybrid_note": (
            "hybrid arm included in this comparison"
            if GreenwashingPolicyRegime
            .HYBRID_PRESCREENING_AND_CONNECTOR.value in mean_metrics
            else "hybrid arm not run; add "
            "HYBRID_PRESCREENING_AND_CONNECTOR to `regimes` to test "
            "whether a combined implementation is Pareto-superior"),
    }
    for scenario, ranking in rankings_by_scenario.items():
        conclusions[f"best_under_{scenario}"] = ranking[0]

    report = PolicyComparisonReport(
        rows=rows, mean_metrics=mean_metrics, ci_halfwidth=ci_halfwidth,
        scores_by_scenario=scores_by_scenario,
        rankings_by_scenario=rankings_by_scenario,
        pareto_regimes=pareto, warnings=warnings,
        conclusions=conclusions,
        paired_statistics=paired_statistics,
        replications=replications)
    if csv_path:
        export_policy_comparison_csv(report, csv_path)
    if dashboard_path:
        plot_policy_comparison_dashboard(report, dashboard_path)
    return report


# --------------------------------------------------------------------------- #
# Part I.8: horizon grid and reduced-form global sensitivity interface
# --------------------------------------------------------------------------- #
@dataclass
class HorizonGridResult:
    """Rankings across an explicit horizon grid (Part I.8). A policy must
    never be presented as universally superior when the winner changes
    with horizon or discounting."""

    reports: dict[int, PolicyComparisonReport]
    winners_by_horizon: dict[int, str]
    stable_default_winner: bool
    discount_rate: float

    def to_summary_text(self) -> str:
        lines = [f"Horizon grid (discount rate "
                 f"{self.discount_rate:.2%}/yr, EXPERIMENT):"]
        for horizon, winner in sorted(self.winners_by_horizon.items()):
            lines.append(f"  {horizon:>5}d default-weight winner: {winner}")
        lines.append(
            "  conclusion stability across horizons: "
            + ("STABLE" if self.stable_default_winner
               else "UNSTABLE -- report horizon-conditional results only"))
        return "\n".join(lines)


def run_horizon_grid(
        base_config: Optional[Mapping[str, Any]] = None,
        horizons: Sequence[int] = (120, 365, 1000, 2000),
        regimes: Sequence[GreenwashingPolicyRegime] = (
            GreenwashingPolicyRegime.CURRENT_EU_SUPERVISION,
            GreenwashingPolicyRegime.SME_ALGORITHMIC_PRESCREENING,
            GreenwashingPolicyRegime.CERTIFIED_GREEN_DATA_CONNECTOR,
        ),
        replications: int = 2,
        common_seed: int = 42,
        discount_rate: float = SOCIAL_DISCOUNT_RATE_DEFAULT) \
        -> HorizonGridResult:
    """Runs the paired comparison over an explicit horizon grid."""
    reports: dict[int, PolicyComparisonReport] = {}
    winners: dict[int, str] = {}
    for horizon in horizons:
        config = dict(base_config or {})
        config["days"] = int(horizon)
        report = run_greenwashing_policy_comparison(
            config, regimes=regimes, replications=replications,
            common_seed=common_seed, discount_rate=discount_rate)
        reports[int(horizon)] = report
        winners[int(horizon)] = report.rankings_by_scenario[
            "default_experiment"][0]
    return HorizonGridResult(
        reports=reports, winners_by_horizon=winners,
        stable_default_winner=len(set(winners.values())) == 1,
        discount_rate=discount_rate)


# Default EXPERIMENT parameter space for the reduced-form sensitivity
# design. Ranges are plausibility envelopes, not empirical estimates.
SENSITIVITY_PARAMETER_SPACE: dict[str, tuple[float, float]] = {
    "sanction_scale_multiple": (0.5, 3.0),
    "evidence_request_capacity": (5, 40),
    "investigation_capacity": (2, 12),
    "hub_strictness": (0.10, 0.95),
    "hub_noise": (0.0, 0.50),
    "connector_mismatch_probability": (0.0, 0.10),
    "connector_register_error_probability": (0.0, 0.05),
    "regulatory_strictness": (0.0, 1.0),
    "consumer_preference_scale": (0.5, 1.5),
    "discount_rate": (0.0, 0.07),
    "horizon_days": (120, 730),
}


def latin_hypercube_samples(space: Mapping[str, tuple[float, float]],
                            samples: int,
                            rng: random.Random) -> list[dict[str, float]]:
    """Stdlib Latin-hypercube design: one stratified draw per bin per
    dimension, independently permuted across dimensions."""
    columns: dict[str, list[float]] = {}
    for name, (low, high) in space.items():
        points = [(index + rng.random()) / samples
                  for index in range(samples)]
        rng.shuffle(points)
        columns[name] = [low + point * (high - low) for point in points]
    return [{name: columns[name][index] for name in space}
            for index in range(samples)]


@dataclass
class SensitivityResult:
    """Reduced-form global sensitivity output (Part I.8). One paired
    comparison per LHS sample with a single replication -- a documented
    computational compromise: it explores parameter space breadth, not
    within-sample stochastic variance."""

    rows: list[dict[str, Any]]
    winner_counts: dict[str, int]

    def to_summary_text(self) -> str:
        lines = ["Sensitivity analysis (LHS, reduced-form, EXPERIMENT):"]
        total = max(1, len(self.rows))
        for winner, count in sorted(self.winner_counts.items(),
                                    key=lambda kv: -kv[1]):
            lines.append(f"  {winner}: wins {count}/{total} samples")
        if len(self.winner_counts) > 1:
            lines.append(
                "  ranking is PARAMETER-SENSITIVE: no regime is robustly "
                "superior across the sampled space.")
        return "\n".join(lines)


def run_sensitivity_analysis(
        base_config: Optional[Mapping[str, Any]] = None,
        regimes: Sequence[GreenwashingPolicyRegime] = (
            GreenwashingPolicyRegime.CURRENT_EU_SUPERVISION,
            GreenwashingPolicyRegime.SME_ALGORITHMIC_PRESCREENING,
            GreenwashingPolicyRegime.CERTIFIED_GREEN_DATA_CONNECTOR,
        ),
        samples: int = 8,
        seed: int = 7,
        parameter_space: Optional[Mapping[str, tuple[float, float]]]
        = None) -> SensitivityResult:
    """Latin-hypercube sensitivity sweep over the Part I.8 levers:
    sanction scale, enforcement capacity, hub strictness/noise, connector
    failure rates, regulatory strictness (greenhushing burden), consumer
    responsiveness, discount rate and horizon."""
    from dataclasses import replace as dataclass_replace
    from market_sim.greenwashing_supervision import SupervisionParameters
    from market_sim.policy_regimes import (ConnectorParameters,
                                           PrescreeningParameters)

    space = dict(parameter_space or SENSITIVITY_PARAMETER_SPACE)
    rng = random.Random(seed)
    design = latin_hypercube_samples(space, samples, rng)
    rows: list[dict[str, Any]] = []
    winner_counts: dict[str, int] = {}
    for index, sample in enumerate(design):
        config = dict(base_config or {})
        config.setdefault("num_traders", 8)
        config.setdefault("num_manipulators", 0)
        config.setdefault("enable_credit", False)
        config.setdefault("enable_esg", True)
        config["days"] = int(round(sample.get("horizon_days",
                                              config.get("days", 365))))
        config["regulatory_strictness"] = sample.get(
            "regulatory_strictness", 0.55)
        config["consumer_preference_scale"] = sample.get(
            "consumer_preference_scale", 1.0)
        config["supervision_parameters"] = SupervisionParameters(
            evidence_request_capacity=int(round(sample.get(
                "evidence_request_capacity", 20))),
            investigation_capacity=int(round(sample.get(
                "investigation_capacity", 5))),
            sim_turnover_balance_multiple=sample.get(
                "sanction_scale_multiple", 1.5))
        config["prescreening_parameters"] = dataclass_replace(
            PrescreeningParameters(),
            strictness=sample.get("hub_strictness", 0.5),
            noise=sample.get("hub_noise", 0.08))
        config["connector_parameters"] = ConnectorParameters(
            mismatch_probability=sample.get(
                "connector_mismatch_probability", 0.02),
            register_error_probability=sample.get(
                "connector_register_error_probability", 0.01))
        report = run_greenwashing_policy_comparison(
            config, regimes=regimes, replications=1,
            common_seed=1000 + index,
            discount_rate=sample.get("discount_rate",
                                     SOCIAL_DISCOUNT_RATE_DEFAULT))
        winner = report.rankings_by_scenario["default_experiment"][0]
        winner_counts[winner] = winner_counts.get(winner, 0) + 1
        row: dict[str, Any] = {"sample": index, "winner": winner}
        row.update(sample)
        for name, metrics in report.mean_metrics.items():
            row[f"{name}__severity"] = metrics[
                "severity_weighted_greenwashing"]
            row[f"{name}__greenhushing"] = metrics["mean_greenhushing_gap"]
        rows.append(row)
    return SensitivityResult(rows=rows, winner_counts=winner_counts)


def export_policy_comparison_csv(report: PolicyComparisonReport,
                                 csv_path: str) -> None:
    """One row per regime and replication (Section 10, output 1)."""
    if not report.rows:
        return
    metric_keys = sorted(report.rows[0].metrics.keys())
    default_scores = report.scores_by_scenario.get(
        "default_experiment", {})
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["policy_regime", "replication", "market_seed",
                         "supervision_seed"] + metric_keys
                        + ["composite_score_default_experiment",
                           "pareto_efficient"])
        for row in report.rows:
            writer.writerow(
                [row.regime, row.replication, row.market_seed,
                 row.supervision_seed]
                + [row.metrics[key] for key in metric_keys]
                + [default_scores.get(row.regime, ""),
                   row.regime in report.pareto_regimes])
    print(f"Policy-regime comparison exported to '{csv_path}'.")


def plot_policy_comparison_dashboard(report: PolicyComparisonReport,
                                     output_path: str) -> None:
    """Comparative dashboard (Section 10, output 7)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    regimes = list(report.mean_metrics.keys())
    short = {name: name.replace("_", "\n") for name in regimes}
    panels = [
        ("Greenwashing incidence", "true_material_overstatements", None),
        ("Severity-weighted greenwashing",
         "severity_weighted_greenwashing", None),
        ("Precision / recall", "precision", "recall"),
        ("State + regulator cost", "state_policy_cost",
         "regulator_time_cost"),
        ("Firm costs", "firm_policy_cost", "firm_reporting_cost"),
        ("Greenhushing gap", "mean_greenhushing_gap", None),
        ("Voluntary participation", "voluntary_claims_published", None),
        ("Investigation load (cases proxy)", "regulator_time_cost", None),
        ("Consumer green welfare share", "green_welfare_share", None),
        ("Investor signal distortion", "investor_signal_distortion", None),
        ("Workforce trust / turnover cost", "employee_trust_mean",
         "turnover_replacement_cost"),
        ("Real environmental investment",
         "real_environmental_investment", None),
    ]
    fig, axes = plt.subplots(5, 3, figsize=(16, 22))
    flat = axes.flatten()
    for ax in flat[len(panels) + 1:]:
        ax.axis("off")
    for ax, (title, key_a, key_b) in zip(flat, panels):
        positions = range(len(regimes))
        values = [report.mean_metrics[name][key_a] for name in regimes]
        errors = [report.ci_halfwidth[name][key_a] for name in regimes]
        ax.bar([p - 0.2 for p in positions], values, width=0.4,
               yerr=errors, capsize=3, label=key_a, color="#2ca02c")
        if key_b is not None:
            values_b = [report.mean_metrics[name][key_b]
                        for name in regimes]
            errors_b = [report.ci_halfwidth[name][key_b]
                        for name in regimes]
            ax.bar([p + 0.2 for p in positions], values_b, width=0.4,
                   yerr=errors_b, capsize=3, label=key_b,
                   color="#1f77b4")
            ax.legend(fontsize=7)
        ax.set_xticks(list(positions))
        ax.set_xticklabels([short[name] for name in regimes], fontsize=7)
        ax.set_title(title, fontsize=10, fontweight="bold")
        ax.grid(True, linestyle=":", alpha=0.5)
    # Dedicated panel: composite scores per scenario + Pareto flags.
    ax = flat[len(panels)]
    scenario_names = list(report.scores_by_scenario.keys())
    width = 0.8 / max(1, len(scenario_names))
    for index, scenario in enumerate(scenario_names):
        scores = report.scores_by_scenario[scenario]
        ax.bar([p + index * width for p in range(len(regimes))],
               [scores[name] for name in regimes], width=width,
               label=scenario)
    ax.set_xticks([p + 0.4 for p in range(len(regimes))])
    labels = [short[name] + ("\n(Pareto)" if name in report.pareto_regimes
                             else "") for name in regimes]
    ax.set_xticklabels(labels, fontsize=7)
    ax.set_title("Composite policy efficiency (EXPERIMENT weights)",
                 fontsize=10, fontweight="bold")
    ax.legend(fontsize=6)
    ax.grid(True, linestyle=":", alpha=0.5)
    fig.suptitle(
        "Three-regime greenwashing policy comparison -- all composite "
        "weights are EXPERIMENT settings; raw metrics govern",
        fontsize=13, fontweight="bold")
    plt.tight_layout(rect=(0, 0, 1, 0.97))
    plt.savefig(output_path, dpi=200)
    plt.close(fig)
    print(f"Policy comparison dashboard saved as '{output_path}'.")
