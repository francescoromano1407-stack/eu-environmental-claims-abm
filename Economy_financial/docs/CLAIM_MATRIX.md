# Claim matrix — revised manuscript (17 July 2026)

Every major claim in the revised manuscript
(`Francesco_Romano_EU_Environmental_Claims_ABM_Paper_revised.docx`), classified
against the completed simulation evidence. Categories:

- **SUPPORTED** — directly backed by completed, validated simulation outputs
  or repository tests.
- **PARTIAL** — conditionally or partially supported; the manuscript states the
  qualification wherever the claim appears.
- **REMOVED/REFRAMED** — previously stated or implied, unsupported by the
  completed evidence, and now removed or rewritten.
- **ADDED** — new claim introduced by the July 2026 revision, with its evidence.

Evidence roots: `results/` (LHS campaign), `results/replication_robustness/`,
`results/financial_validation/pilot_30seeds/`, `results/audits/`, `tests/`.

## 1. Policy-comparison claims (core question)

| # | Claim | Category | Evidence and qualification |
|---|---|---|---|
| 1.1 | The hub reduces original material overstatements in 87.5–91.0% of draws and exposure-weighted severity in 85.0–90.5% across all four horizons | SUPPORTED | `results/summaries/*_draw_effects.csv`, 200 draws × 3 paired replications per horizon |
| 1.2 | The hub worsens greenhushing at every horizon (improves it in only 0–6.5% of draws) and increases discounted public cost in every draw | SUPPORTED | same summaries; sign convention documented in §4.3 |
| 1.3 | The connector is null-to-heterogeneous at 120 days, mixed-positive at 365, and robustly favorable on severity at 1,000/2,000 days (97%, 100% of draws) | SUPPORTED | same summaries; horizon dependence mechanism stated as within-model |
| 1.4 | The connector increases discounted public cost in every draw at every horizon | SUPPORTED | same summaries |
| 1.5 | Default-weight winners reverse across horizons in 80.5% of matched draws; within-horizon winners are weight-sensitive in 45.5–70% of draws | SUPPORTED | `summaries/unified_campaign_summary.json`, ranking tables |
| 1.6 | Current supervision is Pareto non-dominated in all 200 draws at every horizon; hub and connector Pareto frequencies as tabulated | SUPPORTED | Pareto tables in summaries |
| 1.7 | Participation and strictness drive the hub's severity–greenhushing trade-off (PRCC signs) | PARTIAL | associational sensitivity diagnostics only; manuscript labels them structural-within-model, not behavioral elasticities |
| 1.8 | Conflict-desk workload and resolution delays are higher under the connector | SUPPORTED | run-level conflict metrics, all horizons |
| 1.9 | Policy rankings depend on horizon, weights, capacity, participation, evidence quality | SUPPORTED | ranking stability + weight-scenario tables |
| 1.10 | Any real-world effectiveness, cost, or welfare forecast for EU policy | REMOVED/REFRAMED (long-standing) | prohibited; every effect statement confined to the model |

## 2. Financial-market claims

| # | Claim | Category | Evidence and qualification |
|---|---|---|---|
| 2.1 | Equity prices discipline corporate greenwashing, disclosure, or transition investment | REMOVED/REFRAMED | No such channel exists in the model: static audit finds no own-share-price input to those decision rules (`results/audits/firm_price_feedback_audit.md`). The manuscript now states this explicitly in §3.7, §5.5, §6, and Limitation 11; the market layer is described as market response and financing context throughout |
| 2.2 | Environmental claims and supervisory outcomes move investor valuation and prices (claims → market direction) | SUPPORTED (within model) | investor fair-value rule (§3.7), information-safe context tested in `tests/`; a stylization, not an estimated response |
| 2.3 | Market prices affect corporate financing proceeds via treasury sales | SUPPORTED (within model) | `CorporatePolicy.sell_treasury` prices at order-book midpoint; the audit's only direct own-share read |
| 2.4 | Positive price impact is reproduced by the market engine | REMOVED/REFRAMED | Not reproduced in 26/30 seeds, never reproduced; mean log-volume × immediate absolute mid-move correlation −0.013 (95% half-width 0.004). Manuscript reports "not reproduced" in Table 8, §5.7, abstract, Limitation 11 |
| 2.5 | Volatility clustering, positive spread/depth, trade-sign persistence, cancellation activity are reproduced | SUPPORTED | 30/30 seeds each, pre-declared rules, seed as unit of inference (`pilot_30seeds/diagnostics/`) |
| 2.6 | Fat tails are reproduced | PARTIAL | 3 reproduced / 27 partial; mean excess kurtosis 1.99, mean Hill α 5.38 (thinner than the 2–5 empirical band in most seeds). The earlier single-path "reproduced" claim (kurtosis 21.66) is superseded as unrepresentative |
| 2.7 | Weak linear return autocorrelation is reproduced | PARTIAL | 29 partial / 1 not; mean lag-1 return ACF −0.082, small but outside the white-noise band. The single-path "not reproduced" (ACF 0.445) is superseded |
| 2.8 | Volume–volatility relation is reproduced | PARTIAL | 17 reproduced / 13 partial; mean correlation 0.113 |
| 2.9 | The financial market is empirically validated | REMOVED/REFRAMED (long-standing) | prohibited; validation is partial and stated as such |

