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
MIN_COMMISSION_RATE: Final[float] = 0.0004  # Commission floor, low volume.
TOBIN_TAX_RATE: Final[float] = float(TOBIN_TAX_RATE_DEC)
MIN_TOBIN_RATE: Final[float] = 0.001        # Tobin floor in low-volume regimes.
TOBIN_HOLDING_DAYS: Final[int] = 15         # Holding threshold, Tobin tax.

# Pre-computed friction interpolation spans (hot path of update_friction).
COMMISSION_RATE_SPAN: Final[float] = BASE_COMMISSION_RATE - MIN_COMMISSION_RATE
TOBIN_RATE_SPAN: Final[float] = TOBIN_TAX_RATE - MIN_TOBIN_RATE

# --------------------------------------------------------------------------- #
# Corporate balance sheet and dividend policy.
# --------------------------------------------------------------------------- #
CORPORATE_BALANCE_FLOOR_DEC: Final[Decimal] = Decimal("50000.0")
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
ORDER_DECAY_BASE_HAZARD: Final[float] = 0.10
ORDER_DECAY_AGE_SCALE: Final[float] = 3.0
ORDER_DECAY_MAX_HAZARD: Final[float] = 0.75

# --------------------------------------------------------------------------- #
# Evolutionary review (Part A): logit choice with memory and a switch cap.
# --------------------------------------------------------------------------- #
EVOLUTION_EPOCH_DAYS: Final[int] = 90
INTENSITY_OF_CHOICE: Final[float] = 120.0  # Logit beta on smoothed returns.
STRATEGY_MEMORY: Final[float] = 0.65       # EWMA weight, past attractiveness.
LAMBDA_MEMORY: Final[float] = 1.0 - STRATEGY_MEMORY  # Complementary weight.
SWITCH_CONSIDERATION_RATE: Final[float] = 0.30  # Fraction that re-evaluates.
MAX_SWITCH_FRACTION: Final[float] = 0.05   # Cap on migration per epoch.
