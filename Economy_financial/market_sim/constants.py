"""
Centralized market microstructure constants.

Single source of truth for every structural parameter of the simulation:
transactional friction bounds (Part D), corporate solvency floors, LOB
order-evaporation hazard bounds (Part D), and the evolutionary review
configuration (Part A). Importing modules must reference these by name --
no magic numbers are permitted to shadow them elsewhere in the package.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Friction (Part D, fix 1): rates float between a floor and a base level
# depending on the current volume regime. Escrow accounting is pinned to the
# rate in force at order placement (stored per order).
# --------------------------------------------------------------------------- #
BASE_COMMISSION_RATE = 0.001   # Per-side commission in normal/high volume.
MIN_COMMISSION_RATE = 0.0004   # Commission floor in low-volume regimes.
TOBIN_TAX_RATE = 0.005         # Tobin tax at full activity.
MIN_TOBIN_RATE = 0.001         # Tobin floor in low-volume regimes.
TOBIN_HOLDING_DAYS = 15        # Holding period threshold for the Tobin tax.

# --------------------------------------------------------------------------- #
# Corporate balance sheet and dividend policy.
# --------------------------------------------------------------------------- #
CORPORATE_BALANCE_FLOOR = 50_000.0
BASE_DIVIDEND_PER_SHARE = 2.00

# --------------------------------------------------------------------------- #
# Order-book depth measurement.
# --------------------------------------------------------------------------- #
IMBALANCE_BAND = 0.05          # Depth-imbalance measurement band around mid.

# --------------------------------------------------------------------------- #
# LOB order evaporation (Part D, fix 2): per-day cancellation hazard grows
# with order age; expected order life ~4-5 days with a fat tail, so stale
# walls dissolve gradually instead of snapping out on a fixed TTL.
# --------------------------------------------------------------------------- #
ORDER_DECAY_BASE_HAZARD = 0.10
ORDER_DECAY_AGE_SCALE = 3.0
ORDER_DECAY_MAX_HAZARD = 0.75

# --------------------------------------------------------------------------- #
# Evolutionary review (Part A): logit choice with memory and a switch cap.
# --------------------------------------------------------------------------- #
EVOLUTION_EPOCH_DAYS = 90
INTENSITY_OF_CHOICE = 120.0    # Logit beta on smoothed epoch returns.
STRATEGY_MEMORY = 0.65         # EWMA weight on past attractiveness.
SWITCH_CONSIDERATION_RATE = 0.30  # Fraction of traders that re-evaluate.
MAX_SWITCH_FRACTION = 0.05     # Hard cap on population migrating per epoch.
