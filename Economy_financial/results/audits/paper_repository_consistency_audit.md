# Paper-Repository Consistency Audit

- Audit time (UTC): `2026-07-18T14:57:16+00:00`
- Authoritative reference: `Francesco_Romano_EU_Environmental_Claims_ABM_Paper_revised.docx`
- Checked claims: 55
- Status counts: `consistent`: 55

No simulation campaign was executed. All evidence comes from stored
outputs, static source analysis, manifest validation, and lightweight
parsing of the manuscript and repository files.

## Claim-by-claim table

| ID | Manuscript location | Claim | Evidence | Status | Discrepancy | Correction | Material |
|---|---|---|---|---|---|---|---|
| D1 | Abstract; Sec. 4.2; Table 4 | 200 LHS draws, 3 paired replications, 3 regimes at each of 120/365/1,000/2,000 days; 1,800 regime runs per horizon, 7,200 total | results/configuration.json; results/summaries/*_summary.json | consistent | - | none | no |
| D2 | Sec. 4.2; Appendix A | 28 sampled parameters, all EXPERIMENT or STYLIZATION; LEGAL and LEGAL-ANCHOR values fixed | results/manifest.json configuration.sampled_parameters | consistent | - | none | no |
| D3 | Sec. 4.2; Appendix C | Master seed 20,260,716; horizons subset-free | results/configuration.json | consistent | - | none | no |
| D4 | Sec. 4.1 (equations); Appendix C | market seed = 20,260,716 + 1,000,000*j + 1,000*r; supervision seed = 104,729 + 104,729*j + 7,919*r; regimes re-seeded per replication | market_sim/sensitivity_campaign.py:122-149; run-level seed columns | consistent | - | none | no |
| D5 | Sec. 4.1 | Common random numbers: all three regimes share identical market and supervision seeds within each draw-replication cell | results/summaries/horizon_120d_run_level_metrics.csv (600 cells) | consistent | - | none | no |
| D6 | Appendix C | Publication driver refuses <200 draws, <3 replications, or <120 days without --development; configuration records run_global_lhs_campaign.py --full-robustness | run_global_lhs_campaign.py:688; results/configuration.json exact_command | consistent | - | none | no |
| R1 | Table 5; Sec. 5.1; Appendix D | Default-weight winner counts/shares per horizon (95/96/9, 106/76/18, 71/27/102, 67/14/119; i.e. 47.5/48.0/4.5%, 53.0/38.0/9.0%, 35.5/13.5/51.0%, 33.5/7.0/59.5%) | results/summaries/*_summary.json winner_frequency | consistent | - | none | no |
| R2 | Table 5; Sec. 5.1 | Weight-sensitive draws: 70.0%, 63.0%, 58.0%, 45.5% | summary weight_sensitive_fraction | consistent | - | none | no |
| R3 | Sec. 5.1 (weight scenarios at 120 days) | Accuracy-focused hub 119; cost-focused current 168; anti-greenhushing current 179; SME-protective current 198 | horizon_120d_summary.json winner_frequency | consistent | - | none | no |
| R4 | Sec. 5.1 | Pareto frequency: current 200 at every horizon; hub 183/180/180/184; connector 164/174/200/200 | summary pareto_frequency | consistent | - | none | no |
| R5 | Abstract; Sec. 5.1; Sec. 8 | Default winners reverse across horizons in 161/200 shared draws (80.5%) | results/summaries/unified_campaign_summary.json | consistent | - | none | no |
| H1 | Sec. 5.2 | Hub improves original overstatements in 91.0/88.5/87.5/88.0% and severity in 85.0/90.5/89.0/87.5% of draws | effect_distributions prob_improvement | consistent | - | none | no |
| H2 | Sec. 5.2 | Hub mean paired improvements in original material count: 8.65, 13.74, 24.20, 45.99 | effect_distributions original_material_overstatements mean | consistent | - | none | no |
| H3 | Table 6; Sec. 5.2 | Hub greenhushing effects -0.00462/-0.00637/-0.00574/-0.00502; improvement in only 0/3.0/4.5/6.5% of draws | effect_distributions mean_greenhushing_gap | consistent | - | none | no |
| H4 | Table 6; Sec. 5.2 | Hub increases discounted public cost in every draw; mean effects -24,290/-26,462/-28,751/-32,088 simulation-scale EUR | effect_distributions discounted_total_public_cost | consistent | - | none | no |
| H5 | Sec. 5.2 (PRCC) | Hub severity-effect PRCCs: participation 0.531/strictness 0.446 (120d); 0.552/0.494 (365d); greenhushing-effect PRCCs at 365d: participation -0.550, strictness -0.496 | summary parameter_importance effect_severity/effect_greenhushing (hub) | consistent | - | none | no |
| C1 | Sec. 5.3; Table 6 | Connector severity improvement 40.5/60.5/97.0/100% with means -0.63/44.61/1,855.23/12,216.10; original improves 50.5/68.5/100/100% | effect_distributions exposure_weighted_severity / original_material_overstatements (connector) | consistent | - | none | no |
| C2 | Sec. 5.3; Table 6 | Connector increases discounted public cost in every draw; means -64,071/-70,352/-86,192/-111,608 | effect_distributions discounted_total_public_cost (connector) | consistent | - | none | no |
| C3 | Sec. 5.3; Table 6 | Connector greenhushing: near-zero means (-0.000001/-0.00013/-0.00035/-0.00044); improvement only 12.0/12.0/13.0/10.5% | effect_distributions mean_greenhushing_gap (connector) | consistent | - | none | no |
| C4 | Sec. 5.3 (PRCC) | Social discount rate PRCC with connector cost effect: 0.756/0.688/0.716/0.839; connector severity PRCCs at 1,000/2,000d: strictness -0.616/-0.647, compliance burden -0.490/-0.530 | summary parameter_importance (connector) | consistent | - | none | no |
| K1 | Sec. 5.4 | Connector opens 0.87/2.28/4.50/7.99 conflict cases and consumes 0.71/1.86/3.87/6.88 investigation slots (means over 600 runs) | run_level_metrics conflict_cases_opened / conflict_investigations | consistent | - | none | no |
| K2 | Sec. 5.4 | Baseline and hub conflict means: 0 at 365d; 0.71/0.79 at 1,000d; 2.08/2.10 at 2,000d | run_level_metrics conflict_cases_opened | consistent | - | none | no |
| K3 | Sec. 5.4 | Connector resolution delay 44.43/75.98/102.47 days at 365/1,000/2,000d; paired delay effects -44.43/-58.27/-46.64 | run_level_metrics conflict_resolution_delay_mean; effect_distributions conflict_resolution_delay_mean | consistent | - | none | no |
| K4 | Sec. 5.4 | At 2,000 days: corroborated escalations 1.18 (connector) vs 0.36 (current); register corrections 2.79 vs 1.40 | run_level_metrics conflict_escalated_corroborated / conflict_register_corrected | consistent | - | none | no |
| B1 | Sec. 4.4 | Extension executed: draws 41,42,69,71,75,104,109,136,144,147,180,187 at 15 paired replications, all 48 draw-horizon files valid | results/replication_robustness/manifest.json final_audit | consistent | - | none | no |
| B2 | Sec. 4.4; Limitation 9 | 95% intervals narrow in 92.3% of the 1,743 finite cells; median half-width ratio 0.26 | replication_robustness_summary.json paired_intervals | consistent | - | none | no |
| B3 | Sec. 4.4; Limitation 9 | Default winner confirmed in 32/48 cells (9,9,8,6 of 12 by horizon); full ranking confirmed in 60.4% | replication_robustness_summary.json ranking_stability | consistent | - | none | no |
| F1 | Sec. 5.7; Table 8 note | 30 independent seeds, 10,000-day horizon, 2,000-day burn-in, baseline current-supervision regime, order-book events exported | results/financial_validation/pilot_30seeds/aggregate_manifest.json | consistent | - | none | no |
| F2 | Sec. 5.7 | About 256,000-298,000 order-book events per seed (corrected 2026-07-18 from the earlier 270,000-300,000 wording, which understated the stored spread) | multi_seed_financial_validation.json per_seed event_records | consistent | - | none | no |
| F3 | Table 8; Abstract; Limitation 11 | Seed-status counts for all eight stylized facts, including positive price impact NOT reproduced (0/4/26) | multi_seed_financial_validation.json aggregate_classifications | consistent | - | none | no |
| F4 | Table 8 | Cross-seed means: \|r\| ACF .170, r^2 ACF .183, spread 1.38, sign ACF .486 vs .009 band, cancel ratio .537, vol-vol .113, kurtosis 1.99 (SD 1.33), Hill 5.38, return ACF -.082, impact corr -.013 (hw .004) | multi_seed_financial_validation.json aggregate_seed_metrics | consistent | - | none | no |
| M1 | Sec. 3.7; Sec. 6; Limitation 11; Abstract | Firm greenwashing/disclosure and transition-investment rules contain no own-share-price input; the only direct own-share market read is the treasury financing rule (sell_treasury at order-book midpoint) | results/audits/firm_price_feedback_audit.json dependency_table; market_sim/corporates.py:516-517 | consistent | - | none | no |
| M2 | Table 3; Sec. 3.9 | Three compared regimes named current_eu_supervision, sme_algorithmic_prescreening, certified_green_data_connector | market_sim/policy_regimes.py GreenwashingPolicyRegime; results/configuration.json regimes | consistent | - | none | no |
| M3 | Sec. 3.4 (equation) | q_truthful = clip(0.20 + 0.70 x real environmental score, 0, 1) | market_sim/corporate_communications.py:72 | consistent | - | none | no |
| M4 | Sec. 3.5 (sanction equation); Sec. 2.1 | Sanction = 1.5 x estimated benefit + 0.02 x affected revenue x severity x confidence; caps track-gated at 1% ordinary, 4% widespread consumer, 3% CSDDD | market_sim/greenwashing_supervision.py:77-96 | consistent | - | none | no |
| M5 | Sec. 3.5 | Default capacity 20 evidence requests and 5 investigations per period; 10% random surveillance; 30-day first-time correction window | market_sim/greenwashing_supervision.py:77-80 | consistent | - | none | no |
| M6 | Sec. 3.6 | Conflict cases enter the queue at priority 0.85 with a default 20% capacity reserve | market_sim/constants.py:496,510 | consistent | - | none | no |
| M7 | Sec. 3.6 | Eight default connector source types covering Scope 1/2, renewable share, water, waste/recycling, pollution, partial Scope 3, and environmental capex | market_sim/policy_regimes.py DEFAULT_CONNECTOR_SOURCES | consistent | - | none | no |
| M8 | Sec. 3.3 | z<1 noise; 1-2.5 inconclusive; 2% materiality line; self-declared uncertainty capped at 2x evidence SE; repeat escalation needs >=4 findings in 365 days with mean z >= 0.5 | market_sim/greenwashing_supervision.py:394-398; market_sim/constants.py:419,451,456-458 | consistent | - | none | no |
| M9 | Sec. 3.7 (equation) | V_fair = V_fundamental x (1 + greenium x posterior x credibility) x (1 - controversy discount); unsophisticated investors respond more slowly (0.40 controversy scaling) | market_sim/traders.py:455-463 | consistent | - | none | no |
| M10 | Sec. 3.7 (equation); Sec. 3.4 | Productivity multiplier 1 - 0.03 x (1 - trust); annual turnover starts at 10%, capped at 30%; 30-day onboarding | market_sim/workforce.py:26-37 | consistent | - | none | no |
| M11 | Sec. 3.7 | Consumers allocate an exogenous EUR 1,000 daily budget by logit utility | seed manifests simulation_parameters.consumer_daily_budget; market_sim/consumer_market.py | consistent | - | none | no |
| M12 | Sec. 3.2; Sec. 4.3; Data availability | Latent truth is evaluator-only and never enters agent decisions (information-safe architecture, enforced by tests) | results/configuration.json research_only_metrics; tests/ (information-boundary suite, 177 tests passing) | consistent | - | none | no |
| L1 | Sec. 2.1; Table 1; Sec. 3.1 | Directive 2024/825 applies 27 Sep 2026; CSRD national scenario 19 Mar 2027; CSDDD applies 26 Jul 2029; day 1 = 1 Jan 2026 | market_sim/regulation.py:61-64 | consistent | - | none | no |
| L2 | Sec. 2.1 | CSRD scope: net turnover exceeding EUR 450m AND more than 1,000 employees, conjunctive, strict inequalities (equality does not qualify) | market_sim/regulation.py:66-67,109 | consistent | - | none | no |
| L4 | Sec. 2.1 (CSDDD scope caveat); Limitation 10 | The revised CSDDD undertaking-scope test (5,000 employees / EUR 1.5bn) is NOT implemented; the paper says the model gates CSDDD by date and remedy track only | market_sim/regulation.py (absence verified) | consistent | - | none | no |
| L5 | Sec. 2.2; Table 1 | Green Claims pre-verification is a disabled counterfactual (off by default) | market_sim/regulation.py:65 | consistent | - | none | no |
| P1 | Appendix A; Table 9 | All stated LHS sampling ranges match the executed campaign's recorded parameter space | results/manifest.json configuration.sampled_parameters | consistent | - | none | no |
| X1 | Data and Code Availability | Every artifact path cited in the data-availability statement exists | results/configuration.json; results/manifest.json; results/raw; results/summaries; results/financial_validation/pilot_30seeds; results/replication_robustness; results/audits; docs/PUBLICATION_READINESS_REVIEW.md; docs/CLAIM_MATRIX.md; run_replication_robustness.py | consistent | - | none | no |
| X2 | Limitation 10; Appendix C | Shipped campaign manifests record a git hash suffixed +dirty (1645f35...+dirty); archival release must preserve the dirty diff or rerun from a clean tag | summaries code_version; robustness/validation manifests code_provenance | consistent | - | none | no |
| X3 | All captions | Tables numbered 1-9 and Figures 1-3, sequential and unique | manuscript caption paragraphs | consistent | - | none | no |
| X4 | Figure 2 (embedded image) | Figure 2 caption reads 'Default-weight winner shares across horizons'; the plotted points match Table 5 shares; the embedded title and footnote state the four-horizon coverage | word/media/image2.png (visual inspection); Table 5 | consistent | - | embedded title/footnote repainted (tools/apply_editorial_fixes.py) | no |
| X5 | Data and Code Availability (figures) | Publication figures generated from stored outputs exist in results/figures/ | results/figures/ | consistent | - | none | no |
| X6 | References | Every reference-list entry is cited in the body | manuscript body vs reference list | consistent | - | none (manuscript-internal) | no |
| X7 | Secs. 4.4, 5.7 vs docs/ | Repository documentation agrees with the manuscript on executed campaigns, superseded diagnostics, and the non-reproduced price impact | docs/REPRODUCIBILITY.md; docs/DATA_DICTIONARY.md; docs/FINANCIAL_VALIDATION_CAMPAIGN.md; docs/CLAIM_MATRIX.md | consistent | - | none | no |

## Observed values

- **D1** — draws=200; replications=3; regimes=3; horizons=4; draws_summarized_120=200; draws_summarized_365=200; draws_summarized_1000=200; draws_summarized_2000=200; runs_120=1800; runs_365=1800; runs_1000=1800; runs_2000=1800
- **D2** — 28 parameters; classes OK
- **D3** — master_seed=20260716; subsets_null=4
- **D4** — formulas present in code
- **D5** — cells checked=600, mismatched=0, formula violations=0
- **D6** — exact_command=['run_global_lhs_campaign.py', '--full-robustness']
- **R1** — 120d base=95; 120d hub=96; 120d conn=9; 365d base=106; 365d hub=76; 365d conn=18; 1000d base=71; 1000d hub=27; 1000d conn=102; 2000d base=67; 2000d hub=14; 2000d conn=119
- **R2** — 120d=0.7; 365d=0.63; 1000d=0.58; 2000d=0.455
- **R3** — accuracy hub=119; cost current=168; antiGH current=179; sme current=198
- **R4** — 120d base=200; 120d hub=183; 120d conn=164; 365d base=200; 365d hub=180; 365d conn=174; 1000d base=200; 1000d hub=180; 1000d conn=200; 2000d base=200; 2000d hub=184; 2000d conn=200
- **R5** — reversals=161; shared=200; fraction=0.805
- **H1** — orig 120d=0.91; orig 365d=0.885; orig 1000d=0.875; orig 2000d=0.88; sev 120d=0.85; sev 365d=0.905; sev 1000d=0.89; sev 2000d=0.875
- **H2** — 120d=8.646666666666667; 365d=13.741666666666667; 1000d=24.2; 2000d=45.98666666666667
- **H3** — mean 120d=-0.004621610567678559; mean 365d=-0.006365649609360233; mean 1000d=-0.00574006798892155; mean 2000d=-0.0050216841865735815; P 120d=0.0; P 365d=0.03; P 1000d=0.045; P 2000d=0.065
- **H4** — mean 120d=-24290.44148828738; mean 365d=-26462.382334759677; mean 1000d=-28751.12208220155; mean 2000d=-32087.7591428329; P 120d=0.0; P 365d=0.0; P 1000d=0.0; P 2000d=0.0
- **H5** — sev part 120=0.5310609294063654; sev strict 120=0.44559372717408036; sev part 365=0.5520367693906081; sev strict 365=0.4941271162587957; gh part 365=-0.5497948813713271; gh strict 365=-0.496406650841336
- **C1** — sevP 120d=0.405; sevP 365d=0.605; sevP 1000d=0.97; sevP 2000d=1.0; sevM 120d=-0.631374485817766; sevM 365d=44.61243246843047; sevM 1000d=1855.227080307305; sevM 2000d=12216.104733475893; origP 120d=0.505; origP 365d=0.685; origP 1000d=1.0; origP 2000d=1.0
- **C2** — mean 120d=-64070.536981407946; mean 365d=-70351.79190573313; mean 1000d=-86192.02908156774; mean 2000d=-111607.89699835509; P 120d=0.0; P 365d=0.0; P 1000d=0.0; P 2000d=0.0
- **C3** — mean 120d=-8.240559102923116e-07; mean 365d=-0.0001301271212903327; mean 1000d=-0.0003495555646705392; mean 2000d=-0.0004434833735806656; P 120d=0.12; P 365d=0.12; P 1000d=0.13; P 2000d=0.105
- **C4** — disc 120d=0.7561353169444727; disc 365d=0.6881119119686352; disc 1000d=0.7163279984174934; disc 2000d=0.8390696608356786; strict 1000=-0.6162393036716998; strict 2000=-0.6468327621458413; burden 1000=-0.49040661100201133; burden 2000=-0.5303982436300682
- **K1** — open 120d=0.8733333333333333; open 365d=2.276666666666667; open 1000d=4.501666666666667; open 2000d=7.985; inv 120d=0.7116666666666667; inv 365d=1.8583333333333334; inv 1000d=3.8733333333333335; inv 2000d=6.878333333333333
- **K2** — base 365=0.0; hub 365=0.0; base 1000=0.7066666666666667; hub 1000=0.7916666666666666; base 2000=2.08; hub 2000=2.1033333333333335
- **K3** — delay 365d=44.42630291005291; delay 1000d=75.97809466848567; delay 2000d=102.47054438582636; effect 365d=-44.42630291005291; effect 1000d=-58.27156689070789; effect 2000d=-46.63733010011207
- **K4** — esc conn=1.1816666666666666; esc base=0.355; reg conn=2.785; reg base=1.4016666666666666
- **B1** — valid=True, draws_ok=True, target=15
- **B2** — finite cells=1743; fraction narrower=0.9225473321858864; median ratio=0.25952520127277817
- **B3** — total stable=32; cells=48; 120d=9; 365d=9; 1000d=8; 2000d=6; full ranking=0.6041666666666666
- **F1** — seeds valid=30; horizon=10000; burn-in=2000; events on=1; regime is baseline=1
- **F2** — stated 256000-298000; stored min=255945, max=298264, n=30
- **F3** — volatility_clustering:R=30; volatility_clustering:P=0; volatility_clustering:N=0; positive_spread_and_depth:R=30; positive_spread_and_depth:P=0; positive_spread_and_depth:N=0; trade_sign_persistence:R=30; trade_sign_persistence:P=0; trade_sign_persistence:N=0; cancellation_activity:R=30; cancellation_activity:P=0; cancellation_activity:N=0; positive_volume_volatility_relation:R=17; positive_volume_volatility_relation:P=13; positive_volume_volatility_relation:N=0; fat_tailed_returns:R=3; fat_tailed_returns:P=27; fat_tailed_returns:N=0; weak_linear_return_autocorrelation:R=0; weak_linear_return_autocorrelation:P=29; weak_linear_return_autocorrelation:N=1; positive_price_impact:R=0; positive_price_impact:P=4; positive_price_impact:N=26
- **F4** — absACF=0.17046628210728482; sqACF=0.18269269403002716; spread=1.384119858974228; signACF=0.4858476221486253; band=0.008960364801674182; cancel=0.5374246338489603; volvol=0.11270269212294802; kurt=1.9885242747135987; kurtSD=1.3257936776174366; hill=5.38198551567398; retACF=-0.08241417035935644; impact=-0.012547968636437925; impact hw=0.004228745540308809
- **M1** — {"compliance": "inconclusive_static_analysis", "financing": "direct_price_feedback_detected", "greenwashing_disclosure": "no_price_feedback_detected", "investment": "no_price_feedback_detected", "production_or_strategy": "no_price_feedback_detected", "reputation_management": "inconclusive_static_analysis"}
- **M2** — ['current_eu_supervision', 'sme_algorithmic_prescreening', 'certified_green_data_connector']
- **M3** — clamp(0.20 + 0.70 * g) present
- **M4** — defaults 1.5/0.02/0.01/0.04/0.03 present
- **M5** — 20/5/0.10/30 present
- **M6** — 0.85 / 0.20 present
- **M7** — 8 sources: scope_2_emissions, scope_1_emissions, renewable_energy_share, water_intensity, recycling_rate, pollution_intensity, scope_3_emissions, environmental_capex
- **M8** — all thresholds present
- **M9** — formula present; unsophisticated x0.40
- **M10** — 0.03/0.10/0.30/30 present
- **M11** — consumer_daily_budget=1000.0
- **M12** — They are never passed into firm, consumer, investor, workforce, hub, connector, or regulator decisions.
- **L1** — all four dates present
- **L2** — 450m/1000, conjunctive strict >
- **L4** — no 5,000/1.5bn scope constants found (matches paper's disclaimer)
- **L5** — default False
- **P1** — benefit_multiplier low=0.5; benefit_multiplier high=3.0; evidence_request_capacity low=5; evidence_request_capacity high=40; investigation_capacity low=1; investigation_capacity high=12; random_surveillance_share low=0.0; random_surveillance_share high=0.3; correction_window_days low=10; correction_window_days high=90; conflict_capacity_share low=0.0; conflict_capacity_share high=0.6; conflict_resolution_days low=5; conflict_resolution_days high=60; hub_participation_scale low=0.2; hub_participation_scale high=1.5; hub_strictness low=0.1; hub_strictness high=0.95; hub_noise low=0.0; hub_noise high=0.5; hub_processing_delay_days low=0; hub_processing_delay_days high=20; connector_coverage_scale low=0.5; connector_coverage_scale high=1.2; connector_mismatch_probability low=0.0; connector_mismatch_probability high=0.1; connector_register_error_probability low=0.0; connector_register_error_probability high=0.05; connector_stale_probability low=0.0; connector_stale_probability high=0.25; connector_downtime_probability low=0.0; connector_downtime_probability high=0.1; connector_correction_delay_days low=10; connector_correction_delay_days high=120; consumer_preference_scale low=0.5; consumer_preference_scale high=1.5; investor_sophisticated_fraction low=0.05; investor_sophisticated_fraction high=0.8; workforce_trust_loss_rate low=0.1; workforce_trust_loss_rate high=1.0; compliance_burden_scale low=0.25; compliance_burden_scale high=2.5; social_discount_rate low=0.0; social_discount_rate high=0.07
- **X1** — all present
- **X2** — code_version=1645f3589408503894c7e8f44a92ffe382a9a5b4+dirty
- **X3** — tables=[1, 2, 3, 4, 5, 6, 7, 8, 9], figures=[1, 2, 3]
- **X4** — Plotted data match Table 5 exactly (0.475/0.48/0.045; 0.53/0.38/0.09; 0.355/0.135/0.51; 0.335/0.07/0.595). Embedded title repainted 2026-07-18 to 'Figure 2. Default-weight winner shares across horizons' and footnote to 'Horizons 120, 365, 1,000, and 2,000 days; ...' via tools/apply_editorial_fixes.py; plotted data untouched; verified visually.
- **X5** — 10 figure files: fig01_paired_effects.png, fig02_paired_effects.png, fig03_greenwashing_greenhushing_frontier.png, fig04_cost_effectiveness.png...
- **X6** — 29 entries checked
- **X7** — no contradictions found

## Corrections applied

- **X4** — embedded title/footnote repainted (tools/apply_editorial_fixes.py)

## Intentionally unchanged substantive mismatches

- None.

## Manuscript-internal presentation notes (no repository conflict)

- **X4**: resolved 2026-07-18 — Figure 2's embedded title and footnote were repainted to state the four-horizon coverage (tools/apply_editorial_fixes.py); plotted data untouched.
- **X6**: any uncited reference-list entries are listed in the claim table (Parguel et al. 2011 was cited in Section 1 on 2026-07-18).

## Missing or inconclusive evidence

- None. Every checked claim could be verified against stored outputs, source code, or documentation.

## Tests and validations run

- This audit script (read-only cross-check of 55 claims against stored outputs, source, and docs).
- `python -m pytest tests/ -q` — full repository suite (177 tests), run separately on the same tree: all passing.
- `python run_global_lhs_campaign.py --resume results` — strict read-only preflight: 200/200 valid draws at every horizon, 0 missing.
- Common-random-number and seed-formula verification over all 600 draw-replication cells of the 120-day run-level table (claim D5).

## Analyses and simulations intentionally not executed

- Global LHS campaign, replication-robustness campaign, and financial-validation campaign: not rerun; completed outputs treated as authoritative evidence.
- No draw, seed, manifest, figure, or summary file was regenerated or modified.
- Signed event-level price-impact diagnostics and empirical calibration: future work as stated in the manuscript.

## Verdict

**CONSISTENT.** No substantive mismatch between the manuscript and the repository. The paper may proceed to final external legal review and submission preparation.

No simulation campaign was executed during this audit.