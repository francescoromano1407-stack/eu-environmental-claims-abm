from datetime import date
import random

from market_sim.corporate_communications import CorporateCommunicationsPolicy
from market_sim.environmental_claims import (
    ClaimChannel,
    ClaimSubject,
    ClaimType,
)
from market_sim.models import Asset


def test_honest_mandatory_report_has_multidimensional_supported_claims():
    asset = Asset("HON", green_score=0.75,
                  annual_net_turnover=700_000_000,
                  average_employees=1500)
    policy = CorporateCommunicationsPolicy(asset, "honest")
    decision, claims, evidence = policy.communicate(
        400, date(2027, 4, 5), 0.55, True, random.Random(10))
    subjects = {claim.subject for claim in claims
                if claim.channel == ClaimChannel.SUSTAINABILITY_REPORT}
    assert {ClaimSubject.SCOPE_1_EMISSIONS,
            ClaimSubject.SCOPE_2_EMISSIONS,
            ClaimSubject.SCOPE_3_EMISSIONS,
            ClaimSubject.TAXONOMY_ALIGNMENT,
            ClaimSubject.ENVIRONMENTAL_CAPEX}.issubset(subjects)
    assert len(evidence) == len(claims)
    assert all(claim.evidence_ids for claim in claims)
    assert decision.overstatement == 0.0
    assert decision.claim_preparation_cost > 0.0
    assert decision.evidence_cost > 0.0
    assert asset.communication_preparation_spend \
        == decision.claim_preparation_cost


def test_greenwasher_generates_overstatement_scope_mismatch_offsets_targets():
    asset = Asset("GW", green_score=0.30)
    policy = CorporateCommunicationsPolicy(asset, "greenwasher")
    decision, claims, _ = policy.communicate(
        60, date(2026, 3, 1), 0.20, False, random.Random(5))
    assert decision.overstatement > 0.0
    marketing = [claim for claim in claims
                 if claim.channel in {ClaimChannel.MARKETING,
                                      ClaimChannel.PRODUCT_LABEL}]
    assert marketing
    assert any(claim.operational_boundary == "scope_1_2"
               for claim in marketing)
    offset_claim = next(claim for claim in claims
                        if claim.claim_type == ClaimType.OFFSET_BASED)
    assert offset_claim.relies_on_offsets
    assert not offset_claim.offset_disclosed_separately
    target = next(claim for claim in claims
                  if claim.claim_type == ClaimType.FUTURE_TARGET)
    assert target.target_date is not None
    assert target.baseline_value is not None
    taxonomy = next(claim for claim in claims
                    if claim.subject == ClaimSubject.TAXONOMY_ALIGNMENT)
    assert taxonomy.asserted_value >= 0.0


def test_extreme_burden_can_cause_greenhushing_but_not_an_illegal_claim():
    asset = Asset("QUIET", green_score=0.80)
    policy = CorporateCommunicationsPolicy(asset, "honest")
    decision, claims, evidence = policy.communicate(
        60, date(2026, 3, 1), 1.0, False, random.Random(7))
    assert decision.communication_intensity == 0.0
    assert decision.greenhushing_gap > 0.0
    assert claims == []
    assert evidence == []
    assert asset.assessment_history == []


def test_guidance_can_reduce_greenhushing_without_changing_truth():
    unsupported = CorporateCommunicationsPolicy(
        Asset("NOHELP", green_score=0.80), "honest")
    supported = CorporateCommunicationsPolicy(
        Asset("HELP", green_score=0.80), "honest")
    no_help = unsupported.choose(1.0, False)
    with_help = supported.choose(
        1.0, False, guidance_support=1.0, evidence_support=1.0)
    assert with_help.communication_intensity \
        > no_help.communication_intensity
    assert with_help.greenhushing_gap < no_help.greenhushing_gap
    assert supported.asset.true_green_score \
        == unsupported.asset.true_green_score


def test_public_records_do_not_serialize_latent_truth():
    asset = Asset("SAFE", green_score=0.50)
    policy = CorporateCommunicationsPolicy(asset, "adaptive")
    _, claims, evidence = policy.communicate(
        60, date(2026, 3, 1), 0.55, False, random.Random(8))
    assert claims and evidence
    assert all("true_green_score" not in claim.to_dict()
               and "environmental_facts" not in claim.to_dict()
               for claim in claims)
    assert all("true_green_score" not in record.to_dict()
               for record in evidence)
