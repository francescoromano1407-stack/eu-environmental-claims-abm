"""Information-constrained consumer demand and external product ledger.

Consumers observe communications, linked evidence and published regulatory
signals.  They never read ``EnvironmentalFactVector``.  Demand is a
budget-constrained logit allocation, so perceived claim/evidence divergence
reduces purchases while greenhushing merely removes part of the green premium.
All preference and cost coefficients are ``STYLIZATION`` values.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import random
from typing import Any, Iterable

from market_sim.environmental_claims import ClaimSubject


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return min(upper, max(lower, float(value)))


@dataclass(frozen=True)
class ConsumerSegment:
    name: str
    population_share: float
    attention: float
    environmental_preference: float
    sophistication: float
    memory: float
    price_sensitivity: float = 0.20


DEFAULT_CONSUMER_SEGMENTS = (
    ConsumerSegment("indifferent", 0.30, 0.15, 0.10, 0.20, 0.15),
    ConsumerSegment("mainstream", 0.35, 0.40, 0.40, 0.40, 0.45),
    ConsumerSegment("green_attentive", 0.25, 0.80, 1.00, 0.70, 0.70),
    ConsumerSegment("expert", 0.10, 0.95, 0.80, 0.95, 0.85),
)


@dataclass
class ConsumerBelief:
    perceived_score: float = 0.0
    perceived_discrepancy: float = 0.0
    controversy: float = 0.0
    visibility: float = 0.0
    last_updated_day: int = 0


@dataclass(frozen=True)
class ConsumerFirmFlow:
    day: int
    firm_symbol: str
    gross_revenue: float
    external_production_cost: float
    corporate_margin: float
    units: float
    perceived_score: float
    perceived_discrepancy: float
    greenhushing_visibility_loss: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConsumerMarketLedger:
    daily_budget: float
    cumulative_exogenous_budget: float = 0.0
    cumulative_gross_revenue: float = 0.0
    cumulative_external_production_cost: float = 0.0
    cumulative_corporate_margin: float = 0.0
    flows: list[ConsumerFirmFlow] = field(default_factory=list)

    def record_day(self, budget: float,
                   flows: Iterable[ConsumerFirmFlow]) -> None:
        day_flows = list(flows)
        gross = sum(flow.gross_revenue for flow in day_flows)
        external_cost = sum(flow.external_production_cost
                            for flow in day_flows)
        margin = sum(flow.corporate_margin for flow in day_flows)
        self.cumulative_exogenous_budget += budget
        self.cumulative_gross_revenue += gross
        self.cumulative_external_production_cost += external_cost
        self.cumulative_corporate_margin += margin
        self.flows.extend(day_flows)

    def validate(self, tolerance: float = 1e-8) -> None:
        assert abs(self.cumulative_exogenous_budget
                   - self.cumulative_gross_revenue) <= tolerance
        assert abs(self.cumulative_gross_revenue
                   - self.cumulative_external_production_cost
                   - self.cumulative_corporate_margin) <= tolerance


class ConsumerMarket:
    def __init__(self, daily_budget: float = 1000.0,
                 segments: Iterable[ConsumerSegment]
                 = DEFAULT_CONSUMER_SEGMENTS,
                 discrepancy_sensitivity: float = 1.0):
        self.daily_budget = max(0.0, float(daily_budget))
        self.segments = tuple(segments)
        # Part J sensitivity lever (STYLIZATION; default 1.0 preserves
        # behaviour): scales the utility penalty consumers attach to a
        # perceived claim/evidence divergence.
        self.discrepancy_sensitivity = max(
            0.0, float(discrepancy_sensitivity))
        total_share = sum(max(0.0, segment.population_share)
                          for segment in self.segments)
        if total_share <= 0.0:
            raise ValueError("consumer segment shares must sum to a positive value")
        self._normalized_shares = {
            segment.name: segment.population_share / total_share
            for segment in self.segments}
        self.beliefs: dict[tuple[str, str], ConsumerBelief] = {}
        self.ledger = ConsumerMarketLedger(self.daily_budget)
        self.last_flows: list[ConsumerFirmFlow] = []

    def step(self, day: int, venues: Iterable[Any], rng: random.Random) \
            -> list[ConsumerFirmFlow]:
        venues = list(venues)
        if not venues or self.daily_budget <= 0.0:
            self.last_flows = []
            self.ledger.record_day(0.0, [])
            return []
        revenue = {venue.symbol: 0.0 for venue in venues}
        perceived_score = {venue.symbol: 0.0 for venue in venues}
        perceived_gap = {venue.symbol: 0.0 for venue in venues}
        visibility_loss = {venue.symbol: 0.0 for venue in venues}

        for segment in self.segments:
            utilities: list[float] = []
            segment_beliefs: list[ConsumerBelief] = []
            for index, venue in enumerate(venues):
                belief = self._update_belief(segment, venue.asset, day, rng)
                segment_beliefs.append(belief)
                product_price = 1.0 + 0.02 * index
                base_quality = 0.25 - 0.01 * index
                green_utility = (segment.environmental_preference
                                 * belief.perceived_score
                                 * belief.visibility)
                discrepancy_penalty = (
                    self.discrepancy_sensitivity
                    * (0.4 + segment.attention + segment.sophistication)
                    * belief.perceived_discrepancy
                    * (1.0 + belief.controversy))
                utility = (base_quality + green_utility
                           - discrepancy_penalty
                           - segment.price_sensitivity * math.log(product_price))
                utilities.append(utility)
            maximum = max(utilities)
            weights = [math.exp(value - maximum) for value in utilities]
            denominator = sum(weights)
            segment_budget = (self.daily_budget
                              * self._normalized_shares[segment.name])
            for venue, weight, belief in zip(venues, weights,
                                             segment_beliefs):
                allocation = segment_budget * weight / denominator
                revenue[venue.symbol] += allocation
                perceived_score[venue.symbol] += (
                    self._normalized_shares[segment.name]
                    * belief.perceived_score)
                perceived_gap[venue.symbol] += (
                    self._normalized_shares[segment.name]
                    * belief.perceived_discrepancy)
                visibility_loss[venue.symbol] += (
                    self._normalized_shares[segment.name]
                    * (1.0 - belief.visibility))

        flows: list[ConsumerFirmFlow] = []
        for index, venue in enumerate(venues):
            asset = venue.asset
            gross = revenue[venue.symbol]
            # Trust-related productivity loss is at most 3% of revenue,
            # because WorkforceState bounds its multiplier to [0.97, 1].
            production_cost_rate = 0.60 + (1.0
                                           - asset.workforce.productivity_multiplier)
            external_cost = gross * production_cost_rate
            margin = gross - external_cost
            product_price = 1.0 + 0.02 * index
            asset.balance += margin
            flows.append(ConsumerFirmFlow(
                day=day,
                firm_symbol=venue.symbol,
                gross_revenue=gross,
                external_production_cost=external_cost,
                corporate_margin=margin,
                units=gross / product_price,
                perceived_score=perceived_score[venue.symbol],
                perceived_discrepancy=perceived_gap[venue.symbol],
                greenhushing_visibility_loss=visibility_loss[venue.symbol],
            ))
        # Force the final gross amount to the exogenous budget at floating
        # precision by assigning any sub-cent residual to the first firm.
        residual = self.daily_budget - sum(flow.gross_revenue for flow in flows)
        if abs(residual) > 1e-12 and flows:
            first = flows[0]
            cost_rate = (first.external_production_cost
                         / first.gross_revenue) if first.gross_revenue else 0.60
            cost_delta = residual * cost_rate
            margin_delta = residual - cost_delta
            flows[0] = ConsumerFirmFlow(
                **{**first.to_dict(),
                   "gross_revenue": first.gross_revenue + residual,
                   "external_production_cost":
                       first.external_production_cost + cost_delta,
                   "corporate_margin": first.corporate_margin + margin_delta,
                   "units": first.units + residual / 1.0})
            venues[0].asset.balance += margin_delta
        self.last_flows = flows
        self.ledger.record_day(self.daily_budget, flows)
        return flows

    def _update_belief(self, segment: ConsumerSegment, asset: Any,
                       day: int, rng: random.Random) -> ConsumerBelief:
        key = (segment.name, asset.symbol)
        belief = self.beliefs.setdefault(key, ConsumerBelief())
        claim = next((item for item in reversed(asset.claim_history)
                      if item.subject == ClaimSubject.GREEN_SCORE
                      and not item.withdrawn), None)
        visible_score = claim.asserted_value if claim is not None else 0.0
        evidence_gap = 0.0
        if claim is not None and segment.sophistication > 0.0:
            records = {record.evidence_id: record
                       for record in asset.evidence_history}
            linked = next((records[eid] for eid in claim.evidence_ids
                           if eid in records
                           and records[eid].accessible_to_consumers), None)
            if linked is not None:
                evidence_gap = max(0.0, claim.asserted_value - linked.estimate)
        public = asset.public_environmental_signals[-1] \
            if asset.public_environmental_signals else None
        controversy = public.controversy_discount if public is not None else 0.0
        if public is not None:
            evidence_gap = max(evidence_gap, public.perceived_discrepancy)
            visible_score = min(visible_score or public.supported_score,
                                public.supported_score)

        # CorporateCommunicationsPolicy is held by the venue, while the
        # chosen public aggregates are mirrored on Asset.
        benchmark = max(0.0, asset.q_truthful_benchmark)
        actual_intensity = max(0.0, benchmark - asset.greenhushing_gap)
        visibility = _clamp(actual_intensity / benchmark) if benchmark > 0 \
            else (1.0 if claim is not None else 0.0)
        noisy_gap = 0.0
        if claim is not None or public is not None:
            noisy_gap = max(0.0, evidence_gap + rng.gauss(
                0.0, 0.08 * (1.0 - segment.sophistication)))
        attention = segment.attention
        learning = _clamp(0.05 + 0.65 * attention * (1.0 - segment.memory))
        belief.perceived_score += learning * (visible_score
                                              - belief.perceived_score)
        belief.perceived_discrepancy += learning * (
            segment.sophistication * noisy_gap - belief.perceived_discrepancy)
        belief.controversy += learning * (controversy - belief.controversy)
        belief.visibility += learning * (visibility - belief.visibility)
        belief.last_updated_day = day
        return belief
