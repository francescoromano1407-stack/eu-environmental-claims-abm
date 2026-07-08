"""
market_sim -- Agent-based financial market simulation with a P2P LOB engine.

Modular package refactor of `market_simulation_opus.py`. The domain
specification (Parts A-D below) is preserved verbatim across the modules;
this docstring is the package-level architectural map.

Package layout
--------------
  constants.py   Microstructural constants: friction floors, solvency
                 floors, LOB decay hazard bounds, evolutionary epoch config.
  models.py      Data primitives: LimitOrder / MarketOrder (__slots__),
                 Asset (log-space OU fundamental), IncrementalEMA (O(1)).
  order_book.py  OrderBook: bisect-sorted price-time priority arrays,
                 O(1) best-level pops, lazy tombstone compaction, exact
                 double-entry escrow settlement under dynamic friction.
  traders.py     Behavioral agents: Trader (noise / fundamentalist /
                 chartist), MarketMaker (tanh skew, asymmetric spreads),
                 Manipulator (spoofing finite-state machine).
  simulation.py  Simulation orchestrator + CSV export pipeline.
  main.py        Entry point (`python -m market_sim.main`).

Dependency graph (acyclic, verified at runtime):

    constants  <-  models  <-  order_book
                       ^            ^ (TYPE_CHECKING only)
                       |            |
                    traders  <------+   (TYPE_CHECKING only)
                       ^
                       |
                  simulation  <-  main

Domain specification (systemic refactor, Parts A-D)
---------------------------------------------------
PART A -- Herd control: smoothed evolutionary strategy mechanism
  1. The independent 10%-probability strategy switch is replaced by a
     Discrete Choice / Logit model. Each strategy carries an exponentially
     smoothed "attractiveness" score (memory factor STRATEGY_MEMORY) built
     from its realised epoch return; migration targets are sampled from a
     softmax over these scores with intensity-of-choice INTENSITY_OF_CHOICE.
  2. Inertia: only a random SWITCH_CONSIDERATION_RATE fraction of traders
     even re-evaluate their strategy at a review, and the smoothed
     attractiveness prevents reactions to single-epoch noise.
  3. Hard cap: at most MAX_SWITCH_FRACTION (5%) of the evolutionary
     population may actually change strategy per epoch, eliminating the
     synchronised order-cancellation shocks that previously caused
     macro-scale liquidity voids and cascades.

PART B -- Dynamic information flow and elastic valuation corridors
  1. The corporate fundamental (the balance sheet backing the intrinsic
     value) is a mean-reverting Ornstein-Uhlenbeck process in log space
     around a slowly drifting anchor (GBM-like drift), updated every trading
     day. Information arrives organically instead of as rare uniform jumps.
  2. Fundamentalists use no hard 0.95/1.05 trigger walls. The mispricing is
     mapped through a Gaussian error function into a smooth trade
     probability whose width scales with current realised volatility:
     small mispricings are traded rarely and gently, large ones with rising
     conviction, and the corridor breathes with the volatility regime.
  3. The initial corporate balance is seeded from the TRUE total float
     (including the Market Maker and Manipulator inventories), so the
     simulation does not start structurally overvalued.

PART C -- Adaptive Market Maker microstructure
  1. Asymmetric, volatility-scaled spreads: the half-spread widens with
     realised relative volatility, and the side that would worsen the MM's
     inventory position widens further while the unwinding side tightens.
  2. The inventory skew is passed through tanh (smooth for small
     imbalances, saturating defensively near capacity) instead of a linear
     multiplier that over-reacted to minor deviations.
  3. The MM never abruptly drains the book: quoted sizes scale down
     smoothly near capacity instead of quotes disappearing, and after any
     mass cancellation (evolutionary review) `provide_structural_depth`
     posts temporary backstop layers wherever near-mid depth is thin.

PART D -- Fluid friction and probabilistic LOB decay
  1. Commission and Tobin tax are dynamic: they scale down toward floor
     rates during low-volume regimes (measured as short-run volume vs a
     long-run EMA baseline) so friction can no longer freeze the market.
     Escrow accounting stays exact: every resting order stores the
     commission rate at which its cash was escrowed and is settled or
     refunded at exactly that rate.
  2. The rigid ORDER_TTL_DAYS cutoff is replaced by a probabilistic
     age-increasing evaporation hazard: stale resting orders dissolve
     smoothly instead of building week-long artificial walls that all
     expire at once.

Retained legacy guarantees (all still active):
  - Dynamic shares-outstanding fundamental (no hard-coded float).
  - Persistent order book (no daily wipe); cancellation is the only
    removal path and always refunds escrow.
  - Solvency-constrained dividends (corporate balance floor, no printing).
  - Strategy switches recorded via `strategy_history`; canonical trader_id
    immutable; open orders cancelled on switch.
  - MM and Manipulators are full macro participants (dividends, interest).
  - O(1) incremental EMAs; bisect-maintained sorted books with lazy
    tombstone cancellation and periodic compaction.
  - Manipulator (spoofer / momentum-igniter) finite-state machine.

Author: Antigravity (refactored)
Date: July 2026
"""

from __future__ import annotations

from market_sim.models import Asset, IncrementalEMA, LimitOrder, MarketOrder
from market_sim.order_book import OrderBook
from market_sim.simulation import Simulation, export_simulation_metrics
from market_sim.traders import Manipulator, MarketMaker, Trader

__all__ = [
    "Asset",
    "IncrementalEMA",
    "LimitOrder",
    "Manipulator",
    "MarketMaker",
    "MarketOrder",
    "OrderBook",
    "Simulation",
    "Trader",
    "export_simulation_metrics",
]

__version__ = "1.0.0"
