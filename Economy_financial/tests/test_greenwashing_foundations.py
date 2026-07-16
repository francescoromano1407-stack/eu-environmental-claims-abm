"""Foundation tests for the opt-in EU greenwashing supervision layer."""

from datetime import date

from market_sim.environmental_claims import (
    ClaimAudience,
    ClaimChannel,
    ClaimSubject,
    ClaimType,
    EnvironmentalClaim,
    EnvironmentalFactVector,
    FirmProfile,
)
from market_sim.models import Asset
from market_sim.regulation import LegalRegime
from market_sim.simulation import Simulation


def test_legal_calendar_and_strict_csrd_conjunction():
    regime = LegalRegime()
    in_scope = FirmProfile("BIG", 0.5, annual_net_turnover=450_000_001,
                           average_employees=1001)
    at_turnover = FirmProfile("TURN", 0.5, annual_net_turnover=450_000_000,
                              average_employees=2000)
    at_employees = FirmProfile("EMP", 0.5, annual_net_turnover=900_000_000,
                               average_employees=1000)
    assert regime.ucpd_active(date(2026, 1, 1))
    assert not regime.empowering_consumers_active(date(2026, 9, 26))
    assert regime.empowering_consumers_active(date(2026, 9, 27))
    assert not regime.csrd_in_scope(in_scope, date(2027, 3, 18))
    assert regime.csrd_in_scope(in_scope, date(2027, 3, 19))
    assert not regime.csrd_in_scope(at_turnover, date(2027, 3, 19))
    assert not regime.csrd_in_scope(at_employees, date(2027, 3, 19))
    assert not regime.csddd_active(date(2029, 7, 25))
    assert regime.csddd_active(date(2029, 7, 26))


def test_rolling_employee_average_is_used_when_supplied():
    regime = LegalRegime()
    profile = FirmProfile("AVG", 0.5, annual_net_turnover=500_000_000,
                          average_employees=1400)
    on_date = date(2028, 1, 1)
    assert regime.csrd_in_scope(profile, on_date, average_employees=1001)
    assert not regime.csrd_in_scope(profile, on_date, average_employees=999)


def test_individual_and_group_csrd_scope_are_distinct():
    regime = LegalRegime()
    profile = FirmProfile(
        "GROUP", 0.5, annual_net_turnover=200_000_000,
        average_employees=500,
        group_annual_net_turnover=900_000_000,
        group_average_employees=2500)
    on_date = date(2028, 1, 1)
    assert not regime.csrd_in_scope(profile, on_date)
    assert regime.csrd_in_scope(profile, on_date, group_scope=True)


def test_legacy_profile_adapter_and_serialization():
    profile = FirmProfile.from_legacy(("OLD", 0.4, "adaptive", 600_000),
                                      legacy_size_threshold=300_000)
    assert profile.symbol == "OLD"
    assert profile.strategy == "adaptive"
    assert profile.annual_net_turnover == 900_000_000
    assert profile.average_employees == 2000
    assert profile.to_dict()["legacy_firm_size"] == 600_000


def test_fact_and_claim_serialization_keep_period_scope_and_offsets():
    facts = EnvironmentalFactVector.from_green_score(
        0.7, date(2026, 1, 1), date(2026, 12, 31), 500_000_000)
    assert facts.taxonomy_aligned_turnover_share \
        <= facts.taxonomy_eligible_turnover_share
    assert facts.scope_3_emissions > facts.scope_1_emissions
    claim = EnvironmentalClaim(
        claim_id="C-1", firm_symbol="F", day=1,
        communication_date=date(2026, 1, 1),
        channel=ClaimChannel.MARKETING,
        audience=ClaimAudience.CONSUMERS,
        claim_type=ClaimType.OFFSET_BASED,
        subject=ClaimSubject.NET_ZERO,
        asserted_value=0.0, unit="net_emissions_ratio",
        period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
        organizational_boundary="group", operational_boundary="scope_1_2",
        relies_on_offsets=True, offset_disclosed_separately=False,
    )
    payload = claim.to_dict()
    assert payload["channel"] == "marketing"
    assert payload["subject"] == "net_zero"
    assert payload["communication_date"] == "2026-01-01"


def test_asset_exposes_new_fields_without_removing_legacy_proxy():
    asset = Asset("F", green_score=0.6, firm_size=123.0,
                  annual_net_turnover=500_000_000,
                  average_employees=1200)
    assert asset.firm_size == 123.0
    assert asset.annual_net_turnover == 500_000_000
    assert asset.average_employees == 1200
    assert asset.environmental_facts.aggregate_score() >= 0.0
    assert asset.workforce.average_employees_365d == 1200


def test_simulation_accepts_firm_profiles_and_legacy_tuples():
    profiles = [
        FirmProfile("NEW", 0.6, "honest", 700_000_000, 1500),
        ("OLD", 0.2, "adaptive", 600_000),
    ]
    sim = Simulation(num_traders=3, num_manipulators=0, enable_credit=False,
                     asset_profiles=profiles, enable_esg=True, days=1)
    new, old = (venue.asset for venue in sim.venues)
    assert new.annual_net_turnover == 700_000_000
    assert new.average_employees == 1500
    assert old.firm_size == 600_000
    assert old.annual_net_turnover == 900_000_000
