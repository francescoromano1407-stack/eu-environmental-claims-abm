# Parameter registry (appendix table)

Classification (LEGAL / LEGAL-ANCHOR / STYLIZATION / EXPERIMENT)
states the parameter's ROLE; the evidence class states what
supports its VALUE. No behavioural parameter of this model is
empirically calibrated: `reference_class` anchors only the order
of magnitude to a named public reference, and every
`illustrative_scenario` value carries the statement:
> No direct empirical calibration; scenario range used for sensitivity analysis.

GSA = enters the global sensitivity campaign
(`market_sim/sensitivity_campaign.py`) over [low, high].

| ID | Name | Location | Unit | Default | Low | High | Class | Evidence | GSA | Expected direction |
|---|---|---|---|---:|---:|---:|---|---|---|---|
| SAN-01 | `sim_turnover_balance_multiple` | `SupervisionParameters.sim_turnover_balance_multiple` | x corporate balance | 1.5 | 0.5 | 3 | STYLIZATION | reference_class | yes | Higher -> larger sanction bases -> more deterrence, possibly more greenhushing. |
| SAN-02 | `benefit_multiplier` | `SupervisionParameters.benefit_multiplier` | x benefit | 1.5 | 0.5 | 3 | EXPERIMENT | illustrative_scenario | yes | Higher -> stronger deterrence of profitable overstatement. |
| SAN-03 | `affected_revenue_rate` | `SupervisionParameters.affected_revenue_rate` | share/severity | 0.02 | 0.005 | 0.06 | EXPERIMENT | illustrative_scenario | yes | Higher -> larger penalties for high-exposure channels. |
| SAN-04 | `ordinary_penalty_cap_rate` | `SupervisionParameters.ordinary_penalty_cap_rate` | share of sim turnover | 0.01 |  |  | EXPERIMENT | illustrative_scenario | no | Higher -> binding less often. |
| SAN-05 | `consumer_cross_border_cap_rate` | `SupervisionParameters.consumer_cross_border_cap_rate` | share of turnover | 0.04 |  |  | LEGAL-ANCHOR | reference_class | no | n/a (fixed legal anchor). |
| SAN-06 | `csddd_cap_rate` | `SupervisionParameters.csddd_cap_rate` | share of turnover | 0.03 |  |  | LEGAL | legally_mandated | no | n/a (legal ceiling). |
| SAN-07 | `penalty_repeat_escalation_rate` | `constants.PENALTY_REPEAT_ESCALATION_RATE` | x per repeat | 0.5 |  |  | EXPERIMENT | illustrative_scenario | no | Higher -> harsher recidivism response. |
| CAP-01 | `evidence_request_capacity` | `SupervisionParameters.evidence_request_capacity` | cases/period | 20 | 5 | 40 | EXPERIMENT | reference_class | yes | Higher -> more coverage, more false positives possible. |
| CAP-02 | `investigation_capacity` | `SupervisionParameters.investigation_capacity` | investigations/period | 5 | 1 | 12 | EXPERIMENT | reference_class | yes | Higher -> shorter queues, faster decisions. |
| CAP-03 | `random_surveillance_share` | `SupervisionParameters.random_surveillance_share` | probability | 0.1 | 0 | 0.3 | EXPERIMENT | illustrative_scenario | yes | Higher -> better coverage of low-risk-score abuse, more capacity spent on clean claims. |
| CAP-04 | `correction_window_days` | `SupervisionParameters.correction_window_days` | days | 30 | 10 | 90 | EXPERIMENT | illustrative_scenario | yes | Longer -> slower correction, more exposure days. |
| CAP-05 | `regulatory_strictness` | `Simulation(regulatory_strictness=...)` | index 0-1 | 0.55 | 0 | 1 | EXPERIMENT | illustrative_scenario | yes | Higher -> less overstatement AND more greenhushing (chilling). |
| CNF-01 | `conflict_capacity_share` | `SupervisionParameters.conflict_capacity_share` | share | 0.2 | 0 | 0.6 | EXPERIMENT | illustrative_scenario | yes | Higher -> faster dispute resolution, fewer enforcement slots. |
| CNF-02 | `conflict_resolution_days` | `SupervisionParameters.conflict_resolution_days` | days | 20 | 5 | 60 | EXPERIMENT | illustrative_scenario | yes | Longer -> longer exposure of disputed records. |
| CNF-03 | `conflict_priority` | `SupervisionParameters.conflict_priority` | priority 0-1 | 0.85 |  |  | EXPERIMENT | illustrative_scenario | no | Higher -> disputes open sooner. |
| CNF-04 | `conflict_reverification_timeout_days` | `SupervisionParameters.conflict_reverification_timeout_days` | days | 90 |  |  | EXPERIMENT | illustrative_scenario | no | Longer -> more conflicts resolved on real re-measurements. |
| CNF-05 | `conflict_credibility_margin` | `SupervisionParameters.conflict_credibility_margin` | confidence points | 0.15 |  |  | EXPERIMENT | illustrative_scenario | no | Higher -> more dismissals, fewer wrong resolutions. |
| CNF-06 | `source_reverification_delay_days` | `constants.SOURCE_REVERIFICATION_DELAY_DAYS` | days | 30 |  |  | EXPERIMENT | illustrative_scenario | no | Longer -> slower dispute resolution. |
| HUB-01 | `hub_participation_scale` | `PrescreeningParameters.participation_scale` | x propensity | 1.0 | 0.2 | 1.5 | EXPERIMENT | illustrative_scenario | yes | Higher -> more drafts screened (ITT effect grows). |
| HUB-02 | `hub_strictness` | `PrescreeningParameters.strictness` | index 0-1 | 0.5 | 0.1 | 0.95 | EXPERIMENT | illustrative_scenario | yes | Higher -> more flags, more revisions AND more withdrawals (greenhushing). |
| HUB-03 | `hub_noise` | `PrescreeningParameters.noise` | probability | 0.08 | 0 | 0.5 | EXPERIMENT | illustrative_scenario | yes | Higher -> more burden on truthful firms, more withdrawal. |
| HUB-04 | `hub_processing_delay_days` | `PrescreeningParameters.processing_delay_days` | days | 5 | 0 | 20 | EXPERIMENT | illustrative_scenario | yes | Longer -> later publication, larger reporting delay. |
| HUB-05 | `prescreen_max_employees` | `PrescreeningParameters.max_employees` | employees | 1000.0 |  |  | LEGAL-ANCHOR | legally_mandated | no | n/a (scope line). |
| HUB-06 | `prescreen_uptake_honest` | `constants.PRESCREEN_UPTAKE_HONEST` | probability | 0.9 |  |  | EXPERIMENT | illustrative_scenario | no | Higher -> larger treated share among honest firms. |
| CON-01 | `connector_coverage_scale` | `ConnectorParameters.coverage_scale` | x coverage | 1.0 | 0.5 | 1.2 | EXPERIMENT | illustrative_scenario | yes | Lower -> weaker reconciliation power, more incomplete-coverage classifications. |
| CON-02 | `connector_mismatch_probability` | `ConnectorParameters.mismatch_probability` | probability | 0.02 | 0 | 0.1 | EXPERIMENT | illustrative_scenario | yes | Higher -> more false conflicts, more dispute load. |
| CON-03 | `connector_register_error_probability` | `ConnectorParameters.register_error_probability` | probability | 0.01 | 0 | 0.05 | EXPERIMENT | illustrative_scenario | yes | Higher -> more erroneous evidence, more conflicts. |
| CON-04 | `connector_stale_probability` | `ConnectorParameters.stale_probability` | probability | 0.05 | 0 | 0.25 | EXPERIMENT | illustrative_scenario | yes | Higher -> wider comparability error bands. |
| CON-05 | `connector_downtime_probability` | `ConnectorParameters.downtime_probability` | probability | 0.01 | 0 | 0.1 | EXPERIMENT | illustrative_scenario | yes | Higher -> fewer transfers, weaker reconciliation. |
| CON-06 | `connector_correction_delay_days` | `ConnectorParameters.correction_delay_days` | days | 60 | 10 | 120 | EXPERIMENT | illustrative_scenario | yes | Longer -> slower conflict resolution under Regime C. |
| CON-07 | `connector_meter_relative_error` | `ConnectorParameters.meter_relative_error` | relative sigma | 0.01 |  |  | EXPERIMENT | reference_class | no | Higher -> noisier connector evidence. |
| CON-08 | `connector_cyber_incident_probability` | `ConnectorParameters.cyber_incident_probability` | probability | 0.002 |  |  | EXPERIMENT | illustrative_scenario | no | Higher -> more suspensions and privacy risk. |
| DEM-01 | `consumer_preference_scale` | `Simulation(consumer_preference_scale=...)` | x preference | 1.0 | 0.5 | 1.5 | STYLIZATION | illustrative_scenario | yes | Higher -> larger demand response to green claims and discrepancies. |
| DEM-02 | `consumer_discrepancy_sensitivity` | `Simulation(consumer_discrepancy_sensitivity=...)` | x penalty | 1.0 | 0.25 | 2.5 | STYLIZATION | illustrative_scenario | yes | Higher -> greenwashing-to-demand channel strengthens. |
| DEM-03 | `consumer_daily_budget` | `Simulation(consumer_daily_budget=...)` | EUR/day | 1000.0 |  |  | STYLIZATION | illustrative_scenario | no | Scale parameter only. |
| INV-01 | `investor_sophisticated_fraction` | `Simulation(investor_sophisticated_fraction=...)` | share | 0.3 | 0.05 | 0.8 | STYLIZATION | illustrative_scenario | yes | Higher -> faster price incorporation of controversies. |
| INV-02 | `investor_controversy_scale` | `Simulation(investor_controversy_scale=...)` | x discount | 1.0 | 0.25 | 2 | STYLIZATION | illustrative_scenario | yes | Higher -> larger valuation response to published decisions. |
| WRK-01 | `workforce_trust_loss_rate` | `WorkforceState.trust_loss_rate` | trust/discrepancy | 0.45 | 0.1 | 1 | STYLIZATION | illustrative_scenario | yes | Higher -> stronger turnover/productivity response. |
| WRK-02 | `workforce_trust_recovery_rate` | `WorkforceState.trust_recovery_rate` | trust/day | 0.0015 | 0.0005 | 0.01 | STYLIZATION | illustrative_scenario | yes | Higher -> faster rehabilitation after incidents. |
| WRK-03 | `workforce_base_turnover` | `WorkforceState.base_annual_turnover` | share/yr | 0.1 |  |  | STYLIZATION | reference_class | no | Higher -> larger replacement-cost channel. |
| GHU-01 | `compliance_burden_scale` | `Simulation(compliance_burden_scale=...)` | x burden | 1.0 | 0.25 | 2.5 | STYLIZATION | illustrative_scenario | yes | Higher -> more greenhushing at given strictness. |
| EVL-01 | `social_discount_rate` | `PolicyOutcomeEvaluator(discount_rate_annual=...)` | 1/yr | 0.03 | 0 | 0.07 | EXPERIMENT | reference_class | yes | Higher -> later harms/costs matter less; can flip rankings on long horizons. |
| EVL-02 | `eval_materiality_threshold` | `constants.EVAL_MATERIALITY_THRESHOLD` | relative divergence | 0.02 |  |  | EXPERIMENT | illustrative_scenario | no | Higher -> fewer claims counted as material. |
| EVL-03 | `eval_regulator_cost_per_conflict` | `constants.EVAL_REGULATOR_COST_PER_CONFLICT` | EUR | 250.0 |  |  | EXPERIMENT | illustrative_scenario | no | Higher -> conflict-heavy regimes look costlier. |
| EVL-04 | `policy_score_weights` | `PolicyScoreWeights (5 scenarios)` | weights | see class |  |  | EXPERIMENT | illustrative_scenario | no | Different weights can and do change the winner (reported). |
| LAW-01 | `empowering_consumers_application` | `LegalRegime (2024/825 application)` | date | 2026-09-27 |  |  | LEGAL | legally_mandated | no | n/a. |
| LAW-02 | `csrd_scope_thresholds` | `LegalRegime.csrd_in_scope` | EUR / employees | >450m AND >1000 |  |  | LEGAL | legally_mandated | no | n/a. |
| LAW-03 | `ucpd_baseline` | `LegalRegime (UCPD track)` | n/a | active |  |  | LEGAL | legally_mandated | no | n/a. |

