# Publication-readiness review

**Review cut-off:** 15 July 2026 for legal claims.  
**Epistemic status:** transparent simulation-based policy experiment; not an
empirical forecast, causal estimate, legal opinion, or budget estimate.

## 0. Revision decision of 17 July 2026 — Strategy A (reframe, no model change)

The manuscript was revised without changing substantive model logic or any
completed simulation output. The decision rests on three pieces of completed
evidence:

1. The static firm price-feedback audit
   (`results/audits/firm_price_feedback_audit.md`) finds that corporate
   greenwashing, disclosure, qualification, and transition-investment rules
   never read the firm's own share price, order book, or market valuation.
   The only direct own-share market read is the treasury financing rule
   (`CorporatePolicy.sell_treasury`). The model therefore contains no
   market-discipline mechanism, and the policy ranking mechanically cannot
   depend on one.
2. The completed 30-seed financial validation campaign
   (`results/financial_validation/pilot_30seeds/diagnostics/`) classifies
   positive price impact as **not reproduced** (26/30 seeds not reproduced;
   mean log-volume x immediate absolute mid-move correlation -0.013), and
   fat tails, the volume-volatility relation, and weak linear return
   autocorrelation as only **partially reproduced**. A market-discipline
   extension built on this engine would be indefensible before the
   microstructure itself is repaired.
3. The paper's core question — which of three policy regimes best reduces
   greenwashing, accounting for greenhushing, compliance costs, enforcement
   capacity, and heterogeneous institutional conditions — is answered by the
   completed LHS campaign through enforcement, information, evidence,
   legal-procedural, compliance-cost, and greenhushing mechanisms. None of
   the reported policy outcomes runs through equity prices.

Accordingly the manuscript now: describes the equity market as endogenous
market response and financing context, never as demonstrated price
discipline; discloses the non-reproduced price-impact diagnostic and the
partial stylized-facts validation in the abstract, Section 5.7, and a new
eleventh limitation; reports the executed 15-replication robustness
extension (previously described as unexecuted); and states explicitly that
no conclusion relies on stock prices disciplining corporate environmental
behavior. The full claim classification is in `docs/CLAIM_MATRIX.md`.
Strategy B (adding an own-share-price feedback channel) was rejected because
the core contribution does not require it, it would convert 7,200 completed
policy runs plus the validation campaign into archival evidence, and it
would add an empirically uncalibrated behavioral channel on top of a market
engine whose impact diagnostic currently fails.

## 1. Editorial verdict

The manuscript has a publishable core, but it is not ready for submission in
its current form. Its strongest contribution is not a generic finding that
rankings change. It is the joint, mechanism-based result that preventive
screening and certified data infrastructure fail in different ways and on
different time scales under realistic information and capacity constraints.

The most credible first target is **JASSS**, followed by the **Journal of
Economic Interaction and Coordination**. The current draft is below the
validation and identification threshold likely expected by JEBO, JEDC, or
Ecological Economics.

The four-horizon campaign itself is complete and internally coherent: strict
read-only validation accepts 200/200 draws at each of 120, 365, 1,000, and
2,000 days. Each draw contains three regimes and three paired replications,
giving 1,800 regime runs per horizon and 7,200 in total. No LHS simulation is
needed to report the main results. The shipped raw manifests record code
version `1645f3589408503894c7e8f44a92ffe382a9a5b4+dirty`; archival release must
therefore identify the exact dirty-tree diff or rerun under a clean tagged
version before claiming bit-level reproducibility.

## 2. Result narrative supported by the completed campaign

Positive paired effects mean improvement relative to current EU-style
supervision. Confidence intervals summarize dispersion across the 200 LHS
draw-level paired means; they are not confidence intervals for a real-world
population.

| Horizon | Hub severity effect (95% interval; P improve) | Connector severity effect (95% interval; P improve) | Default winners: baseline / hub / connector |
|---:|---:|---:|---:|
| 120 | 23.38 [20.45, 26.31]; 85.0% | -0.63 [-2.46, 1.20]; 40.5% | 95 / 96 / 9 |
| 365 | 338.12 [298.04, 378.21]; 90.5% | 44.61 [29.67, 59.56]; 60.5% | 106 / 76 / 18 |
| 1,000 | 2,256.24 [2,002.60, 2,509.88]; 89.0% | 1,855.23 [1,710.74, 1,999.71]; 97.0% | 71 / 27 / 102 |
| 2,000 | 8,391.02 [7,437.20, 9,344.84]; 87.5% | 12,216.10 [11,498.51, 12,933.70]; 100.0% | 67 / 14 / 119 |

