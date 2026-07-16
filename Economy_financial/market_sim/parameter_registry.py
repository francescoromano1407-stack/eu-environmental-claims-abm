"""Part J (Workstream B): structured parameter registry.

Single machine-readable source of truth for every major behavioural, cost
and institutional parameter of the greenwashing policy experiment. Each
entry states:

* a unique identifier and the exact code location;
* unit, default, and the lower/upper bound used by the global
  sensitivity campaign (`sensitivity_campaign.py`);
* the CLASSIFICATION (LEGAL / LEGAL-ANCHOR / STYLIZATION / EXPERIMENT);
* the EVIDENCE CLASS, kept strictly separate from the classification:
    - ``legally_mandated``       value fixed by a legal instrument in the
                                  model's legal scenario;
    - ``empirically_estimated``  value estimated from data (none of the
                                  behavioural parameters currently is);
    - ``reference_class``        order of magnitude justified by a public
                                  reference class, not directly estimated;
    - ``illustrative_scenario``  a pure modeling choice explored through
                                  sensitivity analysis;
* the source (a primary legal reference where one exists) or the explicit
  statement ``NO_CALIBRATION`` below;
* the expected directional effect (a stated hypothesis, not a result);
* whether the parameter enters the global sensitivity campaign.

Exports: ``export_csv`` and ``export_markdown`` produce the
appendix-ready parameter table; ``gsa_space`` yields the sampling space;
``build_simulation_kwargs`` translates one sampled point into Simulation
constructor arguments.

Honesty note: no behavioural parameter of this model is empirically
calibrated. Classifying a value as ``reference_class`` claims only that
its ORDER OF MAGNITUDE is anchored to a named public reference; results
must be read as policy-experiment orderings under stylized parameters.
"""

from __future__ import annotations

import csv as _csv
from dataclasses import asdict, dataclass, fields
from typing import Any, Mapping, Optional

from market_sim import constants as C

NO_CALIBRATION = ("No direct empirical calibration; scenario range used "
                  "for sensitivity analysis.")

# Real primary legal sources already used by the model documentation.
_SRC_UCPD = "Directive 2005/29/EC (UCPD), ELI: dir/2005/29/oj"
_SRC_2024_825 = ("Directive (EU) 2024/825 (Empowering Consumers), "
                 "ELI: dir/2024/825/oj")
_SRC_2019_2161 = ("Directive (EU) 2019/2161, Art. 3(6) amending UCPD "
                  "Art. 13 (4% turnover fine availability for widespread "
                  "infringements), ELI: dir/2019/2161/oj")
_SRC_2026_470 = ("Directive (EU) 2026/470 as documented in "
                 "docs/EU_GREENWASHING_MODEL.md (stylized in-model legal "
                 "scenario; treat all derived values as scenario law)")
_SRC_BETTER_REG = ("European Commission Better Regulation Toolbox "
                   "(Tool #61 discounting guidance, ~3%/yr social "
                   "discount rate) -- reference class, not an estimate "
                   "for this model")


@dataclass(frozen=True)
class ParameterSpec:
    parameter_id: str
    name: str                 # Campaign/design column name (unique).
    location: str             # Module / class attribute in the code.
    unit: str
    default: Any
    low: Optional[float]
    high: Optional[float]
    classification: str       # LEGAL | LEGAL-ANCHOR | STYLIZATION | EXPERIMENT
    evidence_class: str       # legally_mandated | empirically_estimated |
    #                           reference_class | illustrative_scenario
    source: str
    justification: str
    expected_direction: str
    gsa_eligible: bool
    integer: bool = False     # Round the sampled value to an int.

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _spec(pid, name, location, unit, default, low, high, classification,
          evidence_class, source, justification, direction, gsa,
          integer=False) -> ParameterSpec:
    return ParameterSpec(pid, name, location, unit, default, low, high,
                         classification, evidence_class, source,
                         justification, direction, gsa, integer)


