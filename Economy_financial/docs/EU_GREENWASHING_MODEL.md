# EU greenwashing prevention model

Legal and model cut-off: **15 July 2026**. This document describes a
simulation, not legal advice or an empirical calibration.

## 1. Scope and legal map

No single EU act is treated as a complete “greenwashing code”. The opt-in
layer keeps the following bases separate:

| Track | Model use | Calendar default | Primary source |
|---|---|---:|---|
| UCPD | General misleading actions and omissions in B2C claims | Active throughout | [Directive 2005/29/EC](https://eur-lex.europa.eu/eli/dir/2005/29/oj/eng) |
| Empowering Consumers | Specific generic-claim, label, offset and future-performance rules | 27 Sep 2026 | [Directive (EU) 2024/825](https://eur-lex.europa.eu/eli/dir/2024/825/oj/eng) |
| Corporate sustainability reporting | Scope, structured reporting and limited assurance | National-transposition scenario default 19 Mar 2027 | [Directive (EU) 2026/470](https://eur-lex.europa.eu/eli/dir/2026/470/oj/eng) |
| Consumer enforcement | Coordinated widespread cross-border maximum-fine availability | Only when the case flag is set | [Directive (EU) 2019/2161](https://eur-lex.europa.eu/eli/dir/2019/2161/oj/eng) |
| EU Taxonomy | Eligibility/alignment evidence and consistency, not a firm-wide moral score | When a Taxonomy claim is made | [Regulation (EU) 2020/852](https://eur-lex.europa.eu/eli/reg/2020/852/oj/eng) |
| Issuer/market communications | Separate financial-market claim track | Scope-dependent model screen | [MAR](https://eur-lex.europa.eu/eli/reg/2014/596/oj/eng), [Prospectus Regulation](https://eur-lex.europa.eu/eli/reg/2017/1129/oj/eng), [Transparency Directive](https://eur-lex.europa.eu/eli/dir/2004/109/oj/eng) |
| CSDDD | Due-diligence obligations only; never a generic greenwashing fine | 26 Jul 2029 default application | Directive (EU) 2024/1760 as amended by Directive (EU) 2026/470 |
| European Green Bonds | Voluntary EuGB designation/use-of-proceeds track | Instrument-specific | [Regulation (EU) 2023/2631](https://eur-lex.europa.eu/eli/reg/2023/2631/oj/eng) |

The proposed Green Claims Directive is not baseline law. Its pre-verification
logic is represented only by
`LegalRegime.green_claims_preverification_enabled=False`, an explicit
disabled counterfactual.

Greenhushing is a behavioural and policy-risk metric, not a standalone EU
offence. The model follows that distinction and treats silence as non-illegal
unless another independent duty, such as mandatory reporting, is violated.
See the [Commission answer E-000800/2025](https://www.europarl.europa.eu/doceo/document/E-10-2025-000800-ASW_EN.html).

### Corrections to the former Part G interpretation

- CSRD scope uses `turnover > EUR 450m AND average employees > 1,000`.
  Equality does not qualify. The old single `firm_size` proxy survives only
  in the legacy tuple adapter.
- Limited assurance covers every mandatory report. It is not a 25% audit
  lottery. Public enforcement selection remains capacity-constrained and
  separate.
- The CSDDD 3% ceiling is callable only for a due-diligence case. An ordinary
  consumer, CSRD or investor-communication case uses its own configurable
  policy.
- The model's 4% consumer cap is used only when a case is explicitly marked as
  a coordinated widespread cross-border consumer infringement. It is a
  `LEGAL-ANCHOR`: Directive (EU) 2019/2161 requires the national maximum to be
  at least 4%, but does not establish 4% as a uniform EU ceiling.
- Small and voluntary reporters remain subject to consumer-claim and relevant
  market-communication surveillance.
- Named environmental metrics and claim/evidence scope replace the scalar
  wedge as the enforcement basis. Scalar scores remain compatibility and
  dashboard indicators.

## 2. Architecture and information boundaries

`environmental_claims.py` defines latent facts, structured claims, accessible
evidence, assessments and public signals. `corporate_communications.py` solves
the joint investment/communication/evidence/qualification/overstatement
choice. `greenwashing_supervision.py` performs assurance, screening, case
selection, investigations and remedies. `consumer_market.py` and
`workforce.py` implement the real-economy responses.

| Actor | Latent facts | Claims | Company evidence | Assurance/regulator evidence | Published decisions |
|---|---:|---:|---:|---:|---:|
| Firm | Own operations only | Yes | Yes | Submitted records | Yes |
| Assurance provider | No | Mandatory report | Relevant report evidence | Own procedure estimate | Opinion output |
| Supervisor | No | All screened claims | Requested/access-granted | Yes | Yes |
| Consumer | No | Public/attended claims | Linked public evidence, noisily | No private file | Yes |
| Investor | No | Reports/investor claims | Public linked evidence if sophisticated | No private file | Yes |
| Employee | No omniscient vector | Public claims | Noisy internal operational signal | No private supervisory file | Yes |
| Research evaluator | Ex-post snapshot only | Yes | Yes | Yes | Yes |

The private dictionary `_evaluation_truth_by_claim` is used only after the
decision path to calculate precision, recall and error rates. It is never
passed to consumer, investor, employee, assurance or supervision methods.

## 3. Environmental state, claims and evidence

Each firm carries Scope 1/2/3 emissions; energy and renewable share; water;
waste and recycling; pollution; biodiversity pressure; Taxonomy-eligible and
aligned turnover/CapEx/OpEx; real environmental CapEx; and offsets separated
from gross emissions. Period, group/operational boundaries, methodology and
uncertainty travel with the records.

Claims identify the firm, day/date, channel, audience, type, metric, asserted
value, unit, period, boundaries, evidence IDs, uncertainty, qualifications,
target date, offset reliance and withdrawal/correction state. Enforcement
compares named metrics; it does not sanction from `true_green_score`.

Evidence has source, subject, period, estimate, standard error, coverage,
independence, verification and confidence. Management evidence is neither
silently converted into independent evidence nor treated as certain. Limited
assurance re-performs procedures from accessible records and produces its own
uncertain estimate without receiving latent facts.

## 4. Divergence and legal assessment

For higher-is-greener metrics:

```text
divergence = asserted_value - evidence_estimate
z_over = max(0, divergence) /
         sqrt(evidence_error² + stated_uncertainty² + positive_floor)
```

The sign is reversed for emissions, water/pollution intensity, biodiversity
pressure and net-emission ratios. Materiality is the greener-than-evidence
gap divided by a unit-aware scale. Default experimental bands are:

- `z < 1`: noise;
- `1 <= z < 2.5`: inconclusive/more evidence;
- statistically visible but below 2% materiality: correctable error;
- material qualified divergence: negligence;
- stronger material divergence: overstatement;
- repeated severe findings: systemic abuse.

Applicable per-se consumer rules can override the statistical band after
27 September 2026. The assessment records outcome, legal track, authority,
estimate, divergence, z-score, materiality, confidence, reasons, correction,
benefit/revenue estimates and sanction.

## 5. Prevention, selection and procedure

Every claim receives low-cost screening. Evidence requests default to 20 per
reporting period and formal investigations to 5. Complaints and whistleblowers
receive high priority; channel, claim type, evidence gap and history contribute
to the risk score. A separate 10% random-surveillance draw deters pure score
gaming. These are `EXPERIMENT` capacities, not legal numbers.

Cases retain a state history:

```text
SCREENED -> EVIDENCE_REQUESTED -> UNDER_ASSESSMENT
         -> CORRECTION_WINDOW -> DECIDED -> PUBLISHED -> CLOSED
         -> FORMAL_INVESTIGATION -> DECIDED -> PUBLISHED -> CLOSED
```

Noise and inconclusive cases may close early. First-time correctable errors
receive a 30-day window, with modeled compliance halfway through. Severe,
repeated or prohibited claims enter the finite formal-investigation queue.
No pecuniary transfer occurs before the `DECIDED` transition.

Responses include closure, qualification, correction, withdrawal, published
decision, redress record and track-specific sanction. The ordinary
experimental formula is:

```text
calculated = 1.5 * estimated_benefit
             + 0.02 * affected_revenue * severity * confidence
applied = min(calculated, applicable_track_cap, corporate_headroom)
```

The ordinary simulated ceiling is 1% of turnover (`EXPERIMENT`). The model's
4% consumer legal anchor and the 3% CSDDD ceiling are selected only by their
consumer-cross-border and CSDDD conditions.

## 6. Corporate choice and greenhushing

At a reporting epoch the firm evaluates a transparent grid over real
investment, voluntary communication intensity `q`, qualification, evidence
effort and overstatement. Payoff includes communication/greenium benefit,
missed truthful premium, investment/evidence/qualification cost, compliance
burden and expected enforcement. Coefficients are stylized.

```text
q_truthful_benchmark = clip(0.20 + 0.70 * real_score, 0, 1)
greenhushing_gap = max(0, q_truthful_benchmark - q_chosen)
```

Mandatory report content is separate from voluntary marketing intensity.
High compliance ambiguity can make the optimizer reduce truthful voluntary
speech; no claim then exists to sanction, but consumers and investors cannot
award the full green premium.

## 7. Employees, consumers and investors

Employee trust falls with an evidence-accessible internal discrepancy and
more sharply after a confirmed decision. Quiet truthful days recover trust
more slowly. Productivity is applied once to product cost:

```text
productivity_multiplier = 1 - 0.03 * (1 - trust)
```

Annual turnover starts at 10%, is bounded at 30%, is converted to a daily
hazard, and drives departures, vacancies, hires, 30-day onboarding and
replacement cost. The rolling 365-day employee average feeds future CSRD
scope tests.

Consumers have heterogeneous attention, environmental preference,
sophistication and memory. Each segment allocates its share of the exogenous
EUR 1,000 daily budget by logit utility. Accessible claim/evidence divergence
reduces utility. Greenhushing reduces visibility and its truthful premium but
does not create a controversy signal.

Fundamentalists receive `InvestorEnvironmentalContext`, never facts:

```text
V_fair = V_fundamental
         * (1 + greenium_gamma * posterior_score * credibility)
         * (1 - controversy_discount)
```

Sophisticated agents inspect linked evidence and apply the full controversy
discount; unsophisticated agents update more slowly. Chartists retain the
indirect price-only channel.

Direction of the financial layer: claims, evidence and published supervisory
outcomes move investor valuation and hence prices, and prices affect
corporate financing proceeds through the treasury-sale rule
(`CorporatePolicy.sell_treasury`, which prices against the order-book
midpoint). The static audit in `results/audits/firm_price_feedback_audit.md`
finds no other direct or indirect own-share-price input to firm decisions:
greenwashing/disclosure, qualification and transition-investment rules never
read the firm's own price, order book or market valuation. The equity market
is therefore a market-response and financing context, not a price-discipline
mechanism, and no paper conclusion relies on stock prices disciplining
corporate environmental behaviour.

## 8. Event order and random streams

Day 1 maps to `start_date` (default 1 January 2026). On active market days:

1. map the legal date;
2. update fundamentals and real environmental transition;
3. process prior public information through workforce trust and turnover;
4. run product demand and book external revenue, cost and margin;
5. create scheduled reports/marketing/investor claims and evidence;
6. perform mandatory limited assurance;
7. screen claims, advance queues, decide and publish cases;
8. form information-safe state, bank and investor inputs;
9. run order book, trading, credit, interest, dividends and evolution;
10. log and validate ledgers.

Claims made at step 5 cannot influence that day's step-4 consumer demand.
They may affect same-day financial trading only after public supervisory output
exists. Communications, assurance, supervision, consumer and workforce draws
use separate `random.Random` streams derived from `supervision_seed`; legacy
module-level RNG trajectories are untouched while the feature is disabled.

## 9. Ledgers and invariants

- Consumer budget is an explicitly exogenous injection. Daily gross product
  revenue equals the configured budget.
- Gross product revenue equals external production cost plus corporate margin.
  Margin reaches the corporate balance through one path only.
- Replacement/evidence/production costs are external-service outflows.
- Subsidies and sanctions are State/corporate transfers. The sanction Decimal
  inflow equals the amount removed from corporate balances.
- Green-bond issuance and earmarked expenditure preserve the existing
  `issued = unspent proceeds + spent-green` identity.
- Productivity affects product production cost once; controversy affects
  valuation/demand, not the same fundamental a second time.

## 10. Configuration classification

| Parameter | Default | Class |
|---|---:|---|
| 2024/825 application | 27 Sep 2026 | `LEGAL` |
| CSRD national scenario date | 19 Mar 2027 | `LEGAL`/configurable transposition |
| CSRD thresholds | >450m and >1,000 | `LEGAL` |
| CSDDD application | 26 Jul 2029 | `LEGAL` |
| Green Claims pre-verification | off | `EXPERIMENT` |
| Random surveillance | 10% | `EXPERIMENT` |
| Evidence/investigation capacity | 20 / 5 per period | `EXPERIMENT` |
| Correction window | 30 days | `EXPERIMENT` |
| Guidance / small-firm evidence support | 0.35 / 0.25 | `EXPERIMENT` |
| Qualified-claim safe-harbour-like treatment | off | `EXPERIMENT` |
| Ordinary simulated ceiling | 1% | `EXPERIMENT` |
| Productivity-loss cap | 3% | `STYLIZATION` |
| Turnover base/cap | 10% / 30% annually | `STYLIZATION` |
| Consumer budget | 1,000/day | `STYLIZATION` |
| Onboarding | 30 days | `STYLIZATION` |

## 11. Running and outputs

Legacy callers do nothing new by default:

```python
Simulation(days=365)
```

Full opt-in system:

```python
Simulation(
    days=365,
    enable_esg=True,
    enable_regulation=True,
    enable_greenwashing_supervision=True,
    supervision_seed=104729,
    consumer_daily_budget=1000.0,
)
```

`python -m market_sim.main` explicitly enables the system and writes:

- `simulation_results.csv` — historical columns first, new aggregate and
  firm-level series appended;
- `environmental_claim_audit_log.csv` — claim/evidence/assessment ledger;
- `greenwashing_regulatory_cases.csv` — states, reasons, remedies and money;
- `market_simulation_dashboard.png` — market, claims, demand, workforce and
  regulator panels.

## 12. Three-regime State-intervention comparison (Part H)

The model compares three State intervention regimes under identical
economic, corporate, consumer, investor, workforce and environmental
conditions:

| Regime | Module | Legal status |
|---|---|---|
| A `current_eu_supervision` | `greenwashing_supervision.py` (unchanged) | Baseline: binding EU law as transposed in the model scenario (UCPD, 2024/825, CSRD as amended by Directive (EU) 2026/470, MAR-style screens, CSDDD track) |
| B `sme_algorithmic_prescreening` | `policy_regimes.SMEPrescreeningHub` | **Proposed national preventive policy experiment.** NOT required or established by Directive (EU) 2026/470 or any other baseline instrument |
| C `certified_green_data_connector` | `policy_regimes.CertifiedGreenDataConnector` | **Proposed public digital-infrastructure experiment.** NOT an obligation under Directive (EU) 2026/470; technologically enabled, nationally implementable |
| (extra) `hybrid_prescreening_and_connector` | both | EXPERIMENT arm answering the Section-9 hybrid question; excluded from the default comparison |

### 12.1 Legal grounding and distinctions

Verified against the Official Journal text of Directive (EU) 2026/470
(OJ L, 26.2.2026, ELI: `dir/2026/470/oj`):

- **Binding EU law** used by the baseline: the >EUR 450m **and** >1,000
  employee CSRD scope (recital 7, Art. 2(4)); limited-assurance-only
  regime (recitals 4–5); omission grounds (recital 14); Art. 29ca
  voluntary-use standards and the ≤1,000-employee value-chain cap with
  self-declarations and the statutory right to decline (recitals 12,
  21–22); CSDDD 3 % net-worldwide-turnover penalty ceiling and the
  26 July 2029 application / 26 July 2028 transposition dates.
- **National implementation choices**: the CSRD scenario date
  (`LegalRegime.csrd_new_scope_date`) and everything either proposed
  regime would require (establishing a hub or connector, procurement,
  data-protection basis, register access). Both regimes are therefore
  configurable experiments, never asserted obligations.
- **Supervisory guidance**: guidance/evidence-support intensities of the
  baseline supervisor (`SUPERVISORY`-flavoured `EXPERIMENT` settings).
- **Model assumptions**: every behavioural coefficient (participation
  propensities, screening noise, connector error rates, weights) is
  labelled `EXPERIMENT` or `STYLIZATION` in `constants.py`.
- The hub's eligibility line (≤1,000 average employees, outside
  mandatory CSRD scope) reuses the protected-undertaking threshold as a
  LEGAL-ANCHOR for *who the voluntary service targets*. It is never an
  exemption from consumer law, investigations or substantiation duties.

### 12.2 Regime B: SME pre-screening hub

Draft workflow: `DRAFT → SUBMITTED_TO_PRESCREENING → AUTOMATED_FEEDBACK
→ FIRM_REVISION_OR_REJECTION → PUBLISHED_OR_WITHHELD`. The hub reads
only the draft claim, firm-submitted evidence, prior published claims
and prior public decisions — never the latent fact vector (tested).
Sixteen explainable checks cover vague language, unsupported adjectives,
missing quantities/units/periods/baselines/boundaries, whole-company
overreach, packaging-only product claims, missing Scope 3,
eligibility-as-alignment, offset separation, unsupported targets,
missing plans, unverified labels, cross-channel conflicts,
stale/conflicting/inaccessible evidence, concealed uncertainty, and a
claim greener than the firm's own evidence. Feedback carries issue code,
explanation, affected field, deficiency, recommended correction and
qualification, confidence, legal/voluntary-standard reference and a
materiality flag, plus `prescreening_status =
"non_binding_preventive_feedback"` and a visible no-endorsement
disclaimer. Participation modes: voluntary (default), subsidized,
auto-invitation, mandatory counterfactual (off). The safe-harbour-LIKE
experiment is off by default and never protects concealment, prohibited
practices, repeated abuse or claims contradicted by firm-known
evidence. An over-strict or noisy algorithm demonstrably increases
withdrawals and greenhushing (tested); the hub is not hard-coded as
superior.

### 12.3 Regime C: certified green data connector

Authorization per firm and source: `NOT_CONNECTED → CONSENT_REQUESTED →
AUTHORIZED → ACTIVE → SUSPENDED_OR_REVOKED`, with consent withdrawal,
data minimization (per-source authorization), audit-logged tamper-evident
provenance (SHA-256 over payload, methodology version, period,
uncertainty, completeness, correction status). Eight default sources map
to Scope 1/2, renewable share, water, waste/recycling, pollution,
partial Scope 3 (coverage 0.45) and environmental CapEx. Connector
evidence (`EvidenceSource.CERTIFIED_PUBLIC_CONNECTOR`) has high
independence (0.95) and certification, but strictly positive
uncertainty, meter error, facility mismatch, staleness, register errors
with delayed corrections, downtime and cyber incidents. It never
populates green scores, Taxonomy eligibility/alignment, net-zero,
offsets or future targets (tested). The reconciliation engine
classifies firm-vs-connector-vs-other-evidence differences into matched,
rounding noise, methodological, incomplete coverage, source conflict,
correction required, suspicious override, material overstatement and
repeated manipulation; material classes only raise screening priority
(`connector_reconciliation` trigger) inside the unchanged procedural
supervisor — no sanction ever follows automatically (tested). Selective
authorization of favourable sources is detectable (authorized share
below `CONNECTOR_SELECTIVE_THRESHOLD`).

### 12.4 Comparability, evaluation and scoring

`run_greenwashing_policy_comparison` executes paired replications with
common random numbers: identical global market seed and
`supervision_seed` per replication across arms (same firms, latent
trajectories, strategies, macro shocks, consumer/workforce populations);
the hub and connector consume dedicated policy streams
(`supervision_seed + 89 / + 97`). Arms are provably aligned until the
first reporting epoch (tested). Policy-induced divergence of shared
streams afterwards (e.g. fewer screened claims after a withdrawal) is a
direct policy effect, not accidental RNG drift.

The research-only `PolicyOutcomeEvaluator` reads the latent-truth
snapshot strictly ex post and computes the Section-8 battery:
greenwashing incidence/severity/exposure, the confusion matrix with
precision/recall/specificity and delays, prevention (revisions, withheld
overstatements, evidence quality, overrides, participation, adoption,
recurrence), greenhushing (gap, withheld truthful claims, foregone
premium proxies), costs (State setup/operating, regulator time, firm
compliance, SME burden, cost per prevented/detected claim, reporting
delay, cyber incidents) and economic effects (perceived misallocation,
green welfare share, investor signal distortion, trust, replacement
cost, subsidy/bank misallocation, real investment, emissions).

The composite `policy_efficiency` score is an EXPERIMENT: min-max
normalized criteria weighted by `PolicyScoreWeights` (default plus
cost-focused, accuracy-focused, SME-protective and anti-greenhushing
scenarios), reported next to the raw dashboard, a four-axis Pareto
frontier (severity ↓, public cost ↓, greenhushing ↓, accuracy ↑),
confidence intervals across replications, and an explicit warning when
the identity of the best regime changes across reasonable weights. The
runner's conclusions name the regime that minimizes greenwashing, the
most accurate, the least costly, the most SME-protective, the least
greenhushing-inducing, the best under each scenario, and whether the
hybrid arm (when run) is Pareto-superior.

### 12.5 Part H outputs, ledgers and parameters

New outputs (all existing CSV columns keep their original order; new
fields are appended): the regime-comparison CSV (one row per regime ×
replication), the pre-screening event ledger, the connector provenance
and reconciliation ledgers, `policy_regime` identifiers on the claim and
case ledgers, per-day policy cost/adoption/correction/withdrawal series
in `simulation_results.csv`, and the comparative dashboard. Policy costs
flow through `State.pay_policy_cost` as generic treasury outflows that
can never touch the earmarked green-bond sub-ledger (identity asserted;
`state.policy_cost_dec == hub + connector state costs`, tested).

Information-access additions to the Section-2 matrix: the hub sees
draft claims + submitted evidence + public history (no latent facts, no
supervisor file); the connector's transfer function is a simulated
measurement apparatus over the physical ledger (like the firm's own
meters) and only its uncertain `EvidenceRecord` output ever reaches any
decision-maker; the evaluator alone reads truth, ex post.

| Part H parameter | Default | Class |
|---|---:|---|
| Hub eligibility line | ≤1,000 employees, non-CSRD | LEGAL-ANCHOR (Art. 29ca population) |
| Participation mode / propensities | voluntary; 0.90/0.60/0.35 | EXPERIMENT |
| Hub strictness / noise | 0.50 / 0.08 | EXPERIMENT |
| Hub costs (setup/submission/revision) | 25,000 / 40 / 60+25 | EXPERIMENT |
| Safe-harbour-like treatment | off | EXPERIMENT |
| Connector costs (setup/daily/cyber/integration) | 60,000 / 30 / 10 / 150 | EXPERIMENT |
| Meter error / mismatch / stale / register error | 1% / 2% / 5% / 1% | EXPERIMENT |
| Downtime / cyber incident | 1% / 0.2% | EXPERIMENT |
| Reconciliation bands (z) | 1.0 / 2.5 / 4.0 | EXPERIMENT |
| Composite score weights | see `PolicyScoreWeights` | EXPERIMENT |
| Evaluator unit costs | 120 / 400 per case/investigation | EXPERIMENT |

### 12.6 Part H limitations

Both proposed regimes depend on national transposition and
administrative capacity that the model does not represent (procurement,
GDPR/NIS2 compliance engineering, register interoperability, appeal
rights against hub feedback, liability for erroneous source data).
Participation, screening-noise and connector-error rates are not
empirically calibrated; conclusions must be read as sensitivity ranges
under the stated weights, never as forecasts. The consumer-premium and
misallocation proxies are reduced-form. The hybrid arm shares both
instruments' parameters without modelling integration savings or
additional complexity costs.

## 13. Part I — red-team remediation and paper-ready methodology

An independent adversarial review (red team) identified defects that the
current build repairs. Every repair is regression-guarded in
`tests/test_remediation.py`; the legacy trajectory with
`enable_greenwashing_supervision=False` is bit-for-bit unchanged.

### 13.1 Sanction-scale bridge (P0)

The statutory `annual_net_turnover` (hundreds of millions EUR) exists in
**legal-scope units** and is used exclusively for scope tests (CSRD
thresholds, protected-undertaking lines). Monetary sanction bases are
computed on a **simulation-scale turnover proxy**:

```text
sim_turnover = SIM_TURNOVER_BALANCE_MULTIPLE (1.5, STYLIZATION) × balance
affected_revenue = channel_share × sim_turnover
calculated = 1.5 × estimated_benefit
             + 0.02 × affected_revenue × severity × confidence
calculated ×= min(cap, 1 + 0.5 × prior_severe_findings)   (EXPERIMENT)
applied = min(calculated, track_ceiling_rate × sim_turnover, headroom)
```

The track cap **rates** are unchanged and remain track-gated: 1%
(EXPERIMENT ordinary), a 4% LEGAL-ANCHOR only for coordinated cross-border
consumer cases, and the 3% legal ceiling only for CSDDD due-diligence cases.
Pre-fix, 10/14 sanctions
seized the firm's entire distributable balance; post-fix zero cases are
headroom-bound in the reference year while sanctions stay strictly
positive and monotone in severity, confidence, benefit, affected revenue
and recidivism (tested).

### 13.2 Replication inference (P0)

`run_greenwashing_policy_comparison` now draws an independent stochastic
environment per replication with a transparent schedule
(`market_seed = common_seed + 1000·r`,
`supervision_seed = base + 7919·r`), while all policy arms inside one
replication share both seeds exactly (common random numbers). Reports
carry seed provenance per row, paired mean differences, standard
deviations, 95% CIs, probabilities of improvement, and explicit warnings
for single-replication runs or degenerate variance. Order invariance
(A→B→C ≡ C→B→A ≡ solo) is tested.

### 13.3 Immutable claim-and-correction ledger (P1)

A supervisory correction now flows through
`EnvironmentalClaim.record_correction`, which preserves
`original_asserted_value`, stamps `corrected_day`/`withdrawn_day`, and
appends an immutable `ClaimCorrectionEvent` (original value, corrected
value, exposure days, legal track, case id) to the supervisor ledger
(exported via `export_correction_events`). Corrections act prospectively:
agents see the corrected value only from the correction day; incidence
metrics are measured on original values, so corrections can never launder
history. Duration-weighted measures: misleading-claim days,
exposure-weighted severity, time-to-correction.

### 13.4 Detector hardening (P1)

All thresholds are `EXPERIMENT` (constants.py Part I):

- **Uncertainty plausibility**: self-declared uncertainty is credible up
  to 2× the evidence standard error; the excess is disregarded, flagged
  (`implausible_uncertainty`) and reasoned. The inflated-sigma attack now
  classifies as overstatement instead of noise.
- **Boundary**: a restricted operational boundary never widens the error
  band (the old comparability bonus is removed); undisclosed restriction
  escalates to a correction demand; a meaningful qualification makes a
  partial-scope claim valid.
- **Repeat-pattern memory**: ≥4 one-sided sub-threshold findings within
  365 days with mean z ≥ 0.5 escalate to negligence; isolated noise never
  escalates.
- **Evidence conflict**: an independent record and the firm's own record
  disagreeing by > 2 combined sigma route to INCONCLUSIVE with an audit
  trail; no sanction can rest on a single unresolved conflicting record
  (the wrong-public-record false positive is eliminated).
- **Cross-period checks**: cherry-picked short periods against the firm's
  own adjacent evidence and implausible comparative baselines floor at
  correction demands. **Residual blind spots (stated, not claimed
  detectable)**: production-driven absolute reductions,
  intensity-vs-absolute framing without production evidence, coordinated
  multi-firm narratives, audience-perception effects of true claims.
- Qualification checks everywhere use the semantic
  `meaningful_qualification` heuristic (length + scoping tokens);
  placeholder qualifications no longer satisfy any rule.

### 13.5 Hub substance (P1/P2)

The processing delay is operational: submitted drafts are withheld from
every public surface until `review_day` and only then join the claim log
and the next supervisory batch. Prevention accounting is honest:
revisions count as *meaningful* only when they answered a legally
material issue; spurious/informational flags are tracked separately
(`noise_flag_events`) and never enter prevention metrics or
cost-per-prevented. The composition audit records
eligible/participating/submissions/revisions/withdrawals per corporate
strategy (research-only labels), and the evaluator reports ITT- and
TOT-style rates (`hub_participation_rate`,
`hub_tot_revision_rate_{honest,adaptive,greenwasher}`). New checks:
`MEANINGLESS_QUALIFICATION`, `OVERSTATED_UNCERTAINTY`,
`CLAIM_EXCEEDS_OWN_EVIDENCE`.

### 13.6 Connector operations (P1/P2)

Integrity hashes are now **verified** (`verify_provenance`): tampered
records are marked, excluded from reconciliation and testable. The
register-error lifecycle is implemented: errors register a correction due
date; `process_corrections` issues superseding records
(`corrects_transfer_id` provenance) that propagate prospectively without
rewriting historical decisions; meanwhile unresolved conflicts route to
INCONCLUSIVE in the rule engine, so no firm is sanctioned on an erroneous
register record. Staleness is meaningful: stale reads return the
register's genuinely old measurement when history exists (documented
drift-noise approximation otherwise). The low-coverage safe channel is
closed: coverage widens effective uncertainty (`z / (σ/coverage)`), and
large discrepancies under low coverage produce a targeted-investigation
`correction_required` state instead of a clean pass. `unit_mismatch` is a
real computed comparison against source units (no conversion evidence is
modeled — documented limit). Reconciliation still never sanctions by
itself.

### 13.7 Metric families (P1/P2)

Named families with honest definitions: screening-conditioned
precision/recall (explicit aliases) vs **population-level** detection
recall/coverage and severity-weighted recall; original vs live-uncorrected
vs corrected incidence; exposure-weighted severity and misleading-claim
days; queue mean/p90 age, backlog, completion times; intent separation
via a research-only intent snapshot (measurement-noise vs strategic
material overstatements) — the 2% threshold alone no longer defines
intent. Composite-score repairs: the two greenwashing criteria measure
distinct dimensions (incidence vs duration-weighted exposure), accuracy
uses population recall, public cost uses the discounted comparison value.
The greenhushing index remains a mixed-unit EXPERIMENT aggregation,
stated as such. Pareto analysis and ranking-instability warnings are
unchanged.

### 13.8 Horizon, discounting and sensitivity (P2)

An EXPERIMENT social discount rate (default 3%/yr) discounts policy
costs and exposure-weighted harm for comparisons; undiscounted
accounting ledgers are always preserved. `run_horizon_grid` reports
default-weight winners across 120/365/1000/2000 days with an explicit
stability verdict; `run_sensitivity_analysis` provides a reproducible
reduced-form Latin-hypercube design (stdlib) over sanction scale,
enforcement capacity, hub strictness/noise, connector failure rates,
regulatory strictness, consumer preference scale, discount rate and
horizon (one replication per sample — a documented computational
compromise). A regime must never be presented as universally superior
when the winner changes across defensible weights, horizons or sampled
parameters; the runners say so explicitly.

### 13.9 Identification and contribution framing

Within one replication, arms share identical initial firms, latent
trajectories, strategies, macro shocks and populations; only the State
intervention mechanism (and its dedicated policy RNG streams) differs, so
paired differences identify the policy effect plus endogenous behavioral
responses under common shocks. Across replications the full stochastic
environment varies. Selection into the voluntary hub and connector is
endogenous by design; ITT and TOT are therefore reported separately and
participation composition is exported. Results are **policy-experiment
orderings under stylized parameters, not forecasts**: no behavioral
parameter is empirically calibrated. The model's credible contribution is
institutional and methodological — an information-safe paired
computational comparison of preventive algorithmic pre-screening,
certified public environmental-data infrastructure, and
capacity-constrained ex-post enforcement under a calendar-aware EU
sustainability-reporting and consumer-protection architecture.
Greenhushing itself is not a novel concept (see the signalling-game
literature); what is new here is the integrated institutional comparison
and the procedural, information-safe architecture.

## 14. Limitations and calibration needs (superseded status: see §15.5)

The model is not calibrated to enforcement frequencies, causal demand
elasticities, employee-turnover studies or sector emissions distributions.
National transposition, competent-authority powers, appeals, group scope,
jurisdiction, damages and criminal/competition referrals require deeper
country-specific modules. Taxonomy DNSH/minimum-safeguard evidence, detailed
ESRS datapoints, product lifecycle assessment and EuGB external-review
workflows are reduced-form. Assurance is procedure-level and not a substitute
for audit standards. Results should be reported as policy experiments and
sensitivity ranges, never forecasts or legal conclusions.


## 15. Part J — paper-readiness completion

Part J executes the remaining paper-readiness work: a full global
sensitivity campaign, a structured parameter registry, an explicit
capacity-consuming conflict-resolution procedure, and the
publication/reporting layer. Everything is regression-guarded
(`tests/test_conflict_resolution.py`, `tests/test_sensitivity_campaign.py`,
`tests/test_part_j_stress.py`); the legacy trajectory with
`enable_greenwashing_supervision=False` remains bit-for-bit unchanged.

### 15.1 Evidence-conflict resolution (Workstream C)

The Part I rule "conflicts route to INCONCLUSIVE" is now a procedure,
not an endpoint. A conflicting file opens a case in the new
`CONFLICT_RESOLUTION` state, enters the SHARED finite investigation
queue under a transparent priority (`conflict_priority=0.85`,
EXPERIMENT: below whistleblower 1.0, complaint 0.95 and connector
reconciliation 0.90), and consumes one slot of `investigation_capacity`
when opened. An EXPERIMENT reserve (`conflict_capacity_share=0.20` of
capacity, never more than the number of waiting disputes) prevents an
endless stream of higher-priority enforcement cases from starving
disputes forever; setting it to zero restores pure priority competition
(tested both ways).

An opened conflict investigation commissions a re-measurement from the
SOURCE: under Regime C the connector's register-correction lifecycle
answers it (superseding record after the correction delay, prospective
only); otherwise a stylized third party re-measures after
`SOURCE_REVERIFICATION_DELAY_DAYS`. The re-verifier is a measurement
apparatus over the physical ledger — exactly like the firm's meters and
the connector transfer function — and only its uncertain
`EvidenceRecord` output ever reaches the supervisor. Resolution is a
transparent decision table:

* fresh independent record agrees with the firm → **confirmation +
  external register corrected** (public rehabilitation signal, zero
  controversy);
* fresh independent record corroborates the register → **escalation**,
  implemented as a re-assessment on the corroborated independent file
  that then follows the ORDINARY procedural path (formal investigation,
  decision, publication) — the conflict itself never sanctions;
* three-way disagreement → **dismissal**;
* timeout with no re-measurement → credibility fallback that can only
  confirm, demand a correction (correction-window machinery) or
  dismiss — **escalation without corroborated evidence is impossible by
  construction**, so no sanction can ever rest on an unresolved source
  conflict.

Repeated conflicts corroborate: a later period's independent reading
that agrees with the earlier disputed register record escalates the
earlier case. Delay, queue cost (evaluator unit cost 250/conflict,
EXPERIMENT), outcome mix and pending disputes are tracked (the
`conflict_*` metric family); register corrections propagate
prospectively through the connector and future assessments; closed
decisions are never rewritten.

### 15.2 Global sensitivity campaign (Workstream A)

`market_sim/sensitivity_campaign.py` replaces the Part I.8 reduced-form
interface with a real campaign: Latin-hypercube sampling over the
28 GSA-eligible dimensions of the parameter registry (sanction bridge
and proportionality, screening/investigation capacity, random
surveillance, enforcement strictness, conflict-desk parameters, hub
participation/strictness/noise/delay, connector coverage/error/
staleness/downtime/correction delay, consumer preference and
discrepancy sensitivity, investor sophistication and controversy
sensitivity, workforce trust loss/recovery, compliance burden, social
discount rate), >=3 paired replications per draw with common random
numbers within replications and an independent stochastic environment
across replications and draws, atomic per-draw result files with
resume-without-corruption, and a machine-readable manifest (master
seed, full design, replication seed schedule, horizon, discount-rate
handling, git hash, regime identifiers). Composite weights are not
sampled continuously; rank frequency is reported across the five
discrete EXPERIMENT weight scenarios per draw.

Executed scale (shipped in `results/`, exact inspection commands in
`docs/REPRODUCIBILITY.md`): 200 draws x 3 replications x 3 regimes at
each of 120, 365, 1,000, and 2,000 days (1,800 regime runs per horizon;
7,200 in total). All four horizons use the same complete LHS design;
`subset` is null in the authoritative machine-readable configuration.
Summaries report paired-effect distributions, probabilities
of improvement, confidence intervals, rank/winner/Pareto frequencies,
the weight-sensitivity fraction, and parameter importance as
standardized regression coefficients plus partial rank correlations.
The campaign measures MODEL robustness and parameter dependence — never
causal identification or empirical prediction.

### 15.3 Headline robustness findings (results, not forecasts)

* **Conditional rankings.** The default-weight winner changes across
  horizons for 80.5% of the 200 shared draws. Changing normative weights
  changes the winner in 70.0%, 63.0%, 58.0%, and 45.5% of draws at 120,
  365, 1,000, and 2,000 days. Policy rankings are
  reported only conditional on horizon, discount rate, weights and
  participation.
* **Hub (Regime B):** reduces originally-material overstatements in
  87.5–91.0% and exposure-weighted severity in 85.0–90.5% of draws,
  with effect size driven chiefly by `hub_participation_scale` and
  `hub_strictness`; but it increases the greenhushing gap in ~95–100%
  of draws and always adds public cost. Its severity effect at high
  strictness/noise partly operates through withdrawals — a trade-off,
  not a free lunch.
* **Connector (Regime C):** near-null severity effect at 120 days
  (P(improve)=40.5%), heterogeneous at 365 days (60.5%), and a much more
  robust severity reducer at 1,000 and 2,000 days (97.0% and 100% of all
  200 draws) as fixed costs amortize
  and reconciliation/correction lifecycles compound. This
  horizon-dependence weakens any short-horizon claim in either
  direction and is exactly why conclusions must be stated
  horizon-conditionally. The full-space long-horizon campaign resolves
  the former 6/3-draw coverage limitation but does not provide empirical
  calibration.
* **Conflict desk:** conflict investigations occur mainly under
  Regime C (register errors create genuine disputes); resolution delay
  is capacity- and reserve-dependent; heavy source error loads the
  dispute channel, never the sanction channel (stress-tested at 50%
  register-error rates).

### 15.4 Interpretation rules (binding for any write-up)

1. No effect size from this model is an empirical prediction; all
   results are policy-experiment orderings under stylized parameters.
2. The greenwashing-to-demand, greenwashing-to-trust and
   trust-to-turnover directions are STRUCTURAL ASSUMPTIONS
   (STYLIZATION-class parameters, see the registry), not validated
   behavioural estimates.
3. Hub effects are described as prevention of good-faith errors plus
   withdrawal-induced claim suppression; any stronger anti-fraud claim
   requires separate demonstration (the hub cannot block publication).
4. Connector effects may be cited only horizon-conditionally and with
   coverage/source-error diagnostics. Full-space long-horizon robustness
   does not make the result an empirical forecast.
5. Rankings are reported conditional on scenario, horizon, discount
   rate and weights, with the weight-sensitivity fraction alongside.
6. The limitations in §15.5 belong in the MAIN summary of any paper,
   not in an appendix.

### 15.5 Limitation status after Part J

| Limitation | Status |
|---|---|
| Sensitivity analysis was a smoke interface (1 replication/sample) | RESOLVED — full LHS campaign, >=3 paired replications, resume, manifest |
| Conflicts closed same-day without consuming capacity | RESOLVED — CONFLICT_RESOLUTION procedure, shared capacity, reserve, corroboration-gated escalation |
| Parameter values without stated evidence basis | RESOLVED (transparency), NOT RESOLVED (calibration) — registry separates legally-mandated / reference-class / illustrative values; no behavioural parameter is empirically estimated |
| Long-horizon confirmation of the full design space | RESOLVED for the stated LHS design — 200 draws at both 1,000 and 2,000 days; empirical calibration remains unresolved |
| Empirical calibration of demand/trust/turnover channels | NOT RESOLVED — out of scope for simulation work; flagged for survey/quasi-experimental follow-up |
| National transposition, appeals, procurement, GDPR/NIS2 engineering | NOT RESOLVED — reduced-form as before (§12.6) |
| Composite score remains an EXPERIMENT aggregation | UNCHANGED BY DESIGN — reported only next to raw metrics, Pareto sets and rank-stability warnings |