### Mechanism 1: the hub has a structural prevention-suppression-cost trade-off

The hub lowers original material overstatements in 87.5-91.0% of draws and
exposure-weighted severity in 85.0-90.5% across horizons. Yet its mean
greenhushing effect is negative at every horizon (-0.00462, -0.00637,
-0.00574, and -0.00502), and it improves greenhushing in only 0-6.5% of
draws. It increases discounted public cost in every draw, by mean simulated
amounts of EUR 24,290, 26,462, 28,751, and 32,088. Mean firm policy plus
reporting cost is also higher under the hub: EUR 1,483 versus 508 at 120 days,
EUR 3,579 versus 1,231 at 365 days, EUR 8,181 versus 2,847 at 1,000 days, and
EUR 16,075 versus 5,784 at 2,000 days.

This is the central substantive result: stricter and more widely used
pre-screening improves claim quality through revision and withdrawal, while
also suppressing defensible communication and consuming public and firm
resources. Participation and strictness have positive PRCCs with severity
improvement and negative PRCCs with greenhushing improvement, supporting the
mechanism within the model. They do not establish real behavioral elasticities.

### Mechanism 2: connector benefits accumulate slowly

The connector is effectively null-to-heterogeneous at 120 days, mixed but
positive on average at 365 days, and robustly favorable on severity at 1,000
and 2,000 days. Original material overstatements improve in 50.5%, 68.5%,
100%, and 100% of draws. The plausible within-model mechanism is cumulative:
authorization, recurring transfers, provenance, reconciliation, correction,
and conflict resolution require time before they affect exposure.

This benefit is not a cost-saving result. The connector increases discounted
public cost in every draw, by mean simulated amounts of EUR 64,071, 70,352,
86,192, and 111,608. It also creates more evidence conflicts and longer
resolution processes. These are procedure and workload effects, not observed
administrative cost estimates.

### Mechanism 3: ranking instability motivates conditional policy maps

Default winners reverse across horizons for 161/200 shared draws (80.5%).
Within-horizon winners change when normative weights change in 70.0%, 63.0%,
58.0%, and 45.5% of draws. This is not a model failure. It shows that different
institutions occupy different locations on the accuracy-greenhushing-cost
frontier and that time changes those locations. Current supervision is Pareto
non-dominated in all 200 draws at every horizon; the hub appears on the Pareto
front in 183, 180, 180, and 184 draws, and the connector in 164, 174, 200, and
200 draws. The paper should therefore report conditional policy maps, raw
effects, and Pareto frequency before composite rankings.

## 3. Prioritized revision plan

### Priority 1 — required before submission

1. **Reframe the title, abstract, introduction, findings, and conclusion around
   the two mechanisms above.** Ranking reversal is supporting evidence for
   conditional analysis, not the headline contribution.
2. **Add the financial validation section and disclose the negative result.**
   *Done (17 July 2026).* Section 5.7 now reports the completed 30-seed
   campaign: volatility clustering, spread/depth, trade-sign persistence, and
   cancellation activity reproduced; fat tails, volume-volatility, and weak
   linear return autocorrelation partially reproduced; positive price impact
   **not reproduced**. Do not call the financial market validated.
3. **Correct the legal characterization of 4%.** Directive (EU) 2019/2161
   requires national maximum fines for the relevant widespread infringements
   to be at least 4% of relevant turnover; it does not fix 4% as a uniform EU
   ceiling. The unchanged in-model 4% cap is a `LEGAL-ANCHOR` scenario choice.
4. **Implement or expressly remove the claim of full CSDDD scope fidelity.**
   Directive (EU) 2026/470 changes the principal company threshold to more than
   5,000 employees and more than EUR 1.5 billion net worldwide turnover. The
   current `LegalRegime` gates CSDDD by date but does not expose a firm-scope
   test. Until corrected and tested, describe the CSDDD track as a date- and
   remedy-gated procedural abstraction, not a complete scope implementation.
5. **Clean reproducibility provenance.** Resolve the `+dirty` result version,
   archive a patch or exact source tree, and align manuscript, data dictionary,
   reproducibility guide, configuration, manifests, and directory layout.
6. **Move implementation detail to an ODD supplement.** Keep information
   boundaries, institutional mechanisms, timing, and outcome definitions in
   the article; move class structure, state fields, full event schedule,
   constants, and test inventory to the supplement.