## Sources and justifications

### SAN-01 `sim_turnover_balance_multiple`

- **Justification**: Bridge between simulation-scale balances and the statutory turnover-based ceiling rates (Part I.1).
- **Source**: Asset-turnover ratios of listed EU non-financials cluster roughly between 0.5 and 2 (order-of-magnitude reference class from standard financial-statement analysis); No direct empirical calibration; scenario range used for sensitivity analysis.

### SAN-02 `benefit_multiplier`

- **Justification**: Disgorgement-plus factor on the estimated benefit of the misleading claim.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### SAN-03 `affected_revenue_rate`

- **Justification**: Revenue-linked component of the experimental sanction formula.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### SAN-04 `ordinary_penalty_cap_rate`

- **Justification**: Ordinary simulated ceiling; the 4% consumer legal anchor and 3% CSDDD ceiling are track-gated separately. Held fixed in the campaign to keep the track-gating interpretable.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### SAN-05 `consumer_cross_border_cap_rate`

- **Justification**: Exact in-model cap anchored to the statutory minimum maximum, available only for coordinated widespread cross-border consumer infringements; EU law does not fix 4% as a uniform ceiling.
- **Source**: Directive (EU) 2019/2161, Art. 3(6) amending UCPD Art. 13 (national maximum must be at least 4% of relevant turnover for widespread infringements), ELI: dir/2019/2161/oj

