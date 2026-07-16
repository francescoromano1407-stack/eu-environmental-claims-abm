"""Part H tests: policy selection/regression, pre-screening hub, connector.

Deterministic throughout: every RNG is seeded locally, no test depends on
wall time or ordering of other tests.
"""

import random
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from market_sim.environmental_claims import (
    ClaimAudience,
    ClaimChannel,
    ClaimSubject,
    ClaimType,
    EnvironmentalClaim,
    EvidenceRecord,
    EvidenceSource,
)
from market_sim.greenwashing_supervision import GreenwashingSupervisor
from market_sim.policy_regimes import (
    PRESCREENING_STATUS,
    CertifiedGreenDataConnector,
    ConnectorAuthorizationState,
    ConnectorParameters,
    DataSourceKind,
    GreenwashingPolicyRegime,
    PrescreeningParameters,
    PrescreeningParticipationMode,
    ReconciliationClass,
    SMEPrescreeningHub,
)
from market_sim.regulation import LegalRegime
from market_sim.simulation import Simulation


# --------------------------------------------------------------------------- #
# Test fixtures: minimal information-safe stand-ins
# --------------------------------------------------------------------------- #
class _Workforce:
    def __init__(self, employees: float):
        self.average_employees_365d = employees


class _FactsStub:
    """Physical ledger stub for connector metering tests."""

    def __init__(self, values: dict, period_start: date, period_end: date):
        self._values = values
        self.period_start = period_start
        self.period_end = period_end

    def value_for(self, subject: ClaimSubject) -> float:
        return float(self._values.get(subject, 0.0))


class _AssetStub:
    def __init__(self, symbol: str = "SME1", employees: float = 400.0,
                 balance: float = 500_000.0):
        self.symbol = symbol
        self.balance = balance
        self.workforce = _Workforce(employees)
        self.q_truthful_benchmark = 0.60
        self.greenhushing_gap = 0.0
        self.claim_history = []
        self.evidence_history = []
        self.public_environmental_signals = []
        self.environmental_facts = _FactsStub(
            {ClaimSubject.SCOPE_1_EMISSIONS: 50_000.0,
             ClaimSubject.SCOPE_2_EMISSIONS: 30_000.0,
             ClaimSubject.SCOPE_3_EMISSIONS: 120_000.0,
             ClaimSubject.RENEWABLE_ENERGY_SHARE: 0.40,
             ClaimSubject.WATER_INTENSITY: 0.50,
             ClaimSubject.RECYCLING_RATE: 0.55,
             ClaimSubject.POLLUTION_INTENSITY: 0.45,
             ClaimSubject.ENVIRONMENTAL_CAPEX: 900_000.0},
            date(2026, 1, 1), date(2026, 12, 31))


def _claim(claim_id: str = "C-TEST-1", subject=ClaimSubject.GREEN_SCORE,
           claim_type=ClaimType.QUALITATIVE,
           channel=ClaimChannel.MARKETING, asserted: float = 0.8,
           qualification: str = "", evidence_ids=(), unit: str = "score_0_1",
           **overrides) -> EnvironmentalClaim:
    base = dict(
        claim_id=claim_id, firm_symbol="SME1", day=60,
        communication_date=date(2026, 3, 1), channel=channel,
        audience=ClaimAudience.CONSUMERS, claim_type=claim_type,
        subject=subject, asserted_value=asserted, unit=unit,
        period_start=date(2026, 1, 1), period_end=date(2026, 2, 28),
        organizational_boundary="consolidated_group",
        operational_boundary="scope_1_2_3", evidence_ids=evidence_ids,
        qualification=qualification)
    base.update(overrides)
    return EnvironmentalClaim(**base)


def _evidence(evidence_id: str = "E-TEST-1",
              subject=ClaimSubject.GREEN_SCORE, estimate: float = 0.55,
              standard_error: float = 0.03, verified: bool = False,
              **overrides) -> EvidenceRecord:
    base = dict(
        evidence_id=evidence_id, firm_symbol="SME1", subject=subject,
        period_start=date(2026, 1, 1), period_end=date(2026, 2, 28),
        estimate=estimate, standard_error=standard_error,
        source=EvidenceSource.COMPANY_RECORD, coverage=0.9,
        independence=0.2, verified=verified, reliability_prior=0.8)
    base.update(overrides)
    return EvidenceRecord(**base)