### Priority 2 — strong reviewer-risk reduction

7. *Done (16 July 2026).* The 15-replication extension has been executed on
   12 representative draws at all four horizons
   (`results/replication_robustness/`). It narrows paired intervals in 92.3%
   of comparable cells (median half-width ratio 0.26) but confirms the
   three-replication default-weight winner in only 32/48 draw-horizon cells,
   so the manuscript now emphasizes distribution-level statements over
   draw-level winner labels.
8. Expand related work using a mechanism-gap matrix, not a citation list.
9. Add sectoral and country-specific external validation targets, even if data
   acquisition remains future work.
10. Replace “no universal winner” subsection titles with mechanism titles and
    place ranking stability after the two policy mechanisms.

### Priority 3 — presentation

11. Number the three manuscript figures in order as Figures 1-3 and update all
    references.
12. Reduce repeated legal disclaimers while retaining one prominent statement
    in the abstract, methods, table notes, and conclusion.
13. Keep simulated euros in tables but label them “simulation-scale accounting
    units”; do not use a currency symbol in the main narrative without that
    qualifier.

## 4. Proposed revised abstract

Environmental-claim governance combines an information problem with an
institutional-capacity problem: regulators observe claims and uncertain
evidence rather than firms' latent environmental states, while preventive
scrutiny may suppress truthful communication. We develop an information-safe
agent-based model linking corporate environmental claims, consumer demand,
investor valuation, workforce responses, a limit-order-book market, and
capacity-constrained supervision. We compare current EU-style ex-post
supervision with two experimental institutions: a voluntary algorithmic SME
pre-screening hub and a certified green-data connector. A 28-parameter Latin
hypercube design evaluates 200 configurations at 120, 365, 1,000, and 2,000
days, with three paired common-random-number replications per configuration.
Within the model, the hub reduces exposure-weighted claim severity in
85.0-90.5% of configurations across horizons, but systematically increases
greenhushing and public and firm compliance costs. The connector is weak and
heterogeneous at 120 days, improves severity in 60.5% of configurations at 365
days, and becomes robust at 1,000 and 2,000 days (97.0% and 100.0%), while
remaining cost-intensive and increasing evidence-conflict workload. Default
rankings reverse across horizons in 80.5% of matched configurations, showing
why policy comparisons must be conditional on time, evidence quality,
capacity, participation, and normative weights. A 30-seed stylized-facts
validation of the market engine reproduces volatility clustering, positive
spread and depth, trade-sign persistence, and cancellation activity;
partially reproduces fat tails, the volume-volatility relation, and weak
linear return autocorrelation; and does not reproduce positive price impact
under the implemented diagnostic. The market layer is therefore reported as
endogenous market response and financing context: firm greenwashing,
disclosure, and transition-investment rules contain no own-share-price
feedback, and no conclusion relies on stock-price discipline of corporate
behavior. The results are transparent simulation-based policy orderings, not
empirical forecasts or causal estimates.

## 5. Proposed contribution statement

The paper contributes a computational institutional-design framework for
environmental-claim supervision. Its novelty lies in combining three elements
that are usually modeled separately: (i) information-safe supervision in which
no decision-maker observes latent environmental truth; (ii) procedural
enforcement with queues, correction windows, assurance, track-gated remedies,
and capacity-consuming evidence conflict; and (iii) endogenous feedback from
claims and public decisions into consumption, finance, and workforce outcomes.
This integration reveals two conditional mechanisms: preventive pre-screening
trades lower modeled overstatement for more greenhushing and higher cost,
whereas certified data infrastructure produces delayed claim-quality benefits
that become robust only over longer horizons. The global paired design maps
where these mechanisms hold and why normative rankings change; it does not
estimate real-world policy effects.

## 6. Recommended article structure

1. **Introduction:** policy problem, research question, two mechanism
   hypotheses, concise contribution.
2. **Related work and positioning:** compliance/enforcement ABMs; RegTech and
   SupTech; greenwashing/greenhushing; financial ABM validation; computational
   policy experiments and ODD.
3. **EU institutional setting:** only legally necessary tracks, verified dates,
   scope boundaries, and explicit experimental institutions.
4. **Model:** purpose, agents, information boundaries, corporate communication,
   enforcement and conflict, market response and financing channel (with the
   explicit statement that firm environmental decisions contain no
   own-share-price feedback). Move implementation detail to an ODD supplement.