### SAN-06 `csddd_cap_rate`

- **Justification**: Callable only for due-diligence cases.
- **Source**: Directive (EU) 2026/470 as documented in docs/EU_GREENWASHING_MODEL.md (stylized in-model legal scenario; treat all derived values as scenario law); Art. 4(19) amending CSDDD Art. 27(4)

### SAN-07 `penalty_repeat_escalation_rate`

- **Justification**: Repeat-offender escalation below the legal ceiling.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### CAP-01 `evidence_request_capacity`

- **Justification**: Screening capacity per reporting period.
- **Source**: EU consumer-protection authorities decide tens to a few hundred misleading-advertising cases per year against far larger claim volumes (order of magnitude from published CPC network sweeps); No direct empirical calibration; scenario range used for sensitivity analysis.

### CAP-02 `investigation_capacity`

- **Justification**: Formal-investigation capacity per period, shared with conflict investigations (Part J).
- **Source**: Formal proceedings are an order of magnitude rarer than screenings (same reference class as CAP-01); No direct empirical calibration; scenario range used for sensitivity analysis.

### CAP-03 `random_surveillance_share`

- **Justification**: Random-surveillance draw deterring pure risk-score gaming.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### CAP-04 `correction_window_days`

- **Justification**: First-time correctable errors receive this compliance window.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### CAP-05 `regulatory_strictness`