REGISTRY: tuple[ParameterSpec, ...] = (
    # ---------------- sanction scale and proportionality ---------------- #
    _spec("SAN-01", "sim_turnover_balance_multiple",
          "SupervisionParameters.sim_turnover_balance_multiple",
          "x corporate balance", C.SIM_TURNOVER_BALANCE_MULTIPLE, 0.5, 3.0,
          "STYLIZATION", "reference_class",
          "Asset-turnover ratios of listed EU non-financials cluster "
          "roughly between 0.5 and 2 (order-of-magnitude reference class "
          "from standard financial-statement analysis); "
          + NO_CALIBRATION,
          "Bridge between simulation-scale balances and the statutory "
          "turnover-based ceiling rates (Part I.1).",
          "Higher -> larger sanction bases -> more deterrence, possibly "
          "more greenhushing.", True),
    _spec("SAN-02", "benefit_multiplier",
          "SupervisionParameters.benefit_multiplier", "x benefit",
          1.5, 0.5, 3.0, "EXPERIMENT", "illustrative_scenario",
          NO_CALIBRATION,
          "Disgorgement-plus factor on the estimated benefit of the "
          "misleading claim.",
          "Higher -> stronger deterrence of profitable overstatement.",
          True),
    _spec("SAN-03", "affected_revenue_rate",
          "SupervisionParameters.affected_revenue_rate", "share/severity",
          0.02, 0.005, 0.06, "EXPERIMENT", "illustrative_scenario",
          NO_CALIBRATION,
          "Revenue-linked component of the experimental sanction formula.",
          "Higher -> larger penalties for high-exposure channels.", True),
    _spec("SAN-04", "ordinary_penalty_cap_rate",
          "SupervisionParameters.ordinary_penalty_cap_rate",
          "share of sim turnover", 0.01, None, None, "EXPERIMENT",
          "illustrative_scenario", NO_CALIBRATION,
          "Ordinary simulated ceiling; the legal 4%/3% ceilings are "
          "track-gated separately. Held fixed in the campaign to keep "
          "the track-gating interpretable.",
          "Higher -> binding less often.", False),
    _spec("SAN-05", "consumer_cross_border_cap_rate",
          "SupervisionParameters.consumer_cross_border_cap_rate",
          "share of turnover", 0.04, None, None, "LEGAL",
          "legally_mandated", _SRC_2019_2161,
          "Ceiling available only for coordinated widespread cross-border "
          "consumer infringements.", "n/a (legal ceiling).", False),
    _spec("SAN-06", "csddd_cap_rate",
          "SupervisionParameters.csddd_cap_rate", "share of turnover",
          0.03, None, None, "LEGAL", "legally_mandated",
          _SRC_2026_470 + "; Art. 4(19) amending CSDDD Art. 27(4)",
          "Callable only for due-diligence cases.",
          "n/a (legal ceiling).", False),
    _spec("SAN-07", "penalty_repeat_escalation_rate",
          "constants.PENALTY_REPEAT_ESCALATION_RATE", "x per repeat",
          C.PENALTY_REPEAT_ESCALATION_RATE, None, None, "EXPERIMENT",
          "illustrative_scenario", NO_CALIBRATION,
          "Repeat-offender escalation below the legal ceiling.",
          "Higher -> harsher recidivism response.", False),
    # ---------------- regulator capacity and procedure ------------------ #
    _spec("CAP-01", "evidence_request_capacity",
          "SupervisionParameters.evidence_request_capacity",
          "cases/period", 20, 5, 40, "EXPERIMENT", "reference_class",
          "EU consumer-protection authorities decide tens to a few "
          "hundred misleading-advertising cases per year against far "
          "larger claim volumes (order of magnitude from published CPC "
          "network sweeps); " + NO_CALIBRATION,
          "Screening capacity per reporting period.",
          "Higher -> more coverage, more false positives possible.",
          True, integer=True),
    _spec("CAP-02", "investigation_capacity",
          "SupervisionParameters.investigation_capacity",
          "investigations/period", 5, 1, 12, "EXPERIMENT",
          "reference_class",
          "Formal proceedings are an order of magnitude rarer than "
          "screenings (same reference class as CAP-01); "
          + NO_CALIBRATION,
          "Formal-investigation capacity per period, shared with "
          "conflict investigations (Part J).",
          "Higher -> shorter queues, faster decisions.", True,
          integer=True),
    _spec("CAP-03", "random_surveillance_share",
          "SupervisionParameters.random_surveillance_share", "probability",
          0.10, 0.0, 0.30, "EXPERIMENT", "illustrative_scenario",
          NO_CALIBRATION,
          "Random-surveillance draw deterring pure risk-score gaming.",
          "Higher -> better coverage of low-risk-score abuse, more "
          "capacity spent on clean claims.", True),
    _spec("CAP-04", "correction_window_days",
          "SupervisionParameters.correction_window_days", "days",
          30, 10, 90, "EXPERIMENT", "illustrative_scenario",
          NO_CALIBRATION,
          "First-time correctable errors receive this compliance window.",
          "Longer -> slower correction, more exposure days.", True,
          integer=True),
    _spec("CAP-05", "regulatory_strictness",
          "Simulation(regulatory_strictness=...)", "index 0-1",
          0.55, 0.0, 1.0, "EXPERIMENT", "illustrative_scenario",
          NO_CALIBRATION,
          "Perceived enforcement strictness entering the corporate "
          "communication optimizer.",
          "Higher -> less overstatement AND more greenhushing "
          "(chilling).", True),
    # ---------------- conflict resolution (Part J / Workstream C) ------- #
    _spec("CNF-01", "conflict_capacity_share",
          "SupervisionParameters.conflict_capacity_share", "share",
          C.CONFLICT_CAPACITY_SHARE, 0.0, 0.6, "EXPERIMENT",
          "illustrative_scenario", NO_CALIBRATION,
          "Investigation-capacity share reserved for evidence-conflict "
          "disputes (dedicated data-dispute desk).",
          "Higher -> faster dispute resolution, fewer enforcement "
          "slots.", True),
    _spec("CNF-02", "conflict_resolution_days",
          "SupervisionParameters.conflict_resolution_days", "days",
          C.CONFLICT_RESOLUTION_DAYS, 5, 60, "EXPERIMENT",
          "illustrative_scenario", NO_CALIBRATION,
          "Procedural duration of one conflict investigation.",
          "Longer -> longer exposure of disputed records.", True,
          integer=True),
    _spec("CNF-03", "conflict_priority",
          "SupervisionParameters.conflict_priority", "priority 0-1",
          C.CONFLICT_PRIORITY, None, None, "EXPERIMENT",
          "illustrative_scenario", NO_CALIBRATION,
          "Transparent queue priority of conflict cases (below "
          "whistleblower/complaint/connector triggers).",
          "Higher -> disputes open sooner.", False),
    _spec("CNF-04", "conflict_reverification_timeout_days",
          "SupervisionParameters.conflict_reverification_timeout_days",
          "days", C.CONFLICT_REVERIFICATION_TIMEOUT_DAYS, None, None,
          "EXPERIMENT", "illustrative_scenario", NO_CALIBRATION,
          "Fallback deadline for the credibility-based resolution.",
          "Longer -> more conflicts resolved on real re-measurements.",
          False),
    _spec("CNF-05", "conflict_credibility_margin",
          "SupervisionParameters.conflict_credibility_margin",
          "confidence points", C.CONFLICT_CREDIBILITY_MARGIN, None, None,
          "EXPERIMENT", "illustrative_scenario", NO_CALIBRATION,
          "Decisive margin of the credibility fallback.",
          "Higher -> more dismissals, fewer wrong resolutions.", False),
    _spec("CNF-06", "source_reverification_delay_days",
          "constants.SOURCE_REVERIFICATION_DELAY_DAYS", "days",
          C.SOURCE_REVERIFICATION_DELAY_DAYS, None, None, "EXPERIMENT",
          "illustrative_scenario", NO_CALIBRATION,
          "Third-party re-measurement turnaround.",
          "Longer -> slower dispute resolution.", False),
    # ---------------- hub (Regime B) ------------------------------------ #
    _spec("HUB-01", "hub_participation_scale",
          "PrescreeningParameters.participation_scale", "x propensity",
          1.0, 0.2, 1.5, "EXPERIMENT", "illustrative_scenario",
          "Baseline uptakes (0.90/0.60/0.35 by strategy) have no "
          "empirical source; " + NO_CALIBRATION,
          "Scales every strategy's voluntary participation propensity.",
          "Higher -> more drafts screened (ITT effect grows).", True),
    _spec("HUB-02", "hub_strictness",
          "PrescreeningParameters.strictness", "index 0-1",
          C.PRESCREEN_STRICTNESS_DEFAULT, 0.10, 0.95, "EXPERIMENT",
          "illustrative_scenario", NO_CALIBRATION,
          "Issue-severity threshold scaling of the screening algorithm.",
          "Higher -> more flags, more revisions AND more withdrawals "
          "(greenhushing).", True),
    _spec("HUB-03", "hub_noise", "PrescreeningParameters.noise",
          "probability", C.PRESCREEN_NOISE_DEFAULT, 0.0, 0.50,
          "EXPERIMENT", "illustrative_scenario", NO_CALIBRATION,
          "Spurious-flag probability of the screening algorithm.",
          "Higher -> more burden on truthful firms, more withdrawal.",
          True),
    _spec("HUB-04", "hub_processing_delay_days",
          "PrescreeningParameters.processing_delay_days", "days",
          C.PRESCREEN_PROCESSING_DELAY_DAYS, 0, 20, "EXPERIMENT",
          "illustrative_scenario", NO_CALIBRATION,
          "Operational review delay withholding drafts from publication.",
          "Longer -> later publication, larger reporting delay.", True,
          integer=True),
    _spec("HUB-05", "prescreen_max_employees",
          "PrescreeningParameters.max_employees", "employees",
          C.PRESCREEN_MAX_EMPLOYEES, None, None, "LEGAL-ANCHOR",
          "legally_mandated",
          _SRC_2026_470 + "; Art. 29ca / recital 12 protected-undertaking "
          "line", "Population the voluntary service targets; never an "
          "exemption.", "n/a (scope line).", False),
    _spec("HUB-06", "prescreen_uptake_honest",
          "constants.PRESCREEN_UPTAKE_HONEST", "probability",
          C.PRESCREEN_UPTAKE_HONEST, None, None, "EXPERIMENT",
          "illustrative_scenario", NO_CALIBRATION,
          "Baseline voluntary uptake, honest strategy (scaled by "
          "HUB-01 in the campaign).",
          "Higher -> larger treated share among honest firms.", False),
    # ---------------- connector (Regime C) ------------------------------ #
    _spec("CON-01", "connector_coverage_scale",
          "ConnectorParameters.coverage_scale", "x coverage",
          1.0, 0.5, 1.2, "EXPERIMENT", "illustrative_scenario",
          NO_CALIBRATION,
          "Scales each register's observational coverage (clamped to "
          "[0.05, 1]).",
          "Lower -> weaker reconciliation power, more incomplete-coverage "
          "classifications.", True),
    _spec("CON-02", "connector_mismatch_probability",
          "ConnectorParameters.mismatch_probability", "probability",
          C.CONNECTOR_MISMATCH_PROBABILITY, 0.0, 0.10, "EXPERIMENT",
          "illustrative_scenario", NO_CALIBRATION,
          "Wrong facility/firm matching probability per transfer.",
          "Higher -> more false conflicts, more dispute load.", True),
    _spec("CON-03", "connector_register_error_probability",
          "ConnectorParameters.register_error_probability", "probability",
          C.CONNECTOR_REGISTER_ERROR_PROBABILITY, 0.0, 0.05, "EXPERIMENT",
          "illustrative_scenario", NO_CALIBRATION,
          "Register-error probability per transfer (correction lifecycle "
          "follows).",
          "Higher -> more erroneous evidence, more conflicts.", True),
    _spec("CON-04", "connector_stale_probability",
          "ConnectorParameters.stale_probability", "probability",
          C.CONNECTOR_STALE_PROBABILITY, 0.0, 0.25, "EXPERIMENT",
          "illustrative_scenario", NO_CALIBRATION,
          "Probability a transfer returns a genuinely old reading.",
          "Higher -> wider comparability error bands.", True),
    _spec("CON-05", "connector_downtime_probability",
          "ConnectorParameters.downtime_probability", "probability",
          C.CONNECTOR_DOWNTIME_PROBABILITY, 0.0, 0.10, "EXPERIMENT",
          "illustrative_scenario", NO_CALIBRATION,
          "Per-period-and-source downtime probability.",
          "Higher -> fewer transfers, weaker reconciliation.", True),
    _spec("CON-06", "connector_correction_delay_days",
          "ConnectorParameters.correction_delay_days", "days",
          C.CONNECTOR_CORRECTION_DELAY_DAYS, 10, 120, "EXPERIMENT",
          "illustrative_scenario", NO_CALIBRATION,
          "Register-error correction turnaround (also answers "
          "supervisory re-verification requests).",
          "Longer -> slower conflict resolution under Regime C.", True,
          integer=True),
    _spec("CON-07", "connector_meter_relative_error",
          "ConnectorParameters.meter_relative_error", "relative sigma",
          C.CONNECTOR_METER_RELATIVE_ERROR, None, None, "EXPERIMENT",
          "reference_class",
          "Utility-grade electricity metering accuracy classes are ~0.5-2% "
          "(order-of-magnitude reference); " + NO_CALIBRATION,
          "Strictly positive measurement error of certified sources.",
          "Higher -> noisier connector evidence.", False),
    _spec("CON-08", "connector_cyber_incident_probability",
          "ConnectorParameters.cyber_incident_probability", "probability",
          C.CONNECTOR_CYBER_INCIDENT_PROBABILITY, None, None,
          "EXPERIMENT", "illustrative_scenario", NO_CALIBRATION,
          "Cyber-incident probability per period and source.",
          "Higher -> more suspensions and privacy risk.", False),
    # ---------------- consumers, investors, workforce ------------------- #
    _spec("DEM-01", "consumer_preference_scale",
          "Simulation(consumer_preference_scale=...)", "x preference",
          1.0, 0.5, 1.5, "STYLIZATION", "illustrative_scenario",
          NO_CALIBRATION,
          "Scales every segment's environmental preference.",
          "Higher -> larger demand response to green claims and "
          "discrepancies.", True),
    _spec("DEM-02", "consumer_discrepancy_sensitivity",
          "Simulation(consumer_discrepancy_sensitivity=...)", "x penalty",
          1.0, 0.25, 2.5, "STYLIZATION", "illustrative_scenario",
          NO_CALIBRATION,
          "Scales the utility penalty of a perceived claim/evidence "
          "divergence.",
          "Higher -> greenwashing-to-demand channel strengthens.", True),
    _spec("DEM-03", "consumer_daily_budget",
          "Simulation(consumer_daily_budget=...)", "EUR/day", 1000.0,
          None, None, "STYLIZATION", "illustrative_scenario",
          NO_CALIBRATION,
          "Exogenous consumer budget injection (a numeraire; results "
          "scale with it).", "Scale parameter only.", False),
    _spec("INV-01", "investor_sophisticated_fraction",
          "Simulation(investor_sophisticated_fraction=...)", "share",
          C.SOPHISTICATED_FRACTION, 0.05, 0.80, "STYLIZATION",
          "illustrative_scenario", NO_CALIBRATION,
          "Share of fundamentalists inspecting linked evidence.",
          "Higher -> faster price incorporation of controversies.", True),
    _spec("INV-02", "investor_controversy_scale",
          "Simulation(investor_controversy_scale=...)", "x discount",
          1.0, 0.25, 2.0, "STYLIZATION", "illustrative_scenario",
          NO_CALIBRATION,
          "Scales the controversy discount in investor fair values.",
          "Higher -> larger valuation response to published decisions.",
          True),
    _spec("WRK-01", "workforce_trust_loss_rate",
          "WorkforceState.trust_loss_rate", "trust/discrepancy",
          0.45, 0.10, 1.00, "STYLIZATION", "illustrative_scenario",
          NO_CALIBRATION,
          "Trust lost per unit of observable internal discrepancy.",
          "Higher -> stronger turnover/productivity response.", True),
    _spec("WRK-02", "workforce_trust_recovery_rate",
          "WorkforceState.trust_recovery_rate", "trust/day",
          0.0015, 0.0005, 0.0100, "STYLIZATION", "illustrative_scenario",
          NO_CALIBRATION,
          "Daily recovery toward the 0.85 anchor on quiet truthful days.",
          "Higher -> faster rehabilitation after incidents.", True),
    _spec("WRK-03", "workforce_base_turnover",
          "WorkforceState.base_annual_turnover", "share/yr", 0.10, None,
          None, "STYLIZATION", "reference_class",
          "EU labour-market annual separation rates are commonly in the "
          "10-20% range (order-of-magnitude reference class); "
          + NO_CALIBRATION,
          "Baseline annual turnover; cap 30%.",
          "Higher -> larger replacement-cost channel.", False),
    _spec("GHU-01", "compliance_burden_scale",
          "Simulation(compliance_burden_scale=...)", "x burden",
          1.0, 0.25, 2.50, "STYLIZATION", "illustrative_scenario",
          NO_CALIBRATION,
          "Scales the perceived compliance burden that chills voluntary "
          "truthful communication (greenhushing driver).",
          "Higher -> more greenhushing at given strictness.", True),
    # ---------------- evaluation and comparison ------------------------- #
    _spec("EVL-01", "social_discount_rate",
          "PolicyOutcomeEvaluator(discount_rate_annual=...)", "1/yr",
          C.SOCIAL_DISCOUNT_RATE_DEFAULT, 0.0, 0.07, "EXPERIMENT",
          "reference_class", _SRC_BETTER_REG,
          "Discounts policy costs and exposure-weighted harm for "
          "comparison; undiscounted ledgers always preserved.",
          "Higher -> later harms/costs matter less; can flip rankings "
          "on long horizons.", True),
    _spec("EVL-02", "eval_materiality_threshold",
          "constants.EVAL_MATERIALITY_THRESHOLD", "relative divergence",
          C.EVAL_MATERIALITY_THRESHOLD, None, None, "EXPERIMENT",
          "illustrative_scenario", NO_CALIBRATION,
          "Research-evaluator line for a material true overstatement.",
          "Higher -> fewer claims counted as material.", False),
    _spec("EVL-03", "eval_regulator_cost_per_conflict",
          "constants.EVAL_REGULATOR_COST_PER_CONFLICT", "EUR",
          C.EVAL_REGULATOR_COST_PER_CONFLICT, None, None, "EXPERIMENT",
          "illustrative_scenario", NO_CALIBRATION,
          "Unit cost of one conflict investigation (evaluator only).",
          "Higher -> conflict-heavy regimes look costlier.", False),
    _spec("EVL-04", "policy_score_weights",
          "PolicyScoreWeights (5 scenarios)", "weights", "see class",
          None, None, "EXPERIMENT", "illustrative_scenario",
          NO_CALIBRATION,
          "Composite-score weights; the campaign reports rank frequency "
          "ACROSS the five scenarios per draw instead of sampling "
          "weights continuously.",
          "Different weights can and do change the winner (reported).",
          False),
    # ---------------- legal calendar (scenario law) --------------------- #
    _spec("LAW-01", "empowering_consumers_application",
          "LegalRegime (2024/825 application)", "date", "2026-09-27",
          None, None, "LEGAL", "legally_mandated", _SRC_2024_825,
          "Per-se consumer rules active from this date.",
          "n/a.", False),
    _spec("LAW-02", "csrd_scope_thresholds",
          "LegalRegime.csrd_in_scope", "EUR / employees",
          ">450m AND >1000", None, None, "LEGAL", "legally_mandated",
          _SRC_2026_470 + "; recital 7, Art. 2(4)",
          "Mandatory-reporting scope test (legal-scope units only; never "
          "a sanction base).", "n/a.", False),
    _spec("LAW-03", "ucpd_baseline", "LegalRegime (UCPD track)", "n/a",
          "active", None, None, "LEGAL", "legally_mandated", _SRC_UCPD,
          "General misleading-practice rules throughout.", "n/a.",
          False),
)