5. **Experimental design and validation:** paired CRN design, LHS, outcomes,
   financial stylized-facts validation, robustness protocol.
6. **Results:** hub trade-off; connector horizon dependence; conflict/capacity;
   conditional rankings and Pareto maps; parameter importance.
7. **Discussion:** external validity, design implications, what evidence would
   change the conclusions.
8. **Limitations and conclusion.**

## 7. Financial stylized-facts validation

### Completed 30-seed campaign (authoritative)

The fixed-parameter validation campaign is complete: 30 independent seeds,
10,000-day horizon, 2,000-day burn-in, baseline `current_eu_supervision`
regime, daily market series plus the primary listing's order-book event
stream (about 256,000-298,000 events per seed, 1.09 GB total). Statuses
follow rules declared before execution; the seed is the unit of inference
(`results/financial_validation/pilot_30seeds/diagnostics/`).

| Fact | Cross-seed evidence (means over 30 seeds) | Classification |
|---|---|---|
| Volatility clustering | absolute-return ACF 0.170 and squared-return ACF 0.183 at lag 1 | Reproduced (30/30) |
| Positive spread and depth | mean spread 1.38 ticks; two-sided depth | Reproduced (30/30) |
| Trade-sign persistence | lag-1 sign ACF 0.486 vs ~0.009 band | Reproduced (30/30) |
| Cancellation activity | cancellation/submission ratio 0.537 | Reproduced (30/30) |
| Volume-volatility relation | mean correlation 0.113 | Partially reproduced (17 R / 13 P) |
| Fat-tailed returns | mean excess kurtosis 1.99; mean Hill alpha 5.38 | Partially reproduced (3 R / 27 P) |
| Weak linear return autocorrelation | mean lag-1 return ACF -0.082 | Partially reproduced (29 P / 1 N) |
| Positive price impact | mean log-volume x immediate absolute mid-move correlation -0.013 | **Not reproduced** (4 P / 26 N) |

The earlier single-path diagnostic of the detached `simulation_results.csv`
(fat tails reproduced, kurtosis 21.66, return ACF 0.445 at lag 1) is
superseded: that path was unrepresentative of the seed distribution and is
retained only as provenance history. The multi-seed campaign shows thinner
tails and much weaker linear predictability than the single path suggested.

### Remaining publication-grade work (future, requires simulation or new code)

1. Replace or supplement the unsigned immediate-impact diagnostic with a
   signed event-level measure (trade sign x future mid-price change at
   multiple event horizons) with seed-level uncertainty.
2. Report return CCDFs, tail-fraction sensitivity for Hill estimates, QQ
   plots, leverage, and aggregational Gaussianity across seeds.
3. Compare against documented empirical targets by frequency and market. Do
   not tune the policy experiment directly to a single asset.

## 8. Related-work outline and positioning

### Compliance and enforcement ABMs

Use tax-compliance models (for example Korobow, Johnson, and Axtell, 2007) and
large-scale taxpayer-reporting models as precedents for endogenous compliance,
social interaction, inspection, and regulator behavior. Add recent work on
data-driven inspection ABMs and environmental enforcement. The gap is that
these models usually do not jointly represent uncertain claim evidence,
legally sequenced remedies, greenhushing, and financial-market feedback.

### RegTech and SupTech

Use the BIS/FSI and FSB literature to motivate data collection, automated risk
analysis, data-quality risk, operational risk, explainability, and supervisory
governance. Position the hub as a preventive RegTech/SupTech experiment and the
connector as data infrastructure, not as implementations of existing law.

### Greenwashing and greenhushing

Retain Delmas and Burbano; Lyon and Maxwell; Lyon and Montgomery; Marquis,
Toffel, and Zhou; Seele and Gatti; and Font, Elgammal, and Lamond. Organize them
around mechanisms: strategic overstatement, selective disclosure, scrutiny,
audit threat, accusation, and silence. The model contribution is to make
greenhushing endogenous to institutional procedure rather than to introduce
the concept.

### Financial ABM validation

Add Cont (2001) for the empirical stylized-fact benchmark and Lux and Marchesi
(1999) for endogenous scaling and volatility persistence in multi-agent
markets. Contrast “can reproduce a fact” with empirical calibration and
out-of-sample validation. The paper must report the failure on linear return
autocorrelation.

### Computational policy experiments and ODD