## 3. Robustness and inference claims

| # | Claim | Category | Evidence and qualification |
|---|---|---|---|
| 3.1 | The replication-robustness extension is unexecuted and supplies no results | REMOVED/REFRAMED (stale) | Executed 16 July 2026: 12 draws × 4 horizons at 15 paired replications, all 48 files valid (`results/replication_robustness/`) |
| 3.2 | Fifteen replications narrow paired 95% intervals in 92.3% of the 1,743 finite draw-metric-policy cells (median half-width ratio 0.26) | ADDED | `replication_robustness_summary.json` |
| 3.3 | The three-replication default-weight winner is confirmed at 15 replications in 32/48 draw-horizon cells (9, 9, 8, 6 of 12 by ascending horizon); full ranking in 60.4% | ADDED | same; the manuscript draws the honest consequence that draw-level winner labels are noisy and distribution-level statements are emphasized |
| 3.4 | Three replications suffice for draw-level winner labels | REMOVED/REFRAMED | contradicted by 3.3; §4.4 and Limitation 9 rewritten |
| 3.5 | Common random numbers hold across regimes within replications; seeds vary across replications/draws | SUPPORTED | seed formulas in manifests; regression tests |

## 4. Model-architecture claims

| # | Claim | Category | Evidence and qualification |
|---|---|---|---|
| 4.1 | No decision-maker observes latent environmental truth; truth is evaluator-only | SUPPORTED | information-boundary tests in `tests/`; campaign configuration research-only notice |
| 4.2 | Corrections are prospective and immutable; sanctions are track-gated; conflicts escalate only with corroboration | SUPPORTED | repository tests |
| 4.3 | Greenhushing is endogenous to expected benefit, burden, ambiguity, evidence costs, enforcement | SUPPORTED (within model) | corporate-choice grid (§3.4); coefficients stylized, not estimated |
| 4.4 | CSDDD is a doctrinally complete implementation | REMOVED/REFRAMED (long-standing) | date/remedy gate only; firm-scope test not implemented (§2.1, Limitation 10) |
| 4.5 | 4% is a uniform EU fine ceiling | REMOVED/REFRAMED (long-standing) | Directive (EU) 2019/2161 sets a minimum-maximum; model's 4% cap is a LEGAL-ANCHOR scenario |
| 4.6 | Behavioral/cost/error/participation parameters are calibrated estimates | REMOVED/REFRAMED (long-standing) | prohibited; parameter registry separates roles and evidence classes |

## 5. Newly added claims (all introduced by this revision)

| # | Claim | Evidence |
|---|---|---|
| 5.1 | Firm greenwashing, disclosure, qualification, and transition-investment rules contain no direct or indirect own-share-price input; the only direct own-share market read is the treasury financing rule | static audit `results/audits/firm_price_feedback_audit.{json,md}` (classification per decision category; limitations of static analysis disclosed in §3.7 and Limitation 11) |
| 5.2 | No policy ranking depends on price-mediated corporate incentives | follows from 5.1 plus the fact that all reported policy outcomes are claim-quality, greenhushing, procedural, and cost metrics |
| 5.3 | The multi-seed campaign supersedes the single-path diagnostic, which was unrepresentative | comparison of single-path vs 30-seed statistics (§5.7) |
| 5.4 | A signed event-level price-impact diagnostic and any market-discipline channel are future work requiring new code and, for the channel, a new versioned model | stated as future work in §5.7 and Conclusion; not implemented |

## 6. Verification notes

- Static-audit limitations (no runtime trace, conservative keyword matching)
  are quoted in the manuscript where the audit is cited.
- All numbers in this matrix are copied from stored result files; nothing was
  simulated for the revision.
- The pre-revision manuscript is preserved as
  `Francesco_Romano_EU_Environmental_Claims_ABM_Paper_revised.pre_market_reframe_backup.docx`.