def registry_by_name() -> dict[str, ParameterSpec]:
    return {spec.name: spec for spec in REGISTRY}


def gsa_space() -> dict[str, ParameterSpec]:
    """The sampled dimensions of the global sensitivity campaign."""
    return {spec.name: spec for spec in REGISTRY if spec.gsa_eligible}


def gsa_defaults() -> dict[str, float]:
    return {name: float(spec.default)
            for name, spec in gsa_space().items()}


def build_simulation_kwargs(sample: Mapping[str, float]) -> dict[str, Any]:
    """Translate one sampled point into Simulation constructor kwargs.

    Missing keys fall back to registry defaults, so partial samples (for
    one-at-a-time experiments) remain valid.
    """
    from market_sim.greenwashing_supervision import SupervisionParameters
    from market_sim.policy_regimes import (ConnectorParameters,
                                           PrescreeningParameters)

    def value(name: str) -> float:
        spec = registry_by_name()[name]
        raw = float(sample.get(name, spec.default))
        if spec.integer:
            raw = int(round(raw))
        return raw

    supervision = SupervisionParameters(
        evidence_request_capacity=int(value("evidence_request_capacity")),
        investigation_capacity=int(value("investigation_capacity")),
        random_surveillance_share=value("random_surveillance_share"),
        correction_window_days=int(value("correction_window_days")),
        sim_turnover_balance_multiple=value(
            "sim_turnover_balance_multiple"),
        benefit_multiplier=value("benefit_multiplier"),
        affected_revenue_rate=value("affected_revenue_rate"),
        conflict_capacity_share=value("conflict_capacity_share"),
        conflict_resolution_days=int(value("conflict_resolution_days")),
    )
    prescreening = PrescreeningParameters(
        strictness=value("hub_strictness"),
        noise=value("hub_noise"),
        participation_scale=value("hub_participation_scale"),
        processing_delay_days=int(value("hub_processing_delay_days")),
    )
    connector = ConnectorParameters(
        coverage_scale=value("connector_coverage_scale"),
        mismatch_probability=value("connector_mismatch_probability"),
        register_error_probability=value(
            "connector_register_error_probability"),
        stale_probability=value("connector_stale_probability"),
        downtime_probability=value("connector_downtime_probability"),
        correction_delay_days=int(value("connector_correction_delay_days")),
    )
    return {
        "supervision_parameters": supervision,
        "prescreening_parameters": prescreening,
        "connector_parameters": connector,
        "regulatory_strictness": value("regulatory_strictness"),
        "consumer_preference_scale": value("consumer_preference_scale"),
        "consumer_discrepancy_sensitivity": value(
            "consumer_discrepancy_sensitivity"),
        "investor_sophisticated_fraction": value(
            "investor_sophisticated_fraction"),
        "investor_controversy_scale": value("investor_controversy_scale"),
        "workforce_trust_loss_rate": value("workforce_trust_loss_rate"),
        "workforce_trust_recovery_rate": value(
            "workforce_trust_recovery_rate"),
        "compliance_burden_scale": value("compliance_burden_scale"),
    }