Use Grimm et al. (2020) for ODD and recent ABM validation guidance for
traceability, uncertainty, and structural realism. Present the model as an
exploratory policy laboratory with global uncertainty analysis, not a digital
twin.

### Defensible novelty wording

Use: “To our knowledge, the paper is among the first computational policy
experiments to combine information-safe environmental-claim supervision,
explicit legal procedure and evidentiary conflict, and endogenous
financial/real-economy feedback in one paired institutional comparison.”

Do not use “the first” until a documented systematic search establishes that
no close integration exists. Novelty is the combination and its consequences,
not any individual component.

## 9. Legal audit checklist

This is a research audit, not legal advice. Every legal row should receive
independent review by an EU-law specialist and, where national transposition is
modeled, by counsel in the relevant Member State.

| Item | Audit result at 15 July 2026 | Required action |
|---|---|---|
| Directive 2005/29/EC (UCPD) | Correct general B2C baseline; national enforcement details omitted | Retain reduced-form label; review national remedies |
| Directive (EU) 2024/825 | Verified: transpose by 27 Mar 2026; apply from 27 Sep 2026 | Retain date; distinguish EU deadline from national measure |
| Directive (EU) 2019/2161, 4% | Current “4% ceiling” wording is inaccurate: national maximum must be **at least** 4% for relevant widespread infringements | Treat model's exact 4% cap as `LEGAL-ANCHOR`; correct paper, registry, and code comments |
| Directive (EU) 2026/470 existence/status | Verified official act of 24 Feb 2026, OJ 26 Feb, in force | Retain primary EUR-Lex citation |
| Revised CSRD scope | Verified conjunction: net turnover exceeding EUR 450m and average employees exceeding 1,000, including group rules | Retain strict inequalities; review issuer/third-country/group branches separately |
| 19 Mar 2027 | Verified as transposition deadline for Articles 1-3, not a universal day-level application date | Label only as configurable national implementation scenario; do not call it the EU application date |
| CSDDD application | Verified: measures applied from 26 Jul 2029; transposition by 26 Jul 2028 | Retain dates |
| Revised CSDDD main scope | More than 5,000 employees and more than EUR 1.5bn worldwide turnover for EU companies; additional group/franchise/third-country rules exist | Add a firm-scope gate or narrow the manuscript claim; current date-only gate is incomplete |
| CSDDD penalty | Verified uniform maximum limit of 3% of worldwide net turnover (or consolidated group turnover where applicable) | Retain track-gated 3%; review base, group and national implementation |
| Green Claims proposal COM(2023)166 | Procedure remained ongoing/awaiting Council first-reading position; not enacted baseline law | Retain disabled counterfactual and update status immediately before submission |
| EU Taxonomy | Evidence/consistency abstraction only; full technical screening, DNSH and safeguards absent | Keep limitation and independently review each claimed field |
| MAR, Prospectus, Transparency | Reduced-form track separation is conceptually sound, but detailed scope and remedies not audited here | Legal review required; avoid claiming doctrinal completeness |
| European Green Bonds | Voluntary designation framing appears appropriate; detailed external-review and disclosure workflow simplified | Verify application provisions and delegated acts |
| GDPR/NIS2/data governance | Connector governance is not implemented | State clearly; do not imply deployability or legal compliance |
| Sanction procedure | Model timing and track gates are experimental procedural representations | Review competent authority, jurisdiction, appeal, judicial review, limitation, and national law |

Primary sources used in this audit:

