# Data dictionary — sensitivity campaign and replication package

All results are **simulation outputs under stylized parameters**, never
forecasts or empirical estimates. Fields marked **[research-only]** are
computed by the ex-post evaluator from the latent-truth snapshot
(`Simulation._evaluation_truth_by_claim` /
`_evaluation_intent_by_claim`) strictly after each run has finished; no
agent, policy system, hub, connector, assurance provider or supervisor
ever reads those values during a run. All other fields are
observable-policy quantities that an in-model actor could in principle
compute.

## Directory layout (`results/`)

| Path | Content |
|---|---|
| `campaign_120d/` | 120-day global screening campaign (200 LHS draws × 3 paired replications × 3 regimes) |
| `campaign_365d/` | 365-day confirmation campaign on the 60-draw policy-relevant subset (`subset_selection_365d.json`) |
| `campaign_1000d/`, `campaign_2000d/` | long-horizon robustness campaigns on representative draws (`subset_selection_long.json`) |
| `default_comparison.json` | 5-replication paired comparison at registry-default parameters, 365 days |
| `figures/` | publication figures (`fig01`–`fig10`) and CSV tables |
| `subset_selection_*.json` | subset-selection rules and chosen draw indices |

## Campaign directory files

### `manifest.json`
| Field | Meaning |
|---|---|
| `config.master_seed` | master seed of the whole campaign |
| `config.seed_schedule` | exact formulas: `market_seed = master_seed + 1000000*draw + 1000*rep`; `supervision_seed = 104729 + 104729*draw + 7919*rep` |
| `config.regimes` | regime identifiers compared (first entry = baseline for paired contrasts) |
| `config.draws`, `config.replications`, `config.horizon_days` | design size |
| `space` | sampled bounds per parameter (from `market_sim/parameter_registry.py`) |
| `design` | the full LHS design matrix (draw index → parameter values) |
| `code_version` | `git rev-parse HEAD` (+`+dirty` when the working tree differs) |

### `draw_XXXX.json`
| Field | Meaning |
|---|---|
| `complete` | `true` only when every replication × regime finished and passed numerical-integrity checks; resume logic recomputes anything else |
| `sample` | the parameter draw (raw LHS values; integers rounded at application time) |
| `discount_rate` | per-draw sampled social discount rate used by the evaluator |
| `rows[]` | one entry per regime × replication: `regime`, `replication`, `market_seed`, `supervision_seed`, `metrics{}` |

### `metrics{}` (evaluator battery)
Groups (full definitions in `market_sim/policy_comparison.py`):

- **Greenwashing incidence [research-only]** — `original_material_overstatements` (count, on ORIGINAL published values), `live_uncorrected_material_overstatements`, `corrected_material_claims`, `severity_weighted_greenwashing`, `exposure_weighted_severity` (severity × exposure days), `discounted_exposure_weighted_severity`, `misleading_claim_days`, `time_to_correction_mean` (days), `noise_only_overstatements` vs `strategic_material_overstatements` (intent split).
- **Detection [research-only]** — screening-conditioned `precision`/`recall`/`specificity` (capacity-selected cases only) vs `population_detection_recall`, `detection_coverage`, `severity_weighted_detection_recall` (all originally-material claims); `false_positive_rate_assessed`; `unresolved_uncertainty` (inconclusive count).
- **Queue / procedure (observable)** — `backlog_pending_cases`, `queue_mean_age_days`, `queue_tail_age_days_p90`, `case_completion_days_mean`, `detection_delay_days`, `correction_delay_days`.
- **Conflict investigations (observable; Part J)** — `conflict_cases_opened`, `conflict_investigations` (capacity actually consumed), `conflict_pending_unresolved`, `conflict_resolution_delay_mean` (days), and outcome counts `conflict_confirmed_firm_claim`, `conflict_register_corrected`, `conflict_claim_corrected`, `conflict_dismissed_unresolved`, `conflict_escalated_corroborated`.
- **Prevention / hub (observable)** — `prepublication_revisions`, `prepublication_meaningful_revisions`, `prepublication_noise_flag_share`, `hub_participation_rate` (ITT-style, eligible firm-periods), `hub_tot_meaningful_revision_rate` and per-strategy TOT rates (strategy labels **[research-only]**), `prepublication_withheld_overstatements` **[research-only]**, `recurrence_after_feedback`.
- **Greenhushing (observable)** — `mean_greenhushing_gap` (share 0–1), `withheld_truthful_claims` **[research-only]**, `voluntary_reporting_declines`, `foregone_consumer_premium` (EUR proxy, EXPERIMENT).
- **Costs (EUR, simulation scale)** — `state_policy_cost`, `regulator_time_cost` (includes conflict-desk time at 250/case), `firm_policy_cost`, `firm_reporting_cost`, `sme_burden`, undiscounted; `discounted_total_public_cost` at the sampled social discount rate; `cost_per_prevented_material_claim`, `cost_per_detected_material_claim`.
- **Economy (observable)** — `consumer_perceived_misallocation`, `green_welfare_share` **[research-only: uses true score]**, `investor_signal_distortion` **[research-only]**, `employee_trust_mean`, `turnover_replacement_cost`, `real_environmental_investment`, `gross_emissions_final`.

### `summary.json`
| Field | Meaning |
|---|---|
| `effect_distributions[metric][regime]` | distribution across draws of per-draw mean PAIRED differences vs the baseline regime. Positive = policy regime improves the outcome (sign convention handled per metric). `n`, `mean`, `sd`, `ci95_halfwidth`, `prob_improvement`, `p05..p95` |
| `winner_frequency[scenario][regime]` | draws won under each composite-weight scenario |
| `rank_frequency[scenario][regime]` | position counts (index 0 = ranked first) |
| `pareto_frequency[regime]` | draws in which the regime is Pareto-efficient (severity ↓, public cost ↓, greenhushing ↓, accuracy ↑) |
| `weight_sensitive_fraction` | share of draws whose winner changes across the five weight scenarios |
| `parameter_importance[target][parameter]` | `src` (standardized regression coefficient, joint OLS) and `prcc` (partial rank correlation). Measures model parameter dependence, **not** causal identification |
| `per_draw[]` | per-draw winners, rankings, Pareto membership, mean paired contrasts and mean metric levels |

### `draw_effects.csv`
One row per draw: sampled parameters, winner per weight scenario,
`weight_sensitive`, Pareto members, `effect__<metric>__<regime>`
(paired mean difference vs baseline, positive = improvement) and
`level__<metric>__<regime>` (per-draw mean level).

## Claim/case ledgers (single-run outputs)
Unchanged from Part G/H/I: `simulation_results.csv`,
`environmental_claim_audit_log.csv`, `greenwashing_regulatory_cases.csv`
(cases now include `conflict_case`, `conflict_investigation_day`,
`conflict_resolution_due_day`, `conflict_resolved_day`,
`conflict_outcome`).