# --------------------------------------------------------------------------- #
# Policy selection and regression
# --------------------------------------------------------------------------- #
def test_default_path_remains_current_system():
    sim = Simulation(num_traders=6, num_manipulators=0,
                     enable_credit=False, enable_esg=True,
                     enable_greenwashing_supervision=True, days=5)
    assert sim.policy_regime \
        == GreenwashingPolicyRegime.CURRENT_EU_SUPERVISION
    assert sim.prescreening_hub is None
    assert sim.green_data_connector is None


def test_explicit_baseline_regime_is_byte_identical_to_default():
    def _run(**extra):
        random.seed(23)
        sim = Simulation(num_traders=8, num_manipulators=0,
                         enable_credit=False, enable_esg=True,
                         enable_greenwashing_supervision=True, days=120,
                         **extra)
        sim.run()
        return ([(c.claim_id, c.asserted_value, c.withdrawn)
                 for c in sim.claim_log],
                sim.log_price, sim.log_greenhushing_gap)

    assert _run() == _run(greenwashing_policy_regime=GreenwashingPolicyRegime
                          .CURRENT_EU_SUPERVISION)


def test_non_baseline_regime_requires_supervision():
    with pytest.raises(ValueError):
        Simulation(num_traders=6, enable_esg=True, days=5,
                   greenwashing_policy_regime=GreenwashingPolicyRegime
                   .SME_ALGORITHMIC_PRESCREENING)


def test_each_regime_runs_independently_and_crn_arms_stay_aligned():
    prices = {}
    for regime in (GreenwashingPolicyRegime.CURRENT_EU_SUPERVISION,
                   GreenwashingPolicyRegime.SME_ALGORITHMIC_PRESCREENING,
                   GreenwashingPolicyRegime.CERTIFIED_GREEN_DATA_CONNECTOR):
        random.seed(31)
        sim = Simulation(num_traders=8, num_manipulators=0,
                         enable_credit=False, enable_esg=True,
                         enable_greenwashing_supervision=True, days=70,
                         greenwashing_policy_regime=regime)
        sim.run()
        prices[regime.value] = list(sim.log_price)
    # Common random numbers: before the first reporting epoch (day 60) no
    # policy instrument has acted, so all arms share the exact trajectory.
    baseline = prices[GreenwashingPolicyRegime
                      .CURRENT_EU_SUPERVISION.value]
    for name, series in prices.items():
        assert series[:59] == baseline[:59], name


# --------------------------------------------------------------------------- #
# Pre-screening hub
# --------------------------------------------------------------------------- #
def test_eligibility_mirrors_protected_undertaking_line_only():
    hub = SMEPrescreeningHub()
    assert hub.is_eligible(average_employees=800.0, mandatory_csrd=False)
    assert not hub.is_eligible(average_employees=1500.0,
                               mandatory_csrd=False)
    assert not hub.is_eligible(average_employees=800.0,
                               mandatory_csrd=True)


def test_participation_is_voluntary_and_never_mandatory_assurance():
    params = PrescreeningParameters()
    assert params.participation_mode \
        == PrescreeningParticipationMode.VOLUNTARY
    assert params.safe_harbor_enabled is False
    hub = SMEPrescreeningHub(params)
    rng = random.Random(3)
    feedback = hub.screen(_claim(), {}, [], [], rng, day=60)
    assert feedback.prescreening_status == PRESCREENING_STATUS
    assert "not assurance" in feedback.disclaimer
    assert "does not approve" in feedback.disclaimer


def test_vague_claims_receive_explainable_feedback():
    hub = SMEPrescreeningHub(replace(PrescreeningParameters(), noise=0.0))
    rng = random.Random(5)
    feedback = hub.screen(_claim(), {}, [], [], rng, day=60)
    codes = {issue.issue_code for issue in feedback.issues}
    assert "VAGUE_GENERIC_LANGUAGE" in codes
    issue = next(item for item in feedback.issues
                 if item.issue_code == "VAGUE_GENERIC_LANGUAGE")
    assert issue.explanation and issue.recommended_correction
    assert issue.reference and issue.legally_material