- [Directive (EU) 2026/470](https://eur-lex.europa.eu/eli/dir/2026/470/oj/eng)
- [Consolidated Directive (EU) 2024/1760](https://eur-lex.europa.eu/eli/dir/2024/1760/2026-03-18/eng)
- [Directive (EU) 2024/825](https://eur-lex.europa.eu/eli/dir/2024/825/oj/eng)
- [Directive (EU) 2019/2161](https://eur-lex.europa.eu/eli/dir/2019/2161/oj/eng)
- [Green Claims procedure 2023/0085/COD](https://oeil.secure.europarl.europa.eu/oeil/en/procedure-file?reference=2023%2F0085%28COD%29)

## 10. Venue strategy

| Venue | Current fit | Likely objections | Minimum revision | One paper or split? |
|---|---|---|---|---|
| JASSS | High: information-safe ABM, institutional process, ODD, sensitivity | Insufficient validation; excessive legal detail; weak replication tails; unclear generalization | Add validation section, ODD supplement, mechanism framing, legal corrections, clean archive | Keep integrated; best first submission |
| Journal of Economic Interaction and Coordination | High-medium: heterogeneous agents, artificial market, emergent institutional outcomes | Financial market not validated; economics may be obscured by legal engineering; welfare weights ad hoc | Strengthen market diagnostics, economic mechanisms, sensitivity interactions and conditional welfare maps | Integrated if shortened; optional methods appendix |
| JEBO | Medium-low | Limited behavioral estimation/identification; stylized preference and trust channels; simulation may read as engineering | Empirical grounding or disciplined behavioral hypotheses, replication extension, external moments | Likely split; policy/behavior paper needs stronger empirical anchor |
| JEDC | Medium-low | Dynamic/control contribution underdeveloped; limit-order-book failure on return autocorrelation; no calibration | Repair and validate market dynamics, show computational-method novelty, formalize dynamic mechanisms | Split into model/market methods paper plus policy experiment |
| Ecological Economics | Medium | Environmental outcomes and welfare are not empirically grounded; financial/legal machinery may dominate ecological contribution | Stronger ecological outcome validation, distributional justice, policy relevance, ecological-economic trade-offs | Prefer integrated only after ecological reframing; otherwise policy paper separate |

## 11. Claim-support matrix

### Well supported by existing completed simulations or code tests

- All four horizons contain the same 200 LHS draws, three paired replications,
  and three regimes; the current raw files pass strict identity and finite-
  metric validation.
- Common random numbers are used across regimes within a replication and seed
  schedules vary across replications and draws.
- The hub's within-model claim-quality improvement, greenhushing increase, and
  public/firm cost increase across the sampled space.
- The connector's strong horizon dependence, long-run severity improvement,
  persistent public cost, and evidence-conflict workload.
- Ranking reversal, normative weight sensitivity, Pareto frequency, and the
  reported parameter-importance associations.
- Information boundaries, correction immutability, conflict corroboration,
  track gating, and accounting invariants to the extent covered by repository
  tests.
- The verified EU dates and thresholds identified as verified in the legal
  audit table.

### Weakly supported and requiring qualification

- “Structural mechanism” claims: supported by sensitivity associations and
  code pathways, but not causal decomposition or empirical evidence.
- Financial realism: across 30 seeds, four microstructure/volatility facts
  are reproduced; fat tails, volume-volatility, and weak linear return
  autocorrelation are partial; positive price impact is not reproduced.
- Novelty: the combination appears distinctive, but an absolute first claim
  requires a systematic search.
- Rare failures, escalation, and tail rankings: three replications are a
  screening design; the executed 15-replication extension narrows intervals
  but confirms the draw-level default winner in only 32/48 cells.
- Administrative and firm cost comparisons: internally consistent but in
  simulation-scale accounting units only.
- CSDDD implementation: date and sanction gate are present, but full company
  scope is not.

### Unsupported and prohibited in the current paper

- Any empirical forecast of EU greenwashing, greenhushing, fiscal cost,
  enforcement effectiveness, prices, employment, or emissions.
- Any causal real-world treatment effect of the hub or connector.
- Any claim that behavioral, cost, error, or participation parameters are
  calibrated estimates.
- Any assertion that the financial market is empirically validated.
- Any claim that equity prices discipline corporate greenwashing,
  disclosure, or transition investment — the model contains no such channel
  (static audit, `results/audits/`), and positive price impact is not
  reproduced.
- Any claim that a real connector would satisfy GDPR, NIS2, cybersecurity,
  interoperability, or public-sector governance requirements.
- Any fixed “4% EU ceiling” characterization under Directive (EU) 2019/2161.

The complete per-claim classification for the revised manuscript is
maintained in `docs/CLAIM_MATRIX.md`.

## 12. Analyses that remain pending

- **Can be regenerated without simulation now:** all four horizon summaries,
  run-level tables, parameter importance, ranking stability, Pareto tables, and
  policy figures; multi-seed financial diagnostics re-analysis from stored
  seed outputs.
- **Completed since the original review (no further simulation needed):**
  the 15-replication robustness extension (12 draws x 4 horizons); the
  30-seed financial validation campaign with order-book event exports; the
  static firm price-feedback and paper-materiality audits.
- **Requires future simulation or new code and is not reported:** signed
  event-level price-impact diagnostics; structural variants and empirical
  calibration; any market-discipline extension (explicitly deferred and, if
  ever undertaken, to be pre-registered and versioned).
