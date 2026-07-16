"""
Centralized market microstructure constants.

Single source of truth for every structural parameter of the simulation:
transactional friction bounds (Part D), corporate solvency floors, LOB
order-evaporation hazard bounds (Part D), and the evolutionary review
configuration (Part A). Importing modules must reference these by name --
no magic numbers are permitted to shadow them elsewhere in the package.

Every constant is declared `typing.Final`: the namespace is frozen against
accidental runtime mutation and static compilers (Cython/MyPyC) may inline
the values. Monetary/fee constants additionally carry an exact
`decimal.Decimal` counterpart (`*_DEC`) for arbitrary-precision accounting
contexts; the float mirrors used in the hot loops are derived from the
Decimal canon so the two representations can never disagree.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Final

# --------------------------------------------------------------------------- #
# Friction (Part D, fix 1): rates float between a floor and a base level
# depending on the current volume regime. Escrow accounting is pinned to the
# rate in force at order placement (stored per order).
# --------------------------------------------------------------------------- #
BASE_COMMISSION_RATE_DEC: Final[Decimal] = Decimal("0.001")
TOBIN_TAX_RATE_DEC: Final[Decimal] = Decimal("0.005")

BASE_COMMISSION_RATE: Final[float] = float(BASE_COMMISSION_RATE_DEC)
MIN_COMMISSION_RATE: Final[float] = 0.0005  # Commission floor, low volume.
TOBIN_TAX_RATE: Final[float] = float(TOBIN_TAX_RATE_DEC)
MIN_TOBIN_RATE: Final[float] = 0.001        # Tobin floor in low-volume regimes.
TOBIN_HOLDING_DAYS: Final[int] = 10        # Holding threshold, Tobin tax.

# Pre-computed friction interpolation spans (hot path of update_friction).
COMMISSION_RATE_SPAN: Final[float] = BASE_COMMISSION_RATE - MIN_COMMISSION_RATE
TOBIN_RATE_SPAN: Final[float] = TOBIN_TAX_RATE - MIN_TOBIN_RATE

# --------------------------------------------------------------------------- #
# Corporate balance sheet and dividend policy.
# --------------------------------------------------------------------------- #
CORPORATE_BALANCE_FLOOR_DEC: Final[Decimal] = Decimal("20000.0")
BASE_DIVIDEND_PER_SHARE_DEC: Final[Decimal] = Decimal("2.00")

CORPORATE_BALANCE_FLOOR: Final[float] = float(CORPORATE_BALANCE_FLOOR_DEC)
BASE_DIVIDEND_PER_SHARE: Final[float] = float(BASE_DIVIDEND_PER_SHARE_DEC)

# Pre-computed log-space solvency floor for the OU fundamental (Part B):
# the daily balance step runs entirely in log space and clamps against this.
LOG_CORPORATE_BALANCE_FLOOR: Final[float] = math.log(CORPORATE_BALANCE_FLOOR)

# --------------------------------------------------------------------------- #
# Order-book depth measurement.
# --------------------------------------------------------------------------- #
IMBALANCE_BAND: Final[float] = 0.05  # Depth-imbalance band around mid.

# --------------------------------------------------------------------------- #
# LOB order evaporation (Part D, fix 2): per-day cancellation hazard grows
# with order age; expected order life ~4-5 days with a fat tail, so stale
# walls dissolve gradually instead of snapping out on a fixed TTL.
# --------------------------------------------------------------------------- #
ORDER_DECAY_BASE_HAZARD: Final[float] = 0.01
ORDER_DECAY_AGE_SCALE: Final[float] = 15.0
ORDER_DECAY_MAX_HAZARD: Final[float] = 0.45

# --------------------------------------------------------------------------- #
# Evolutionary review (Part A): logit choice with memory and a switch cap.
# --------------------------------------------------------------------------- #
EVOLUTION_EPOCH_DAYS: Final[int] = 60
INTENSITY_OF_CHOICE: Final[float] = 120.0  # Logit beta on smoothed returns.
STRATEGY_MEMORY: Final[float] = 0.75       # EWMA weight, past attractiveness.
LAMBDA_MEMORY: Final[float] = 1.0 - STRATEGY_MEMORY  # Complementary weight.
SWITCH_CONSIDERATION_RATE: Final[float] = 0.30  # Fraction that re-evaluates.
MAX_SWITCH_FRACTION: Final[float] = 0.02   # Cap on migration per epoch.

# --------------------------------------------------------------------------- #
# Credit system (Part E): P2P + institutional lending layer. Strictly
# additive -- nothing above this block is referenced or redefined here, and
# the credit layer is inert unless Simulation(enable_credit=True).
# All monetary parameters carry a Decimal canon for the exact ledger; the
# float mirrors are derived from it (single source of truth).
# --------------------------------------------------------------------------- #
# Endogenous rate discovery: Rate = BASE + ALPHA * utilization (annualised),
# converted to a daily rate over the credit day count.
CREDIT_BASE_ANNUAL_RATE_DEC: Final[Decimal] = Decimal("0.05")
CREDIT_UTILIZATION_ALPHA_DEC: Final[Decimal] = Decimal("0.10")
CREDIT_BASE_ANNUAL_RATE: Final[float] = float(CREDIT_BASE_ANNUAL_RATE_DEC)
CREDIT_UTILIZATION_ALPHA: Final[float] = float(CREDIT_UTILIZATION_ALPHA_DEC)
CREDIT_DAY_COUNT: Final[int] = 365         # Day-count convention for accrual.

# Collateralization: max loan-to-value shrinks as realised volatility rises.
#   LTV_max(vol) = clamp(CREDIT_MAX_LTV / (1 + CREDIT_LTV_VOL_SENSITIVITY
#                                              * rel_volatility),
#                        CREDIT_MIN_LTV, CREDIT_MAX_LTV)
CREDIT_MAX_LTV: Final[float] = 0.60
CREDIT_MIN_LTV: Final[float] = 0.15
CREDIT_LTV_VOL_SENSITIVITY: Final[float] = 8.0
COLLATERAL_FRACTION: Final[float] = 0.50   # Share of free shares pledgeable.
MIN_COLLATERAL_SHARES: Final[int] = 10     # Smallest viable pledge.

# Clearing house: forced liquidation fires when debt exceeds this fraction
# of the mark-to-market collateral value.
MAINTENANCE_MARGIN_RATIO: Final[float] = 0.85

# Macroprudential leverage cap: total debt may never exceed this multiple
# of the borrower's mark-to-market equity (wealth net of debt).
MAX_DEBT_TO_EQUITY: Final[float] = 2.0

# P2P lending vault: surplus agents (MarketMaker, wealthy fundamentalists)
# commit a fraction of idle cash above the liquidity threshold.
P2P_LENDER_MIN_CASH: Final[float] = 100_000.0
P2P_VAULT_FRACTION: Final[float] = 0.25

# Borrowing trigger: cash-constrained means available cash below this many
# multiples of the current price; attractiveness must exceed the floor.
BORROWER_CASH_MULTIPLE: Final[float] = 20.0
CREDIT_ATTRACTIVENESS_FLOOR: Final[float] = 0.0
CREDIT_MAX_LINES_PER_BORROWER: Final[int] = 3

# Institutional lender of last resort.
BANK_INITIAL_CAPITAL_DEC: Final[Decimal] = Decimal("2000000.0")
BANK_INITIAL_CAPITAL: Final[float] = float(BANK_INITIAL_CAPITAL_DEC)

# Exact-ledger quantum: every credit cash flow is quantized to the cent in
# Decimal space before being mirrored (as the identical float) to both
# sides of the transfer, so the float ledger conserves bit-for-bit.
CREDIT_CENT_DEC: Final[Decimal] = Decimal("0.01")

# --------------------------------------------------------------------------- #
# ESG / Green transition macro-framework (Part F). Strictly additive: the
# whole layer is inert unless Simulation(enable_esg=True), and nothing
# above this block is referenced or redefined.
# --------------------------------------------------------------------------- #
# Historical capital penalty: green pioneers listed with pre-spent CAPEX.
#   initial_balance *= (1 - GREEN_CAPEX_FACTOR * green_score)
GREEN_CAPEX_FACTOR: Final[float] = 0.30

# Greenium: fundamentalists price sustainability conviction into fair value.
#   V_green_fair = V_fundamental * (1 + GREENIUM_GAMMA * green_score)
GREENIUM_GAMMA: Final[float] = 0.25

# Corporate green transition step: a cent-quantized CAPEX outlay buys a
# permanent green_score increment, only while the balance stays safely
# above the corporate solvency floor.
GREEN_TRANSITION_STEP: Final[float] = 0.05
GREEN_TRANSITION_COST_DEC: Final[Decimal] = Decimal("15000.00")
GREEN_TRANSITION_COST: Final[float] = float(GREEN_TRANSITION_COST_DEC)
GREEN_TRANSITION_SAFETY: Final[float] = 2.0   # Post-CAPEX balance floor mult.

# State / government climate intervention layer.
STATE_TREASURY_DEC: Final[Decimal] = Decimal("5000000.00")
STATE_TREASURY: Final[float] = float(STATE_TREASURY_DEC)
STATE_SUBSIDY_EPOCH_BUDGET_DEC: Final[Decimal] = Decimal("50000.00")
STATE_GREEN_THRESHOLD: Final[float] = 0.70    # Sovereign-fund eligibility.
STATE_DAILY_INVESTMENT_DEC: Final[Decimal] = Decimal("2000.00")
STATE_DAILY_INVESTMENT: Final[float] = float(STATE_DAILY_INVESTMENT_DEC)

# Central-bank Taylor rule with Gaussian monetary surprise:
#   rate = R_TARGET + BETA_PI*(pi - PI_STAR) + BETA_Y*output_gap + N(0, s^2)
TAYLOR_R_TARGET: Final[float] = 0.05
TAYLOR_BETA_PI: Final[float] = 1.5
TAYLOR_BETA_Y: Final[float] = 0.5
TAYLOR_PI_STAR: Final[float] = 0.0
TAYLOR_SHOCK_SIGMA: Final[float] = 0.002
TAYLOR_RATE_FLOOR: Final[float] = 0.0
TAYLOR_RATE_CAP: Final[float] = 0.25

# Green-manipulator narrative sentiment: how many days a subsidy or a
# transition keeps an asset "hot", and the extra sentiment each adds on
# top of the raw green score when the spoofer picks its target.
GREEN_SENTIMENT_WINDOW_DAYS: Final[int] = 60
GREEN_SENTIMENT_EVENT_BOOST: Final[float] = 0.50

# --------------------------------------------------------------------------- #
# Part G -- Greenwashing under Directive (EU) 2026/470 ("Omnibus").
# Strictly additive: everything below is inert unless
# Simulation(enable_esg=True) and, for the regulatory blocks, the
# enable_regulation=True sub-flag. Nothing above this line is referenced
# or redefined here.
# --------------------------------------------------------------------------- #

# -- WP1: stylized regulatory layer (regulation.py) -------------------------- #
# STYLIZATION (Art. 2(4), amending Art. 19a of 2013/34/EU): the directive
# scopes mandatory sustainability reporting by net turnover (> EUR 450m)
# and headcount (> 1000 employees). The simulation has neither payrolls
# nor revenue statements, so firm size is proxied by the corporate
# balance at listing and compared against this threshold analog.
REG_MANDATORY_SIZE_THRESHOLD_DEC: Final[Decimal] = Decimal("2000000.00")
REG_MANDATORY_SIZE_THRESHOLD: Final[float] = \
    float(REG_MANDATORY_SIZE_THRESHOLD_DEC)

# STYLIZATION (Art. 1(3) and recital 5): the Omnibus removes the escalation
# to reasonable assurance; sustainability statements stay under *limited*
# assurance. Modeled as a low-probability audit whose detection power is
# logistic in the disclosed-vs-true wedge. The audit probability, slope
# and midpoint are modeling choices calibrated to "low-power" review, not
# numbers from the directive.
REG_AUDIT_PROBABILITY: Final[float] = 0.25   # Per reporting period.
REG_DETECT_STEEPNESS: Final[float] = 12.0    # Logistic slope in the wedge.
REG_DETECT_MIDPOINT: Final[float] = 0.25     # Wedge with 50% detection.
REG_WEDGE_TOLERANCE: Final[float] = 0.02     # Measurement noise floor.

# STYLIZATION (Art. 2(4)(b)(iii)): commercial-prejudice / trade-secret /
# security omissions let a firm lawfully withhold negative information.
# Modeled as a per-firm rate damping *downward* revisions of the disclosed
# score; the withheld portion accumulates in a capped lawful buffer that
# audits must NOT count as misreporting.
REG_OMISSION_RATE_DEFAULT: Final[float] = 0.30
REG_OMISSION_BUFFER_CAP: Final[float] = 0.15

# STYLIZATION (Art. 4(19), amending CSDDD Art. 27(4)): pecuniary sanctions
# are capped at 3% of net worldwide turnover. The simulation has no income
# statement, so turnover is proxied as a fixed multiple of the corporate
# balance; the multiple is a modeling choice.
REG_PENALTY_RATE_DEC: Final[Decimal] = Decimal("0.03")
REG_PENALTY_RATE: Final[float] = float(REG_PENALTY_RATE_DEC)
REG_TURNOVER_BALANCE_MULTIPLE_DEC: Final[Decimal] = Decimal("0.50")
REG_TURNOVER_BALANCE_MULTIPLE: Final[float] = \
    float(REG_TURNOVER_BALANCE_MULTIPLE_DEC)

# STYLIZATION (recital 47): the Omnibus repeals the obligation to *adopt*
# climate transition plans; firms only report plans they voluntarily have.
# False = post-Omnibus regime (transition purely NPV-driven, WP5);
# True  = pre-Omnibus counterfactual (no backsliding, forced minimum step).
REG_TRANSITION_PLANS_MANDATORY: Final[bool] = False
REG_MANDATED_MIN_STEP: Final[float] = 0.0005  # Counterfactual daily floor.

# STYLIZATION (Art. 3 and Art. 5): phase-in / 2027 transposition. Before
# this simulation day, audits and penalties are inactive and disclosure is
# voluntary for everyone (pre-enforcement regime for policy experiments).
REG_ENFORCEMENT_START_DAY: Final[int] = 240

# STYLIZATION: the EU green-bond framework (Regulation (EU) 2023/2631) is
# left in force by the Omnibus; this flag is purely the experiment lever
# for the WP6 sovereign program, not a provision of Directive 2026/470.
REG_GREEN_BONDS_ALLOWED: Final[bool] = True

# Reporting cadence (aligned with the evolutionary epoch so disclosure,
# subsidies and dividends share one corporate calendar).
REG_REPORTING_PERIOD_DAYS: Final[int] = 60

# -- WP2: greenwashing corporate agent (corporates.py) ----------------------- #
# Cheap-talk disclosure: PR/reporting cost per inflation step, orders of
# magnitude below the real GREEN_TRANSITION-scale CAPEX.
GREENWASH_REPORT_COST_DEC: Final[Decimal] = Decimal("150.00")
GREENWASH_REPORT_COST: Final[float] = float(GREENWASH_REPORT_COST_DEC)
# Plausibility cap on per-period wedge growth (a firm cannot claim to have
# gone from coal to carbon-neutral in one reporting period).
GREENWASH_MAX_WEDGE_STEP: Final[float] = 0.10
# Inflation-choice grid for the one-period expected-profit argmax.
GREENWASH_CHOICE_GRID: Final[tuple] = (0.0, 0.02, 0.04, 0.06, 0.08, 0.10)
# Adaptive-type risk dynamics (modeling choice, no directive basis):
# after its own scandal an adaptive firm reports honestly for the memory
# window, then re-enters the argmax with penalty aversion scaled up.
ADAPTIVE_SCANDAL_MEMORY_DAYS: Final[int] = 180
ADAPTIVE_RISK_AVERSION_STEP: Final[float] = 0.75

# Corporate treasury stake (harvest channel a: insider/treasury sales into
# the greenium). Shares held by the corporate ledger shell at listing and
# sold in clips once the disclosed score commands a market premium.
CORPORATE_TREASURY_SHARES: Final[int] = 1_000
TREASURY_SELL_CLIP: Final[int] = 25          # Shares per reporting period.
TREASURY_MIN_PREMIUM: Final[float] = 0.02    # Min price/fair gap to sell.
# Fraction of incremental sovereign-fund buy flow the treasury is assumed
# to capture through price impact when a disclosure crosses the
# STATE_GREEN_THRESHOLD (structural parameter of the WP2 argmax; the flow
# itself is always read from live State budgets).
SOVEREIGN_FLOW_CAPTURE: Final[float] = 0.02

# -- WP3: credibility beliefs (modeling choice, no directive basis) ---------- #
CREDIBILITY_PRIOR: Final[float] = 0.60
LAMBDA_TRUST: Final[float] = 0.08            # Per-epoch drift toward 1.
SCANDAL_CREDIBILITY_SHOCK: Final[float] = 0.35   # Multiplier, own asset.
SCANDAL_SECTOR_SPILLOVER: Final[float] = 0.90    # Multiplier, other assets.
SOPHISTICATED_FRACTION: Final[float] = 0.30  # Wedge-suspicious fundamentalists.
WEDGE_SUSPICION_HAIRCUT: Final[float] = 0.50 # Extra disclosed-score haircut.
NOISE_CREDIBILITY_DILUTION: Final[float] = 0.50  # Noise traders' kappa dilution.
NOISE_GREEN_TILT: Final[float] = 0.05        # Noise buy-probability green tilt.
# Institutional reliance (WP3): the sovereign fund and the bank use the raw
# disclosed score by default -- the deliberate private-belief/institutional
# wedge. Toggle True for the counterfactual where institutions also
# discount by market credibility.
INSTITUTIONS_USE_CREDIBILITY: Final[bool] = False

# -- WP4: heterogeneous mixed-strategy agents --------------------------------#
WEIGHT_ADAPTATION_STEP: Final[float] = 0.25  # Bounded step toward target vertex.
DIRICHLET_CONCENTRATION: Final[float] = 2.0  # Initial-weight concentration.

# -- WP5: NPV-driven continuous, reversible transition ------------------------#
# Price of green capital: log-space OU around a flat anchor (reuses the
# Asset OU pattern; economy-wide, exogenous).
PGREEN_INITIAL: Final[float] = 1.0
PGREEN_LOG_REVERSION: Final[float] = 0.02
PGREEN_LOG_VOL: Final[float] = 0.02
NPV_HORIZON_DAYS: Final[int] = 250           # Myopic planning horizon H.
TRANSITION_RESPONSIVENESS: Final[float] = 5e-8   # dg/dt per $ of NPV.
G_STEP_MAX: Final[float] = 0.004             # Max daily true-score gain.
G_DECAY_MAX: Final[float] = 0.002            # Max daily backsliding.
# Convex marginal cost of real greenness (per unit of g, in $):
#   C'(g) = GREEN_MC_BASE * (1 + GREEN_MC_CONVEXITY * g / (1.05 - g))
# so the last 10% is disproportionately expensive.
GREEN_MC_BASE_DEC: Final[Decimal] = Decimal("40000.00")
GREEN_MC_BASE: Final[float] = float(GREEN_MC_BASE_DEC)
GREEN_MC_CONVEXITY: Final[float] = 1.0
GREEN_MC_POLE: Final[float] = 1.05           # Cost-curve pole (> 1).
# Certification upkeep: daily cash cost per unit of true score. Backsliding
# refunds nothing; only this maintenance saving is recovered.
GREEN_MAINTENANCE_RATE_DEC: Final[Decimal] = Decimal("8.00")
GREEN_MAINTENANCE_RATE: Final[float] = float(GREEN_MAINTENANCE_RATE_DEC)

# -- WP6: sovereign green bonds -----------------------------------------------#
GREEN_BOND_FACE_DEC: Final[Decimal] = Decimal("50000.00")
GREEN_BOND_FACE: Final[float] = float(GREEN_BOND_FACE_DEC)
GREEN_BOND_GREENIUM: Final[float] = 0.005    # Coupon discount vs policy rate.
GREEN_BOND_MATURITY_DAYS: Final[int] = 365
GREEN_BOND_COUPON_PERIOD_DAYS: Final[int] = 30
# Issue when the treasury float mirror drops below this funding threshold.
GREEN_BOND_ISSUE_THRESHOLD_DEC: Final[Decimal] = Decimal("2000000.00")
GREEN_BOND_MAX_OUTSTANDING: Final[int] = 20

# -- WP7: green-weighted bank reserve requirements ----------------------------#
RESERVE_BASE_RATIO_DEC: Final[Decimal] = Decimal("0.10")
RESERVE_BASE_RATIO: Final[float] = float(RESERVE_BASE_RATIO_DEC)
GREEN_RISK_WEIGHT_DISCOUNT: Final[float] = 0.50  # "Green supporting factor".
OMEGA_MIN: Final[float] = 0.20               # Risk-weight floor (> 0).
GREEN_BOND_OMEGA: Final[float] = 0.25        # Reserve weight of green bonds.

# --------------------------------------------------------------------------- #
# Part H -- three-regime State-intervention comparison. Strictly additive:
# everything below is inert unless a Simulation selects a non-baseline
# GreenwashingPolicyRegime (which itself requires
# enable_greenwashing_supervision=True). Nothing above this line is
# referenced or redefined here.
#
# LEGAL STATUS NOTE. Neither the SME pre-screening hub (Regime B) nor the
# certified public green data connector (Regime C) is an obligation under
# Directive (EU) 2026/470 or any other instrument in the model's baseline.
# Both are PROPOSED NATIONAL POLICY EXPERIMENTS. The only legal anchors
# used below are: the Art. 29ca voluntary-use reporting standards and the
# 1000-employee "protected undertaking" line of the value-chain cap
# (Directive (EU) 2026/470, recitals 12 and 21-22, Art. 2(4) and the new
# Art. 29ca of Directive 2013/34/EU), which merely make a voluntary
# pre-screening service *plausible* for that population -- they do not
# require or endorse one. Every number below is EXPERIMENT unless marked
# LEGAL-ANCHOR.
# --------------------------------------------------------------------------- #

# -- Regime B: SME voluntary-reporting algorithmic pre-screening hub -------- #
# LEGAL-ANCHOR: eligibility mirrors the protected-undertaking employee line
# (<= 1000 average employees, Art. 29ca / recital 12). The line scopes a
# voluntary SERVICE here; it is never an exemption from consumer law,
# investigations or substantiation duties.
PRESCREEN_MAX_EMPLOYEES: Final[float] = 1000.0
# EXPERIMENT: participation propensity per corporate strategy under the
# default voluntary mode (multiplied under subsidized/auto-invite modes).
PRESCREEN_UPTAKE_HONEST: Final[float] = 0.90
PRESCREEN_UPTAKE_ADAPTIVE: Final[float] = 0.60
PRESCREEN_UPTAKE_GREENWASHER: Final[float] = 0.35
PRESCREEN_UPTAKE_SUBSIDIZED_BOOST: Final[float] = 1.20   # Multiplier.
PRESCREEN_UPTAKE_AUTO_INVITE: Final[float] = 0.95        # Near-default-in.
# EXPERIMENT: screening algorithm behaviour. `strictness` scales issue
# severity thresholds; `noise` is the per-clean-claim probability of a
# spurious informational flag (an excessively strict or noisy algorithm
# must be able to increase withdrawal and greenhushing -- tested).
PRESCREEN_STRICTNESS_DEFAULT: Final[float] = 0.50
PRESCREEN_NOISE_DEFAULT: Final[float] = 0.08
# EXPERIMENT: hub economics (cent-quantized Decimal canon).
PRESCREEN_STATE_SETUP_COST_DEC: Final[Decimal] = Decimal("25000.00")
PRESCREEN_STATE_COST_PER_SUBMISSION_DEC: Final[Decimal] = Decimal("40.00")
PRESCREEN_FIRM_COST_PER_SUBMISSION_DEC: Final[Decimal] = Decimal("25.00")
PRESCREEN_FIRM_REVISION_COST_DEC: Final[Decimal] = Decimal("60.00")
PRESCREEN_PROCESSING_DELAY_DAYS: Final[int] = 5   # Reporting-delay metric.
# EXPERIMENT: safe-harbour-like treatment is DISABLED by default and, even
# when enabled, never covers deliberate concealment, prohibited practices,
# repeated abuse, or claims contradicted by firm-known evidence.
PRESCREEN_SAFE_HARBOR_ENABLED: Final[bool] = False

# -- Regime C: certified public green data connector ------------------------- #
# EXPERIMENT: connector economics.
CONNECTOR_STATE_SETUP_COST_DEC: Final[Decimal] = Decimal("60000.00")
CONNECTOR_STATE_DAILY_OPERATING_DEC: Final[Decimal] = Decimal("30.00")
CONNECTOR_FIRM_INTEGRATION_COST_DEC: Final[Decimal] = Decimal("150.00")
CONNECTOR_CYBER_GOVERNANCE_DAILY_DEC: Final[Decimal] = Decimal("10.00")
# EXPERIMENT: measurement quality of certified sources. Connector data are
# NOT infallible: relative meter error stays strictly positive, records
# can go stale, facilities can be mismatched, registers can hold errors,
# and the service can be down or suffer a cyber incident.
CONNECTOR_METER_RELATIVE_ERROR: Final[float] = 0.010
CONNECTOR_MISMATCH_PROBABILITY: Final[float] = 0.02
CONNECTOR_MISMATCH_BIAS: Final[float] = 0.15     # Relative bias when wrong.
CONNECTOR_STALE_PROBABILITY: Final[float] = 0.05
CONNECTOR_STALE_DAYS: Final[int] = 120
CONNECTOR_REGISTER_ERROR_PROBABILITY: Final[float] = 0.01
CONNECTOR_CORRECTION_DELAY_DAYS: Final[int] = 60
CONNECTOR_DOWNTIME_PROBABILITY: Final[float] = 0.01   # Per period+source.
CONNECTOR_CYBER_INCIDENT_PROBABILITY: Final[float] = 0.002
# EXPERIMENT: adoption propensity per strategy (greenwashers connect less
# and selectively -- selective authorization is detectable, tested).
CONNECTOR_UPTAKE_HONEST: Final[float] = 0.90
CONNECTOR_UPTAKE_ADAPTIVE: Final[float] = 0.65
CONNECTOR_UPTAKE_GREENWASHER: Final[float] = 0.40
CONNECTOR_SELECTIVE_THRESHOLD: Final[float] = 0.60  # Authorized-share flag.
# EXPERIMENT: reconciliation bands (standardized divergence z and relative
# divergence). No sanction follows automatically from any band: material
# classes only enter the existing procedurally fair supervision queue.
RECONCILE_ROUNDING_REL: Final[float] = 0.005
RECONCILE_NOISE_Z: Final[float] = 1.0
RECONCILE_CORRECTION_Z: Final[float] = 2.5
RECONCILE_SUSPICIOUS_Z: Final[float] = 4.0
RECONCILE_REPEAT_THRESHOLD: Final[int] = 3

# -- Comparative evaluation (Section 8/9 of the Part H specification) -------- #
# EXPERIMENT: unit costs used by the research evaluator only.
EVAL_REGULATOR_COST_PER_CASE: Final[float] = 120.0
EVAL_REGULATOR_COST_PER_INVESTIGATION: Final[float] = 400.0
EVAL_MATERIALITY_THRESHOLD: Final[float] = 0.02  # True-overstatement line.

# --------------------------------------------------------------------------- #
# Part I -- red-team remediation parameters. Strictly additive; nothing
# above this line is referenced or redefined here. Classification of every
# value is stated inline (LEGAL / STYLIZATION / EXPERIMENT).
# --------------------------------------------------------------------------- #

# -- I.1 sanction-scale bridge (P0) ------------------------------------------ #
# STYLIZATION: the statutory `annual_net_turnover` (hundreds of millions
# EUR) exists in LEGAL-SCOPE units and is used ONLY for scope tests (CSRD
# thresholds, protected-undertaking lines). The simulation's monetary
# economy (balances ~ float x price) is two orders of magnitude smaller,
# so monetary sanction bases are computed on a SIMULATION-SCALE turnover
# proxy: sim_turnover = SIM_TURNOVER_BALANCE_MULTIPLE * corporate balance.
# The statutory ceiling RATES (1% experimental ordinary, 4% cross-border
# consumer, 3% CSDDD) then apply to that proxy, keeping the legal logic
# intact while making sanctions proportionate instead of confiscatory.
# The multiple itself is a stylized turnover/net-assets ratio, not an
# empirical estimate.
SIM_TURNOVER_BALANCE_MULTIPLE: Final[float] = 1.5
# EXPERIMENT: proportionality + repeat-offender escalation. A first
# offence is bounded by the track ceiling; repeat severe findings scale
# the experimental amount up to the cap multiple (never above the legal
# ceiling and never below zero).
PENALTY_REPEAT_ESCALATION_RATE: Final[float] = 0.50
PENALTY_REPEAT_ESCALATION_CAP: Final[float] = 3.0

# -- I.2 detector hardening (P1) ---------------------------------------------- #
# EXPERIMENT: self-declared uncertainty is credible only up to this
# multiple of the best evidence's standard error; beyond it the excess is
# ignored for the z-test and the implausibility is recorded as a reason.
UNCERTAINTY_PLAUSIBILITY_MULTIPLE: Final[float] = 2.0
# EXPERIMENT: rolling escalation memory for repeated one-sided
# sub-threshold findings (salami tactics). Escalates only patterns:
# at least MIN_COUNT positively-diverging low-severity findings inside
# WINDOW_DAYS whose mean standardized divergence exceeds MIN_MEAN_Z.
REPEAT_PATTERN_WINDOW_DAYS: Final[int] = 365
REPEAT_PATTERN_MIN_COUNT: Final[int] = 4
REPEAT_PATTERN_MIN_MEAN_Z: Final[float] = 0.5
# EXPERIMENT: two evidence records disagree materially when their gap
# exceeds this multiple of their combined standard error; unresolved
# cross-source conflicts route to INCONCLUSIVE, never to a sanction.
EVIDENCE_CONFLICT_Z: Final[float] = 2.0

# -- I.3 hub semantic validation (P1/P2) -------------------------------------- #
# EXPERIMENT: a qualification is meaningful only if it is at least this
# long AND mentions at least one recognised scoping token. Placeholder
# qualifications ("x") no longer satisfy any qualification-based check.
QUALIFICATION_MIN_LENGTH: Final[int] = 20
QUALIFICATION_TOKENS: Final[tuple] = (
    "boundary", "period", "scope", "uncertain", "estimate", "method",
    "basis", "coverage")

# -- I.4 discounting and horizon design (P2) ----------------------------------- #
# EXPERIMENT: annual social discount rate applied to policy costs and
# exposure-weighted harm in the comparative evaluator. Undiscounted
# accounting ledgers are always preserved separately.
SOCIAL_DISCOUNT_RATE_DEFAULT: Final[float] = 0.03

# --------------------------------------------------------------------------- #
# Part J -- paper-readiness completion. Strictly additive; nothing above
# this line is referenced or redefined here. Classification of every value
# is stated inline (LEGAL / STYLIZATION / EXPERIMENT). None of the numbers
# below has a direct empirical calibration; every one is exposed to the
# global sensitivity campaign (parameter_registry.py) unless noted.
# --------------------------------------------------------------------------- #

# -- J.1 evidence-conflict resolution procedure (Workstream C) ---------------- #
# EXPERIMENT: procedural duration of one conflict investigation after a
# capacity slot has been assigned to it (evidence re-requests, source
# queries, file review).
CONFLICT_RESOLUTION_DAYS: Final[int] = 20
# EXPERIMENT: transparent queue priority of a conflict case. Deliberately
# below whistleblower (1.0), complaint (0.95) and connector reconciliation
# (0.90): resolving a data dispute matters, but corroborated suspicion
# outranks it.
CONFLICT_PRIORITY: Final[float] = 0.85
# EXPERIMENT: if no re-verification evidence arrives within this window,
# the conflict is decided on procedural credibility alone (and can then
# only end in confirmation, a correction demand, or dismissal -- never in
# an escalation, which requires corroborated evidence).
CONFLICT_REVERIFICATION_TIMEOUT_DAYS: Final[int] = 90
# EXPERIMENT: minimum confidence margin between the independent record and
# the firm's own record for the credibility fallback to prefer one side.
CONFLICT_CREDIBILITY_MARGIN: Final[float] = 0.15
# EXPERIMENT: share of per-period investigation capacity reserved for
# queued conflict investigations (a dedicated data-dispute desk), so an
# endless stream of higher-priority enforcement cases cannot starve
# disputes forever -- and conflicts still compete for ordinary slots when
# the reserve is exhausted. 0.0 disables the reserve entirely.
CONFLICT_CAPACITY_SHARE: Final[float] = 0.20
# EXPERIMENT: stylized delay for a non-connector evidence source to answer
# a supervisory re-verification request with a fresh measurement.
SOURCE_REVERIFICATION_DELAY_DAYS: Final[int] = 30
# EXPERIMENT: relative measurement error of a commissioned third-party
# re-verification. The re-verifier is a measurement apparatus over the
# physical ledger (exactly like the firm's own meters and the connector);
# only its uncertain EvidenceRecord output reaches the supervisor.
REVERIFICATION_RELATIVE_ERROR: Final[float] = 0.02
# EXPERIMENT: research-evaluator unit cost of one conflict investigation
# (between the ordinary case cost of 120 and the formal investigation
# cost of 400 -- a data dispute needs specialist time but no litigation).
EVAL_REGULATOR_COST_PER_CONFLICT: Final[float] = 250.0