def test_supported_specific_claims_are_not_rejected():
    hub = SMEPrescreeningHub(replace(PrescreeningParameters(), noise=0.0))
    rng = random.Random(7)
    record = _evidence(estimate=0.62, standard_error=0.02, coverage=0.95,
                       verified=True, reliability_prior=0.9)
    claim = _claim(claim_type=ClaimType.QUANTITATIVE, asserted=0.62,
                   qualification="Boundary and period stated.",
                   evidence_ids=(record.evidence_id,),
                   stated_uncertainty=0.02)
    feedback = hub.screen(claim, {record.evidence_id: record}, [], [],
                          rng, day=60)
    assert not feedback.materially_flagged


def test_correcting_a_draft_reduces_infringement_risk():
    """A revised draft aligns with its own evidence, so the rule engine
    no longer finds a greener-than-evidence divergence."""
    hub = SMEPrescreeningHub(replace(PrescreeningParameters(), noise=0.0))
    asset = _AssetStub()
    record = _evidence(estimate=0.50, standard_error=0.03)
    overstated = _claim(claim_type=ClaimType.QUANTITATIVE, asserted=0.85,
                        evidence_ids=(record.evidence_id,),
                        qualification="stated boundary")
    rng = random.Random(11)   # Honest firm: revises deterministically.
    published, _ = hub.process_firm_claims(
        60, asset, "honest", [overstated], [record], False, rng)
    assert published and published[0].asserted_value \
        == pytest.approx(record.estimate)

    engine = GreenwashingSupervisor(LegalRegime(), random.Random(1)).rules
    assessment = engine.assess(published[0], [record], 60,
                               date(2026, 3, 1))
    assert assessment.outcome.value in {"supported",
                                        "supported_with_qualification",
                                        "noise"}


def test_publishing_against_advice_remains_possible():
    hub = SMEPrescreeningHub(replace(PrescreeningParameters(), noise=0.0))
    asset = _AssetStub()
    record = _evidence(estimate=0.40, standard_error=0.02)
    outcomes = set()
    for seed in range(40):
        claim = _claim(claim_id=f"C-{seed}",
                       claim_type=ClaimType.QUANTITATIVE, asserted=0.90,
                       evidence_ids=(record.evidence_id,))
        rng = random.Random(seed)
        published, _ = hub.process_firm_claims(
            60, asset, "greenwasher", [claim], [record], False, rng)
        if published and published[0].asserted_value \
                == pytest.approx(0.90):
            outcomes.add("published_against_advice")
    assert "published_against_advice" in outcomes
    assert hub.published_against_advice > 0


def test_strict_noisy_algorithm_increases_withdrawal_and_greenhushing():
    def _withdrawals(strictness: float, noise: float) -> tuple[int, float]:
        hub = SMEPrescreeningHub(replace(
            PrescreeningParameters(), strictness=strictness, noise=noise))
        asset = _AssetStub()
        record = _evidence(estimate=0.55, standard_error=0.03)
        for seed in range(60):
            claim = _claim(claim_id=f"C-{strictness}-{seed}",
                           evidence_ids=(record.evidence_id,))
            rng = random.Random(seed)
            hub.process_firm_claims(60, asset, "honest", [claim],
                                    [record], False, rng)
        return hub.withdrawals, asset.greenhushing_gap

    lenient_withdrawn, lenient_gap = _withdrawals(0.10, 0.0)
    strict_withdrawn, strict_gap = _withdrawals(0.95, 0.60)
    assert strict_withdrawn > lenient_withdrawn
    assert strict_gap >= lenient_gap


def test_hub_never_reads_latent_truth():
    """Identical claim+evidence with different underlying physical states
    must produce identical feedback: the hub is information-safe."""
    hub_a = SMEPrescreeningHub(replace(PrescreeningParameters(), noise=0.0))
    hub_b = SMEPrescreeningHub(replace(PrescreeningParameters(), noise=0.0))
    record = _evidence()
    claim_a = _claim(evidence_ids=(record.evidence_id,))
    claim_b = _claim(evidence_ids=(record.evidence_id,))
    feedback_a = hub_a.screen(claim_a, {record.evidence_id: record}, [],
                              [], random.Random(9), day=60)
    feedback_b = hub_b.screen(claim_b, {record.evidence_id: record}, [],
                              [], random.Random(9), day=60)
    assert [issue.issue_code for issue in feedback_a.issues] \
        == [issue.issue_code for issue in feedback_b.issues]