- **Justification**: Perceived enforcement strictness entering the corporate communication optimizer.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### CNF-01 `conflict_capacity_share`

- **Justification**: Investigation-capacity share reserved for evidence-conflict disputes (dedicated data-dispute desk).
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### CNF-02 `conflict_resolution_days`

- **Justification**: Procedural duration of one conflict investigation.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### CNF-03 `conflict_priority`

- **Justification**: Transparent queue priority of conflict cases (below whistleblower/complaint/connector triggers).
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### CNF-04 `conflict_reverification_timeout_days`

- **Justification**: Fallback deadline for the credibility-based resolution.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### CNF-05 `conflict_credibility_margin`

- **Justification**: Decisive margin of the credibility fallback.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### CNF-06 `source_reverification_delay_days`

- **Justification**: Third-party re-measurement turnaround.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### HUB-01 `hub_participation_scale`

- **Justification**: Scales every strategy's voluntary participation propensity.
- **Source**: Baseline uptakes (0.90/0.60/0.35 by strategy) have no empirical source; No direct empirical calibration; scenario range used for sensitivity analysis.

### HUB-02 `hub_strictness`

- **Justification**: Issue-severity threshold scaling of the screening algorithm.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### HUB-03 `hub_noise`

- **Justification**: Spurious-flag probability of the screening algorithm.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### HUB-04 `hub_processing_delay_days`

- **Justification**: Operational review delay withholding drafts from publication.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### HUB-05 `prescreen_max_employees`

- **Justification**: Population the voluntary service targets; never an exemption.
- **Source**: Directive (EU) 2026/470 as documented in docs/EU_GREENWASHING_MODEL.md (stylized in-model legal scenario; treat all derived values as scenario law); Art. 29ca / recital 12 protected-undertaking line

