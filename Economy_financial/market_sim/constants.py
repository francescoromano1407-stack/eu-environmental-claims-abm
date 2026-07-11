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