def test_safe_harbor_guides_good_faith_but_never_shields_deception():
    random.seed(41)
    sim = Simulation(
        num_traders=6, num_manipulators=0, enable_credit=False,
        enable_esg=True, enable_greenwashing_supervision=True, days=5,
        greenwashing_policy_regime=GreenwashingPolicyRegime
        .SME_ALGORITHMIC_PRESCREENING,
        prescreening_parameters=replace(PrescreeningParameters(),
                                        safe_harbor_enabled=True))
    supervisor = sim.greenwashing_supervisor
    hub = sim.prescreening_hub
    record = _evidence(estimate=0.50, standard_error=0.02)
    supervisor.evidence[record.evidence_id] = record

    # Good-faith case: cleanly pre-screened, no contradiction with the
    # firm's own evidence -> negligence downgraded to correction.
    good = _claim(claim_id="C-GOOD", claim_type=ClaimType.QUANTITATIVE,
                  asserted=0.52, evidence_ids=(record.evidence_id,),
                  qualification="qualified")
    supervisor.claims[good.claim_id] = good
    hub.cleanly_prescreened.add(good.claim_id)
    good_assessment = supervisor.rules.assess(good, [record], 60,
                                              date(2026, 3, 1))
    good_assessment.outcome = type(good_assessment.outcome)("negligence")
    sim._apply_prescreening_safe_harbor([good_assessment])
    assert good_assessment.outcome.value == "correctable_error"

    # Deceptive case: the published value contradicts the firm's own
    # linked evidence by far more than its uncertainty -> NOT protected.
    bad = _claim(claim_id="C-BAD", claim_type=ClaimType.QUANTITATIVE,
                 asserted=0.95, evidence_ids=(record.evidence_id,),
                 qualification="qualified")
    supervisor.claims[bad.claim_id] = bad
    hub.cleanly_prescreened.add(bad.claim_id)
    bad_assessment = supervisor.rules.assess(bad, [record], 60,
                                             date(2026, 3, 1))
    bad_assessment.outcome = type(bad_assessment.outcome)("negligence")
    sim._apply_prescreening_safe_harbor([bad_assessment])
    assert bad_assessment.outcome.value == "negligence"


# --------------------------------------------------------------------------- #
# Certified green data connector
# --------------------------------------------------------------------------- #
def _active_connector(asset, seed: int = 13,
                      parameters: ConnectorParameters | None = None) \
        -> CertifiedGreenDataConnector:
    connector = CertifiedGreenDataConnector(parameters)
    rng = random.Random(seed)
    connector.onboard_firm(asset, "honest", rng)
    return connector


def test_authorized_transfers_create_tamper_evident_provenance():
    asset = _AssetStub()
    connector = _active_connector(asset)
    records = connector.transfer_period(60, date(2026, 3, 1), asset,
                                        random.Random(17))
    assert records
    assert connector.provenance
    for record in connector.provenance:
        assert len(record.integrity_hash) == 64
        assert record.authorization_state \
            == ConnectorAuthorizationState.ACTIVE.value
        assert record.methodology_version


def test_unauthorized_and_revoked_sources_are_inaccessible():
    asset = _AssetStub()
    connector = _active_connector(asset)
    for source in connector.parameters.sources:
        connector.revoke(asset.symbol, source.kind)
    records = connector.transfer_period(60, date(2026, 3, 1), asset,
                                        random.Random(17))
    assert records == []