### HUB-06 `prescreen_uptake_honest`

- **Justification**: Baseline voluntary uptake, honest strategy (scaled by HUB-01 in the campaign).
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### CON-01 `connector_coverage_scale`

- **Justification**: Scales each register's observational coverage (clamped to [0.05, 1]).
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### CON-02 `connector_mismatch_probability`

- **Justification**: Wrong facility/firm matching probability per transfer.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### CON-03 `connector_register_error_probability`

- **Justification**: Register-error probability per transfer (correction lifecycle follows).
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### CON-04 `connector_stale_probability`

- **Justification**: Probability a transfer returns a genuinely old reading.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### CON-05 `connector_downtime_probability`

- **Justification**: Per-period-and-source downtime probability.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### CON-06 `connector_correction_delay_days`

- **Justification**: Register-error correction turnaround (also answers supervisory re-verification requests).
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### CON-07 `connector_meter_relative_error`

- **Justification**: Strictly positive measurement error of certified sources.
- **Source**: Utility-grade electricity metering accuracy classes are ~0.5-2% (order-of-magnitude reference); No direct empirical calibration; scenario range used for sensitivity analysis.

### CON-08 `connector_cyber_incident_probability`

- **Justification**: Cyber-incident probability per period and source.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### DEM-01 `consumer_preference_scale`

- **Justification**: Scales every segment's environmental preference.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### DEM-02 `consumer_discrepancy_sensitivity`

- **Justification**: Scales the utility penalty of a perceived claim/evidence divergence.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### DEM-03 `consumer_daily_budget`

- **Justification**: Exogenous consumer budget injection (a numeraire; results scale with it).
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### INV-01 `investor_sophisticated_fraction`

- **Justification**: Share of fundamentalists inspecting linked evidence.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### INV-02 `investor_controversy_scale`

- **Justification**: Scales the controversy discount in investor fair values.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### WRK-01 `workforce_trust_loss_rate`

- **Justification**: Trust lost per unit of observable internal discrepancy.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### WRK-02 `workforce_trust_recovery_rate`

- **Justification**: Daily recovery toward the 0.85 anchor on quiet truthful days.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### WRK-03 `workforce_base_turnover`

- **Justification**: Baseline annual turnover; cap 30%.
- **Source**: EU labour-market annual separation rates are commonly in the 10-20% range (order-of-magnitude reference class); No direct empirical calibration; scenario range used for sensitivity analysis.

### GHU-01 `compliance_burden_scale`

- **Justification**: Scales the perceived compliance burden that chills voluntary truthful communication (greenhushing driver).
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### EVL-01 `social_discount_rate`

- **Justification**: Discounts policy costs and exposure-weighted harm for comparison; undiscounted ledgers always preserved.
- **Source**: European Commission Better Regulation Toolbox (Tool #61 discounting guidance, ~3%/yr social discount rate) -- reference class, not an estimate for this model

### EVL-02 `eval_materiality_threshold`

- **Justification**: Research-evaluator line for a material true overstatement.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### EVL-03 `eval_regulator_cost_per_conflict`

- **Justification**: Unit cost of one conflict investigation (evaluator only).
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### EVL-04 `policy_score_weights`

- **Justification**: Composite-score weights; the campaign reports rank frequency ACROSS the five scenarios per draw instead of sampling weights continuously.
- **Source**: No direct empirical calibration; scenario range used for sensitivity analysis.

### LAW-01 `empowering_consumers_application`

- **Justification**: Per-se consumer rules active from this date.
- **Source**: Directive (EU) 2024/825 (Empowering Consumers), ELI: dir/2024/825/oj

### LAW-02 `csrd_scope_thresholds`

- **Justification**: Mandatory-reporting scope test (legal-scope units only; never a sanction base).
- **Source**: Directive (EU) 2026/470 as documented in docs/EU_GREENWASHING_MODEL.md (stylized in-model legal scenario; treat all derived values as scenario law); recital 7, Art. 2(4)

### LAW-03 `ucpd_baseline`

- **Justification**: General misleading-practice rules throughout.
- **Source**: Directive 2005/29/EC (UCPD), ELI: dir/2005/29/oj