# --------------------------------------------------------------------------- #
# Appendix exports
# --------------------------------------------------------------------------- #
_EXPORT_FIELDS = [f.name for f in fields(ParameterSpec)]


def export_csv(path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = _csv.DictWriter(handle, fieldnames=_EXPORT_FIELDS)
        writer.writeheader()
        for spec in REGISTRY:
            writer.writerow(spec.to_dict())
    print(f"Parameter registry exported to '{path}'.")


def export_markdown(path: str) -> None:
    lines = [
        "# Parameter registry (appendix table)",
        "",
        "Classification (LEGAL / LEGAL-ANCHOR / STYLIZATION / EXPERIMENT)",
        "states the parameter's ROLE; the evidence class states what",
        "supports its VALUE. No behavioural parameter of this model is",
        "empirically calibrated: `reference_class` anchors only the order",
        "of magnitude to a named public reference, and every",
        "`illustrative_scenario` value carries the statement:",
        f"> {NO_CALIBRATION}",
        "",
        "GSA = enters the global sensitivity campaign",
        "(`market_sim/sensitivity_campaign.py`) over [low, high].",
        "",
        "| ID | Name | Location | Unit | Default | Low | High | Class |"
        " Evidence | GSA | Expected direction |",
        "|---|---|---|---|---:|---:|---:|---|---|---|---|",
    ]
    for spec in REGISTRY:
        low = "" if spec.low is None else f"{spec.low:g}"
        high = "" if spec.high is None else f"{spec.high:g}"
        lines.append(
            f"| {spec.parameter_id} | `{spec.name}` | `{spec.location}` "
            f"| {spec.unit} | {spec.default} | {low} | {high} "
            f"| {spec.classification} | {spec.evidence_class} "
            f"| {'yes' if spec.gsa_eligible else 'no'} "
            f"| {spec.expected_direction} |")
    lines.append("")
    lines.append("## Sources and justifications")
    lines.append("")
    for spec in REGISTRY:
        lines.append(f"### {spec.parameter_id} `{spec.name}`")
        lines.append("")
        lines.append(f"- **Justification**: {spec.justification}")
        lines.append(f"- **Source**: {spec.source}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    print(f"Parameter registry (Markdown) exported to '{path}'.")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Export the parameter registry appendix table.")
    parser.add_argument("--csv", default="docs/parameter_registry.csv")
    parser.add_argument("--markdown",
                        default="docs/PARAMETER_REGISTRY.md")
    args = parser.parse_args()
    export_csv(args.csv)
    export_markdown(args.markdown)


if __name__ == "__main__":
    main()