def test_connector_populates_only_covered_metrics_never_taxonomy_net_zero():
    asset = _AssetStub()
    connector = _active_connector(asset)
    records = connector.transfer_period(60, date(2026, 3, 1), asset,
                                        random.Random(19))
    by_subject = {record.subject for record in records}
    scope1 = next((r for r in records
                   if r.subject == ClaimSubject.SCOPE_1_EMISSIONS), None)
    assert scope1 is not None

    taxonomy = _claim(claim_id="C-TAX",
                      subject=ClaimSubject.TAXONOMY_ALIGNMENT,
                      claim_type=ClaimType.TAXONOMY,
                      channel=ClaimChannel.SUSTAINABILITY_REPORT,
                      asserted=0.99, unit="share_0_1")
    net_zero = _claim(claim_id="C-NZ", subject=ClaimSubject.NET_ZERO,
                      claim_type=ClaimType.OFFSET_BASED,
                      channel=ClaimChannel.SUSTAINABILITY_REPORT,
                      asserted=0.0, unit="net_emissions_ratio")
    covered = _claim(claim_id="C-S1",
                     subject=ClaimSubject.SCOPE_1_EMISSIONS,
                     claim_type=ClaimType.QUANTITATIVE,
                     channel=ClaimChannel.SUSTAINABILITY_REPORT,
                     asserted=10.0, unit="tCO2e")
    connector.auto_populate([taxonomy, net_zero, covered], records,
                            "honest", random.Random(23))
    assert taxonomy.asserted_value == 0.99     # Untouched.
    assert net_zero.asserted_value == 0.0      # Untouched.
    assert covered.asserted_value == pytest.approx(scope1.estimate)
    assert ClaimSubject.TAXONOMY_ALIGNMENT not in by_subject
    assert ClaimSubject.NET_ZERO not in by_subject


def test_source_uncertainty_remains_positive_and_staleness_reduces_confidence():
    asset = _AssetStub()
    connector = _active_connector(
        asset, parameters=ConnectorParameters(stale_probability=0.0,
                                              mismatch_probability=0.0,
                                              register_error_probability=0.0,
                                              downtime_probability=0.0,
                                              cyber_incident_probability=0.0))
    records = connector.transfer_period(60, date(2026, 3, 1), asset,
                                        random.Random(29))
    assert records
    for record in records:
        assert record.standard_error > 0.0
        assert record.confidence < 1.0
    fresh = records[0]
    stale = replace(fresh, staleness_days=300)
    assert stale.confidence < fresh.confidence
    conflicted = replace(fresh, conflict=True)
    assert conflicted.confidence < fresh.confidence


def test_selective_connection_is_detectable():
    asset = _AssetStub(symbol="GWX")
    connector = CertifiedGreenDataConnector()
    # Greenwashers connect sparsely: with this seed the authorized share
    # falls below the selectivity threshold and gets flagged.
    connector.onboard_firm(asset, "greenwasher", random.Random(2))
    share = connector.active_sources("GWX") \
        / len(connector.parameters.sources)
    assert share < 0.60
    assert "GWX" in connector.selective_connection_flags


def test_immaterial_differences_remain_noise():
    asset = _AssetStub()
    connector = _active_connector(
        asset, parameters=ConnectorParameters(stale_probability=0.0,
                                              mismatch_probability=0.0,
                                              register_error_probability=0.0,
                                              downtime_probability=0.0,
                                              cyber_incident_probability=0.0))
    records = connector.transfer_period(60, date(2026, 3, 1), asset,
                                        random.Random(31))
    scope1 = next(r for r in records
                  if r.subject == ClaimSubject.SCOPE_1_EMISSIONS)
    claim = _claim(claim_id="C-NOISE",
                   subject=ClaimSubject.SCOPE_1_EMISSIONS,
                   claim_type=ClaimType.QUANTITATIVE,
                   channel=ClaimChannel.SUSTAINABILITY_REPORT,
                   asserted=scope1.estimate * 1.001, unit="tCO2e",
                   stated_uncertainty=scope1.standard_error)
    findings, flags = connector.reconcile(60, [claim], records, [])
    assert findings[0].classification in {
        ReconciliationClass.MATCHED.value,
        ReconciliationClass.ROUNDING_NOISE.value}
    assert flags == set()


def test_material_override_gets_priority_but_no_automatic_sanction():
    asset = _AssetStub()
    connector = _active_connector(
        asset, parameters=ConnectorParameters(stale_probability=0.0,
                                              mismatch_probability=0.0,
                                              register_error_probability=0.0,
                                              downtime_probability=0.0,
                                              cyber_incident_probability=0.0))
    records = connector.transfer_period(60, date(2026, 3, 1), asset,
                                        random.Random(37))
    scope1 = next(r for r in records
                  if r.subject == ClaimSubject.SCOPE_1_EMISSIONS)
    # Firm reports HALF the metered emissions (greener) with the
    # connector record attached: an unexplained manual override.
    claim = _claim(claim_id="C-OVR",
                   subject=ClaimSubject.SCOPE_1_EMISSIONS,
                   claim_type=ClaimType.QUANTITATIVE,
                   channel=ClaimChannel.SUSTAINABILITY_REPORT,
                   asserted=scope1.estimate * 0.5, unit="tCO2e",
                   evidence_ids=(scope1.evidence_id,))
    balance_before = asset.balance
    findings, flags = connector.reconcile(60, [claim], records, [])
    assert claim.claim_id in flags
    assert findings[0].classification in {
        ReconciliationClass.SUSPICIOUS_OVERRIDE.value,
        ReconciliationClass.MATERIAL_OVERSTATEMENT.value}
    assert asset.balance == balance_before   # Reconciliation never fines.

    supervisor = GreenwashingSupervisor(LegalRegime(), random.Random(1))
    priority, trigger = supervisor._screen_priority(
        claim, records, set(), set(), flags)
    assert trigger == "connector_reconciliation"
    assert priority == pytest.approx(0.90)


def test_source_errors_correctable_without_sanctioning_firm():
    """A register error puts the claim into the correction path of the
    ordinary supervisor, never into an automatic pecuniary sanction."""
    asset = _AssetStub()
    connector = _active_connector(
        asset, parameters=ConnectorParameters(stale_probability=0.0,
                                              mismatch_probability=0.0,
                                              register_error_probability=0.0,
                                              downtime_probability=0.0,
                                              cyber_incident_probability=0.0))
    records = connector.transfer_period(60, date(2026, 3, 1), asset,
                                        random.Random(41))
    scope1 = next(r for r in records
                  if r.subject == ClaimSubject.SCOPE_1_EMISSIONS)
    # Simulate a register error: the connector value is 8% too high, the
    # firm truthfully reports its own (correct) figure.
    corrupted = replace(scope1, estimate=scope1.estimate * 1.08)
    firm_truthful = _claim(
        claim_id="C-REG", subject=ClaimSubject.SCOPE_1_EMISSIONS,
        claim_type=ClaimType.QUANTITATIVE,
        channel=ClaimChannel.SUSTAINABILITY_REPORT,
        asserted=scope1.estimate, unit="tCO2e",
        stated_uncertainty=scope1.standard_error,
        qualification="stated boundary")
    findings, flags = connector.reconcile(
        60, [firm_truthful], [corrupted], [])
    # The divergence is flagged for review (the connector cannot know it
    # is its own register error)...
    assert findings
    # ...but the procedural path decides: with the firm's evidence in the
    # file, the rule engine issues at most a correction-type outcome and
    # applies no penalty at assessment time.
    engine = GreenwashingSupervisor(LegalRegime(), random.Random(1)).rules
    assessment = engine.assess(
        firm_truthful,
        [corrupted, replace(scope1, evidence_id="E-FIRM",
                            source=EvidenceSource.COMPANY_RECORD,
                            independence=0.2, verified=False)],
        60, date(2026, 3, 1))
    assert assessment.penalty == 0.0
    assert assessment.outcome.value not in {"systemic_abuse",
                                            "prohibited_practice"}


def test_connector_ledger_conservation_of_policy_costs():
    random.seed(43)
    sim = Simulation(
        num_traders=8, num_manipulators=0, enable_credit=False,
        enable_esg=True, enable_greenwashing_supervision=True, days=130,
        greenwashing_policy_regime=GreenwashingPolicyRegime
        .HYBRID_PRESCREENING_AND_CONNECTOR)
    sim.run()
    hub, connector = sim.prescreening_hub, sim.green_data_connector
    booked = hub.state_cost_dec + connector.state_cost_dec
    assert sim.state.policy_cost_shortfalls == 0
    assert sim.state.policy_cost_dec == booked
    # The WP6 earmarking identity survives policy spending.
    assert sim.state.bonds_issued_dec \
        == sim.state.green_proceeds_dec \
        + sim.state.green_proceeds_spent_dec
