"""
Financial Market Simulation with a Peer-to-Peer Limit Order Book (LOB) Engine.

Systemic refactor. Changes relative to the previous revision:

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
     value) is now a mean-reverting Ornstein-Uhlenbeck process in log space
     around a slowly drifting anchor (GBM-like drift), updated every trading
     day. Information arrives organically instead of as rare uniform jumps.
  2. Fundamentalists no longer use hard 0.95/1.05 trigger walls. The
     mispricing is mapped through a Gaussian error function into a smooth
     trade probability whose width scales with current realised volatility:
     small mispricings are traded rarely and gently, large ones with rising
     conviction, and the corridor breathes with the volatility regime.
  3. The initial corporate balance is seeded from the TRUE total float
     (including the Market Maker and Manipulator inventories), so the
     simulation no longer starts structurally overvalued -- previously the
     fundamental was ~42 while the price was 100, manufacturing a crash.

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

Retained from the previous revision (all still active):
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

import bisect
import collections
import csv
import math
import random
import statistics
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# --------------------------------------------------------------------------- #
# Global market microstructure constants
# --------------------------------------------------------------------------- #
# Friction (Part D, fix 1): rates float between a floor and a base level
# depending on the current volume regime. Escrow accounting is pinned to the
# rate in force at order placement (stored per order).
BASE_COMMISSION_RATE = 0.001   # Per-side commission in normal/high volume.
MIN_COMMISSION_RATE = 0.0004   # Commission floor in low-volume regimes.
TOBIN_TAX_RATE = 0.005         # Tobin tax at full activity.
MIN_TOBIN_RATE = 0.001         # Tobin floor in low-volume regimes.
TOBIN_HOLDING_DAYS = 15        # Holding period threshold for the Tobin tax.

CORPORATE_BALANCE_FLOOR = 50_000.0
BASE_DIVIDEND_PER_SHARE = 2.00
IMBALANCE_BAND = 0.05          # Depth-imbalance measurement band around mid.

# LOB order evaporation (Part D, fix 2): per-day cancellation hazard grows
# with order age; expected order life ~4-5 days with a fat tail, so stale
# walls dissolve gradually instead of snapping out on a fixed TTL.
ORDER_DECAY_BASE_HAZARD = 0.10
ORDER_DECAY_AGE_SCALE = 3.0
ORDER_DECAY_MAX_HAZARD = 0.75

# Evolutionary review (Part A): logit choice with memory and a switch cap.
EVOLUTION_EPOCH_DAYS = 90
INTENSITY_OF_CHOICE = 120.0    # Logit beta on smoothed epoch returns.
STRATEGY_MEMORY = 0.65         # EWMA weight on past attractiveness.
SWITCH_CONSIDERATION_RATE = 0.30  # Fraction of traders that re-evaluate.
MAX_SWITCH_FRACTION = 0.05     # Hard cap on population migrating per epoch.


class LimitOrder:
    """A resting limit order in the book."""

    __slots__ = ("order_id", "trader_id", "side", "price", "quantity",
                 "timestamp", "active", "escrow_rate")

    def __init__(self, order_id: int, trader_id: str, side: str,
                 price: float, quantity: int, timestamp: int):
        self.order_id = order_id
        self.trader_id = trader_id
        self.side = side.upper()          # 'BUY' or 'SELL'
        self.price = float(price)
        self.quantity = int(quantity)
        self.timestamp = timestamp        # Placement day (price-time priority)
        self.active = True                # False once filled or cancelled
        # Commission rate at which cash was escrowed when the order rested.
        # Settlements and refunds use exactly this rate (Part D, fix 1), so
        # dynamic friction can never create or destroy escrowed cash.
        self.escrow_rate = BASE_COMMISSION_RATE

    def __repr__(self) -> str:
        return (f"LimitOrder(id={self.order_id}, trader={self.trader_id}, "
                f"side={self.side}, price={self.price:.2f}, "
                f"qty={self.quantity}, ts={self.timestamp})")


class MarketOrder:
    """An immediate-or-cancel market order."""

    __slots__ = ("trader_id", "side", "quantity")

    def __init__(self, trader_id: str, side: str, quantity: int):
        self.trader_id = trader_id
        self.side = side.upper()
        self.quantity = int(quantity)

    def __repr__(self) -> str:
        return (f"MarketOrder(trader={self.trader_id}, side={self.side}, "
                f"qty={self.quantity})")


class Asset:
    """
    The traded asset, with corporate balance-sheet tracking.

    Part B, fix 1: the balance is a log-space Ornstein-Uhlenbeck process
    reverting to a slowly drifting anchor:

        anchor_t = anchor_{t-1} + mu                    (GBM-like drift)
        log B_t  = log B_{t-1}
                   + theta * (anchor_t - log B_{t-1})   (mean reversion)
                   + sigma * N(0, 1)                    (information arrival)

    Dividends deduct from the balance; the reversion toward the anchor
    models retained earnings rebuilding the balance sheet organically.
    """

    def __init__(self, symbol: str, initial_price: float = 100.0,
                 initial_balance: float = 300_000.0,
                 fundamental_drift: float = 0.00010,
                 fundamental_reversion: float = 0.015,
                 fundamental_vol: float = 0.005):
        self.symbol = symbol
        self.price_history = [initial_price]
        self.balance_history = [initial_balance]
        self.balance = initial_balance
        self.fundamental_drift = fundamental_drift
        self.fundamental_reversion = fundamental_reversion
        self.fundamental_vol = fundamental_vol
        self._log_anchor = math.log(max(initial_balance,
                                        CORPORATE_BALANCE_FLOOR))

    def record_close(self, price: float) -> None:
        """Appends the daily closing price."""
        self.price_history.append(price)

    def update_daily_fundamental(self) -> None:
        """One OU step of the balance-sheet information process (Part B)."""
        self._log_anchor += self.fundamental_drift
        log_b = math.log(max(self.balance, CORPORATE_BALANCE_FLOOR))
        log_b += self.fundamental_reversion * (self._log_anchor - log_b)
        log_b += random.gauss(0.0, self.fundamental_vol)
        self.balance = max(math.exp(log_b), CORPORATE_BALANCE_FLOOR)
        self.balance_history.append(self.balance)

    def get_last_price(self) -> float:
        """Returns the most recent closing price."""
        return self.price_history[-1]


class IncrementalEMA:
    """
    O(1) incremental exponential moving average.

    Stores only the previous EMA value and an observation counter; one
    `update()` per observation replaces any O(N) history re-scan.
    """

    def __init__(self, period: int):
        self.alpha = 2.0 / (period + 1.0)
        self.value: Optional[float] = None
        self.count = 0

    def update(self, price: float) -> float:
        """Folds a new observation into the EMA in constant time."""
        if self.value is None:
            self.value = price
        else:
            self.value = price * self.alpha + self.value * (1.0 - self.alpha)
        self.count += 1
        return self.value


# --------------------------------------------------------------------------- #
# Traders
# --------------------------------------------------------------------------- #
class Trader:
    """A market participant with cash, shares, and a trading strategy."""

    # Part B, fix 2: elastic fundamentalist corridor parameters. The
    # half-width of the "fair" corridor is base + scale * realised relative
    # volatility, capped; mispricing is mapped through erf() into a smooth
    # trade probability instead of a hard 5% trigger wall.
    FUND_BAND_BASE = 0.02
    FUND_BAND_VOL_SCALE = 1.5
    FUND_BAND_MAX = 0.12

    # Chartist dead zone: EMA crossovers inside this band are ignored,
    # damping momentum churn on microscopic signals.
    CHARTIST_DEADZONE = 0.002

    def __init__(self, trader_id: str, cash: float, shares: int,
                 trader_type: str, current_day: int = 0):
        self.trader_id = trader_id            # Immutable canonical id (map key)
        self.cash = float(cash)
        self.cash_reserved = 0.0              # Cash escrowed in resting bids
        self.shares = int(shares)
        self.shares_reserved = 0              # Shares escrowed in resting asks
        self.type = trader_type
        # Every strategy change is recorded so logs reflect the trader's
        # *current* behaviour without mutating the dict key that resting
        # orders in the book still reference.
        self.strategy_history = [(current_day, trader_type)]

        # FIFO ledger of (purchase_day, quantity, purchase_price) lots,
        # used for the holding-period Tobin tax.
        self.shares_ledger: collections.deque = collections.deque()
        if self.shares > 0:
            self.shares_ledger.append((current_day, self.shares, 100.0))

        self.active_orders: set[int] = set()  # Resting order ids in the book

    # -- identity ---------------------------------------------------------- #
    @property
    def label(self) -> str:
        """Log-friendly id whose prefix always reflects the current strategy."""
        return f"{self.trader_id}[{self.type}]"

    def switch_strategy(self, new_type: str, day: int,
                        order_book: "OrderBook", trader_map: dict) -> None:
        """
        Switches strategy, records it, and cancels all open orders (they
        were priced under the old strategy's logic).
        """
        if new_type == self.type:
            return
        for oid in list(self.active_orders):
            order_book.cancel_order(oid, trader_map)
        self.type = new_type
        self.strategy_history.append((day, new_type))

    # -- accounting -------------------------------------------------------- #
    @property
    def total_cash(self) -> float:
        return self.cash + self.cash_reserved

    @property
    def total_shares(self) -> int:
        return self.shares + self.shares_reserved

    def get_wealth(self, current_price: float) -> float:
        """Mark-to-market wealth: all cash plus all shares at current price."""
        return self.total_cash + self.total_shares * current_price

    # -- decision logic ---------------------------------------------------- #
    def decide_order(self, current_price: float, v_fundamental: float,
                     ema_fast: float, ema_slow: float, ema_ready: bool,
                     book_imbalance: float,
                     rel_volatility: float) -> Optional[tuple]:
        """
        Returns (order_type, side, price, quantity) or None.

        `book_imbalance` in [-1, 1] is the depth imbalance near the mid
        (the surface the Manipulator's spoof orders exploit).
        `rel_volatility` is the realised relative volatility of recent
        closes, which stretches the fundamentalist corridor (Part B).
        """
        if self.type == 'noise':
            return self._decide_noise(current_price, book_imbalance)
        if self.type == 'fundamentalist':
            return self._decide_fundamentalist(current_price, v_fundamental,
                                               rel_volatility)
        if self.type == 'chartist':
            return self._decide_chartist(current_price, ema_fast, ema_slow,
                                         ema_ready, book_imbalance)
        return None

    def _decide_noise(self, current_price: float,
                      imbalance: float) -> Optional[tuple]:
        """Random trader, mildly herding on visible book pressure."""
        buy_p = 0.25 + 0.15 * imbalance
        sell_p = 0.25 - 0.15 * imbalance
        roll = random.random()
        if roll < buy_p:
            action = 'BUY'
        elif roll < buy_p + sell_p:
            action = 'SELL'
        else:
            return None

        qty = random.randint(1, 5)
        if random.random() < 0.3:
            return ('MARKET', action, None, qty)
        price = current_price * (1.0 + random.normalvariate(0.0, 0.02))
        return ('LIMIT', action, max(0.01, round(price, 2)), qty)

    def _decide_fundamentalist(self, current_price: float,
                               v_fundamental: float,
                               rel_volatility: float) -> Optional[tuple]:
        """
        Part B, fix 2: elastic probabilistic corridor.

        The relative mispricing m = (V - P) / V is compared with a corridor
        half-width that breathes with realised volatility. The probability
        of acting is erf(|m| / (band * sqrt(2))) -- a smooth ogive: ~0
        inside the corridor, rising continuously outside it. Order size and
        aggression (market-order share) also scale with conviction, so the
        fundamentalist force is proportional to the distortion instead of
        an all-or-nothing wall at +/-5%.
        """
        if v_fundamental <= 0.0 or current_price <= 0.0:
            return None

        mispricing = (v_fundamental - current_price) / v_fundamental
        band = min(self.FUND_BAND_MAX,
                   self.FUND_BAND_BASE
                   + self.FUND_BAND_VOL_SCALE * rel_volatility)
        conviction = math.erf(abs(mispricing) / (band * math.sqrt(2.0)))
        if random.random() >= conviction:
            return None

        severity = min(1.0, abs(mispricing) / (2.0 * band))
        qty = random.randint(1, 5) + int(3.0 * severity)
        p_market = 0.15 + 0.20 * severity

        if mispricing > 0.0:  # Undervalued -> accumulate.
            if random.random() < p_market:
                return ('MARKET', 'BUY', None, qty)
            # Passive target between the market and fair value; never chase
            # more than half a band above the current price in one order.
            limit = min(v_fundamental * (1.0 - random.uniform(0.1, 0.5) * band),
                        current_price * (1.0 + 0.5 * band))
            return ('LIMIT', 'BUY', max(0.01, round(limit, 2)), qty)

        # Overvalued -> distribute.
        if random.random() < p_market:
            return ('MARKET', 'SELL', None, qty)
        limit = max(v_fundamental * (1.0 + random.uniform(0.1, 0.5) * band),
                    current_price * (1.0 - 0.5 * band))
        return ('LIMIT', 'SELL', max(0.01, round(limit, 2)), qty)

    def _decide_chartist(self, current_price: float, ema_fast: float,
                         ema_slow: float, ema_ready: bool,
                         imbalance: float) -> Optional[tuple]:
        """
        EMA-crossover momentum trader (EMAs arrive precomputed in O(1)).
        A small imbalance tilt keeps chartists susceptible to spoofed depth;
        a dead zone suppresses churn on microscopic crossovers.
        """
        if not ema_ready:
            # Warm-up: behave like a noise trader for the first 15 closes.
            action = random.choice(['BUY', 'SELL', 'HOLD'])
            if action == 'HOLD':
                return None
            qty = random.randint(1, 5)
            price = current_price * (1.0 + random.normalvariate(0.0, 0.02))
            return ('LIMIT', action, max(0.01, round(price, 2)), qty)

        signal = (ema_fast - ema_slow) / ema_slow + 0.01 * imbalance
        if abs(signal) < self.CHARTIST_DEADZONE:
            return None
        qty = random.randint(1, 5)
        if signal > 0.0:
            if random.random() < 0.3:
                return ('MARKET', 'BUY', None, qty)
            price = current_price * (1.0 + random.uniform(0.005, 0.02))
            return ('LIMIT', 'BUY', max(0.01, round(price, 2)), qty)
        if random.random() < 0.3:
            return ('MARKET', 'SELL', None, qty)
        price = current_price * (1.0 - random.uniform(0.005, 0.02))
        return ('LIMIT', 'SELL', max(0.01, round(price, 2)), qty)

    def __repr__(self) -> str:
        return (f"Trader(id={self.label}, cash={self.cash:.2f}, "
                f"reserved_c={self.cash_reserved:.2f}, shares={self.shares}, "
                f"reserved_s={self.shares_reserved})")


# --------------------------------------------------------------------------- #
# Order book (bisect-maintained sorted books, lazy cancels, dynamic friction)
# --------------------------------------------------------------------------- #
class OrderBook:
    """
    P2P limit order book with price-time priority.

    Internal layout: each side is a list of `(sort_key, order)` tuples kept
    permanently sorted with `bisect.insort` -- O(log n) binary search plus a
    C-level memmove. Keys are constructed so the *best* order sits at the
    END of the list, making best-level access and fills an O(1) `pop()`:

        bids: key = ( price, -timestamp, -order_id)  -> best bid last
        asks: key = (-price, -timestamp, -order_id)  -> best ask last

    The `-order_id` term guarantees key uniqueness, so tuple comparison
    never falls through to comparing LimitOrder objects.

    Cancellations are O(1) and lazy: the order is tombstoned
    (`active = False`), refunded immediately, and physically removed only
    when it surfaces at the top of the book or during periodic compaction.

    Part D, fix 1 -- dynamic friction with exact escrow accounting:
    `commission_rate` and `tobin_rate` are set daily by the Simulation.
    Takers pay the rate in force at execution. Makers' cash escrow is taken
    at the rate in force at placement, which is stored on the order
    (`escrow_rate`) and used verbatim for both settlement and refund, so no
    cash can appear or vanish when the rate moves while an order rests.
    """

    COMPACT_THRESHOLD = 256

    def __init__(self):
        self._bids: list[tuple] = []
        self._asks: list[tuple] = []
        self.orders: dict[int, LimitOrder] = {}   # Active orders by id
        self._dead = 0                            # Tombstones awaiting sweep
        self.order_id_counter = 0
        self.commission_rate = BASE_COMMISSION_RATE
        self.tobin_rate = TOBIN_TAX_RATE

    # -- friction ------------------------------------------------------------#
    def set_friction(self, commission_rate: float, tobin_rate: float) -> None:
        """Updates taker-side friction; resting escrows keep their own rate."""
        self.commission_rate = commission_rate
        self.tobin_rate = tobin_rate

    # -- id / key helpers --------------------------------------------------- #
    def get_next_order_id(self) -> int:
        self.order_id_counter += 1
        return self.order_id_counter

    @staticmethod
    def _bid_key(order: LimitOrder) -> tuple:
        return (order.price, -order.timestamp, -order.order_id)

    @staticmethod
    def _ask_key(order: LimitOrder) -> tuple:
        return (-order.price, -order.timestamp, -order.order_id)

    # -- best-level access (lazy tombstone skimming) ------------------------ #
    def best_bid(self) -> Optional[LimitOrder]:
        while self._bids:
            order = self._bids[-1][1]
            if order.active and order.quantity > 0:
                return order
            self._bids.pop()
            self._dead = max(0, self._dead - 1)
        return None

    def best_ask(self) -> Optional[LimitOrder]:
        while self._asks:
            order = self._asks[-1][1]
            if order.active and order.quantity > 0:
                return order
            self._asks.pop()
            self._dead = max(0, self._dead - 1)
        return None

    def get_midpoint(self, default_price: float) -> float:
        bid, ask = self.best_bid(), self.best_ask()
        if bid and ask:
            return (bid.price + ask.price) / 2.0
        if bid:
            return bid.price
        if ask:
            return ask.price
        return default_price

    # -- depth inspection (used by the Manipulator, imbalance, MM backstop) - #
    def depth_within(self, side: str, mid: float, band: float,
                     exclude_trader: Optional[str] = None) -> int:
        """Total active quantity on one side within `band` of the mid."""
        total = 0
        if side == 'BUY':
            floor_price = mid * (1.0 - band)
            for _, order in reversed(self._bids):
                if not order.active:
                    continue
                if order.price < floor_price:
                    break
                if order.trader_id != exclude_trader:
                    total += order.quantity
        else:
            cap_price = mid * (1.0 + band)
            for _, order in reversed(self._asks):
                if not order.active:
                    continue
                if order.price > cap_price:
                    break
                if order.trader_id != exclude_trader:
                    total += order.quantity
        return total

    def get_imbalance(self, mid: float, band: float = IMBALANCE_BAND,
                      exclude_trader: Optional[str] = None) -> float:
        """Depth imbalance in [-1, 1]: >0 means bid-heavy (buy pressure)."""
        bid_qty = self.depth_within('BUY', mid, band, exclude_trader)
        ask_qty = self.depth_within('SELL', mid, band, exclude_trader)
        total = bid_qty + ask_qty
        if total == 0:
            return 0.0
        return (bid_qty - ask_qty) / total

    # -- cancellation (O(1); this remains the ONLY removal path) ------------ #
    def cancel_order(self, order_id: int, trader_map: dict) -> bool:
        """Cancels a resting order and refunds its escrow. O(1)."""
        order = self.orders.get(order_id)
        if order is None or not order.active:
            return False

        trader = trader_map[order.trader_id]
        if order.side == 'BUY':
            refund = order.price * order.quantity * (1.0 + order.escrow_rate)
            refund = min(refund, trader.cash_reserved)  # numeric safety
            trader.cash_reserved -= refund
            trader.cash += refund
        else:
            trader.shares_reserved -= order.quantity
            trader.shares += order.quantity

        trader.active_orders.discard(order_id)
        order.active = False
        del self.orders[order_id]
        self._dead += 1
        if self._dead > self.COMPACT_THRESHOLD:
            self._compact()
        return True

    def _compact(self) -> None:
        """Physically sweeps tombstoned entries out of both books."""
        self._bids = [e for e in self._bids if e[1].active]
        self._asks = [e for e in self._asks if e[1].active]
        self._dead = 0

    # -- fills --------------------------------------------------------------#
    def _retire_top(self, side: str, trader_map: dict) -> None:
        """Removes a fully filled order sitting at the top of the book."""
        entries = self._bids if side == 'BUY' else self._asks
        _, order = entries.pop()
        order.active = False
        self.orders.pop(order.order_id, None)
        trader_map[order.trader_id].active_orders.discard(order.order_id)

    # -- order entry --------------------------------------------------------#
    def add_limit_order(self, order: LimitOrder, trader_map: dict,
                        current_day: int) -> list:
        """
        Places a limit order; matches immediately while it crosses, then
        rests the remainder with funds/shares escrowed. Returns a list of
        (day, price, qty) execution tuples.
        """
        trades = []

        if order.side == 'BUY':
            while order.quantity > 0:
                best = self.best_ask()
                if best is None or order.price < best.price:
                    break
                trade_price = best.price            # Maker's price
                trade_qty = min(order.quantity, best.quantity)
                self.execute_trade(order.trader_id, best.trader_id,
                                   trade_price, trade_qty, current_day,
                                   trader_map, buyer_is_maker=False,
                                   seller_is_maker=True, maker_order=best)
                trades.append((current_day, trade_price, trade_qty))
                order.quantity -= trade_qty
                best.quantity -= trade_qty
                if best.quantity == 0:
                    self._retire_top('SELL', trader_map)

            if order.quantity > 0:
                buyer = trader_map[order.trader_id]
                order.escrow_rate = self.commission_rate
                escrow = order.price * order.quantity \
                    * (1.0 + order.escrow_rate)
                buyer.cash -= escrow
                buyer.cash_reserved += escrow
                bisect.insort(self._bids, (self._bid_key(order), order))
                self.orders[order.order_id] = order
                buyer.active_orders.add(order.order_id)

        else:  # SELL
            while order.quantity > 0:
                best = self.best_bid()
                if best is None or order.price > best.price:
                    break
                trade_price = best.price
                trade_qty = min(order.quantity, best.quantity)
                self.execute_trade(best.trader_id, order.trader_id,
                                   trade_price, trade_qty, current_day,
                                   trader_map, buyer_is_maker=True,
                                   seller_is_maker=False, maker_order=best)
                trades.append((current_day, trade_price, trade_qty))
                order.quantity -= trade_qty
                best.quantity -= trade_qty
                if best.quantity == 0:
                    self._retire_top('BUY', trader_map)

            if order.quantity > 0:
                seller = trader_map[order.trader_id]
                seller.shares -= order.quantity
                seller.shares_reserved += order.quantity
                bisect.insort(self._asks, (self._ask_key(order), order))
                self.orders[order.order_id] = order
                seller.active_orders.add(order.order_id)

        return trades

    def execute_market_order(self, order: MarketOrder, trader_map: dict,
                             current_day: int) -> list:
        """Sweeps resting liquidity; any unfilled remainder expires."""
        trades = []

        if order.side == 'BUY':
            buyer = trader_map[order.trader_id]
            while order.quantity > 0:
                best = self.best_ask()
                if best is None:
                    break
                trade_price = best.price
                trade_qty = min(order.quantity, best.quantity)
                cost_per_share = trade_price * (1.0 + self.commission_rate)
                if buyer.cash < trade_qty * cost_per_share:
                    trade_qty = int(buyer.cash // cost_per_share)
                    if trade_qty == 0:
                        break
                self.execute_trade(order.trader_id, best.trader_id,
                                   trade_price, trade_qty, current_day,
                                   trader_map, buyer_is_maker=False,
                                   seller_is_maker=True, maker_order=best)
                trades.append((current_day, trade_price, trade_qty))
                order.quantity -= trade_qty
                best.quantity -= trade_qty
                if best.quantity == 0:
                    self._retire_top('SELL', trader_map)

        else:  # SELL
            while order.quantity > 0:
                best = self.best_bid()
                if best is None:
                    break
                trade_price = best.price
                trade_qty = min(order.quantity, best.quantity)
                self.execute_trade(best.trader_id, order.trader_id,
                                   trade_price, trade_qty, current_day,
                                   trader_map, buyer_is_maker=True,
                                   seller_is_maker=False, maker_order=best)
                trades.append((current_day, trade_price, trade_qty))
                order.quantity -= trade_qty
                best.quantity -= trade_qty
                if best.quantity == 0:
                    self._retire_top('BUY', trader_map)

        return trades

    # -- settlement ----------------------------------------------------------#
    def execute_trade(self, buyer_id: str, seller_id: str, price: float,
                      qty: int, current_day: int, trader_map: dict,
                      buyer_is_maker: bool, seller_is_maker: bool,
                      maker_order: Optional[LimitOrder] = None) -> None:
        """
        Double-entry settlement: cash, shares, commissions, Tobin tax.

        A maker-buyer settles out of escrow at the exact rate stored on the
        resting order (`maker_order.escrow_rate`); takers pay the current
        dynamic commission. Absolute conservation holds either way.
        """
        buyer = trader_map[buyer_id]
        seller = trader_map[seller_id]

        trade_value = price * qty
        seller_commission = trade_value * self.commission_rate

        # FIFO holding-period Tobin tax on the seller (dynamic rate).
        tobin_tax = 0.0
        remaining = qty
        while remaining > 0 and seller.shares_ledger:
            p_day, p_qty, p_price = seller.shares_ledger.popleft()
            taxed_qty = min(remaining, p_qty)
            if current_day - p_day < TOBIN_HOLDING_DAYS:
                tobin_tax += self.tobin_rate * price * taxed_qty
            if p_qty > remaining:
                seller.shares_ledger.appendleft(
                    (p_day, p_qty - remaining, p_price))
            remaining -= taxed_qty

        # Buyer side.
        if buyer_is_maker:
            # Cash was escrowed at the resting bid's price == trade price,
            # at the commission rate frozen on the order at placement.
            rate = maker_order.escrow_rate if maker_order is not None \
                else BASE_COMMISSION_RATE
            buyer.cash_reserved -= price * qty * (1.0 + rate)
        else:
            buyer.cash -= trade_value * (1.0 + self.commission_rate)
        buyer.shares += qty
        buyer.shares_ledger.append((current_day, qty, price))

        # Seller side.
        if seller_is_maker:
            seller.shares_reserved -= qty
        else:
            seller.shares -= qty
        seller.cash += trade_value - seller_commission - tobin_tax


# --------------------------------------------------------------------------- #
# Part C: adaptive Market Maker (tanh skew, asymmetric vol-scaled spreads)
# --------------------------------------------------------------------------- #
class MarketMaker(Trader):
    """
    Inventory-aware market maker with smooth, saturating risk controls.

    Skew (Part C, fix 2): the reservation price is shifted by

        skew = max_skew_frac * tanh(inventory_deviation / inv_soft_scale)

    -- near-linear and gentle for small imbalances, saturating defensively
    as the inventory approaches its soft capacity, so minor deviations no
    longer trigger violent quote displacement.

    Spread (Part C, fix 1): the half-spread is mid * (base + k * rel_vol),
    widening in high-volatility regimes to absorb shocks. It is asymmetric:
    the side whose fill would worsen the inventory position widens with
    inventory stress while the unwinding side tightens, steering flow to
    rebalance the book instead of abruptly pulling quotes.

    Depth continuity (Part C, fix 3): quoted sizes scale smoothly with
    stress (never to zero while solvent), and `provide_structural_depth`
    posts temporary backstop layers whenever near-mid depth is thin --
    e.g. right after an evolutionary review mass-cancels resting orders.
    """

    def __init__(self, trader_id: str, cash: float, shares: int,
                 target_inventory: int, level_qty: int = 15,
                 num_levels: int = 5, base_half_spread: float = 0.004,
                 vol_sensitivity: float = 0.9, max_skew_frac: float = 0.012,
                 inv_soft_scale: Optional[int] = None,
                 asym_widen: float = 1.5, level_step: float = 0.004,
                 backstop_qty: Optional[int] = None,
                 backstop_min_depth: Optional[int] = None):
        super().__init__(trader_id, cash, shares, trader_type='market_maker')
        self.target_inventory = target_inventory
        self.level_qty = level_qty
        self.num_levels = num_levels
        self.base_half_spread = base_half_spread
        self.vol_sensitivity = vol_sensitivity
        self.max_skew_frac = max_skew_frac
        self.inv_soft_scale = inv_soft_scale if inv_soft_scale is not None \
            else max(1, int(target_inventory * 0.30))
        self.asym_widen = asym_widen
        self.level_step = level_step
        self.backstop_qty = backstop_qty if backstop_qty is not None \
            else level_qty * 3
        self.backstop_min_depth = backstop_min_depth \
            if backstop_min_depth is not None else level_qty * 2
        self.initial_wealth = cash + shares * 100.0

    # -- risk state ----------------------------------------------------------#
    def _inventory_stress(self) -> float:
        """Signed inventory stress in (-1, 1): >0 long, saturating (tanh)."""
        deviation = self.total_shares - self.target_inventory
        return math.tanh(deviation / self.inv_soft_scale)

    def _place_own_limit(self, side: str, price: float, qty: int,
                         order_book: "OrderBook", trader_map: dict,
                         current_day: int) -> None:
        """Solvency-checked helper to post one of the MM's own quotes."""
        if qty <= 0 or price < 0.01:
            return
        if side == 'BUY':
            per_share = price * (1.0 + order_book.commission_rate)
            affordable = int(self.cash // per_share)
            qty = min(qty, affordable)
        else:
            qty = min(qty, self.shares)
        if qty <= 0:
            return
        oid = order_book.get_next_order_id()
        order_book.add_limit_order(
            LimitOrder(oid, self.trader_id, side, price, qty, current_day),
            trader_map, current_day)

    # -- quoting -------------------------------------------------------------#
    def place_quotes(self, mid: float, rel_volatility: float,
                     order_book: "OrderBook", trader_map: dict,
                     current_day: int) -> None:
        """Cancels stale quotes, recomputes skew/spread, re-quotes the ladder."""
        # Refresh: cancel our own resting quotes before re-quoting.
        for oid in list(self.active_orders):
            order_book.cancel_order(oid, trader_map)

        stress = self._inventory_stress()
        s = abs(stress)

        # Smooth tanh skew: long inventory shifts the reservation price
        # down (offload shares, deter buying); short inventory shifts it up.
        reservation = mid * (1.0 - self.max_skew_frac * stress)

        # Volatility-scaled base half-spread (widens in stressed regimes).
        half = max(mid * (self.base_half_spread
                          + self.vol_sensitivity * rel_volatility), 0.01)

        # Asymmetry: widen the risk-increasing side, tighten the unwinding
        # side, and shade the quoted sizes the same way -- but never drop a
        # side entirely while solvent (no instantaneous liquidity voids).
        if stress > 0.0:      # Too long: discourage buying, encourage selling.
            bid_half = half * (1.0 + self.asym_widen * s)
            ask_half = half * max(0.45, 1.0 - 0.35 * s)
            bid_scale = max(0.3, 1.0 - 0.7 * s)
            ask_scale = 1.0 + 0.5 * s
        elif stress < 0.0:    # Too short: mirror image.
            bid_half = half * max(0.45, 1.0 - 0.35 * s)
            ask_half = half * (1.0 + self.asym_widen * s)
            bid_scale = 1.0 + 0.5 * s
            ask_scale = max(0.3, 1.0 - 0.7 * s)
        else:
            bid_half = ask_half = half
            bid_scale = ask_scale = 1.0

        for i in range(self.num_levels):
            step = mid * self.level_step * i
            bid_price = max(0.01, round(reservation - bid_half - step, 2))
            ask_price = round(reservation + ask_half + step, 2)
            ask_price = max(ask_price, bid_price + 0.01)

            self._place_own_limit(
                'BUY', bid_price, max(1, int(self.level_qty * bid_scale)),
                order_book, trader_map, current_day)
            self._place_own_limit(
                'SELL', ask_price, max(1, int(self.level_qty * ask_scale)),
                order_book, trader_map, current_day)

    def provide_structural_depth(self, mid: float, order_book: "OrderBook",
                                 trader_map: dict, current_day: int,
                                 band: float = 0.03) -> None:
        """
        Part C, fix 3: emergency depth provisioning. Called after any event
        that mass-cancels resting orders (e.g. an evolutionary review).
        Wherever total near-mid depth is below `backstop_min_depth`, the MM
        posts wide temporary layers so a single market order cannot gap the
        price through an empty book. These quotes live only until the next
        `place_quotes` refresh cancels and replaces them.
        """
        if order_book.depth_within('BUY', mid, band) < self.backstop_min_depth:
            for offset in (0.015, 0.03):
                price = max(0.01, round(mid * (1.0 - offset), 2))
                self._place_own_limit('BUY', price, self.backstop_qty,
                                      order_book, trader_map, current_day)
        if order_book.depth_within('SELL', mid, band) < self.backstop_min_depth:
            for offset in (0.015, 0.03):
                price = round(mid * (1.0 + offset), 2)
                self._place_own_limit('SELL', price, self.backstop_qty,
                                      order_book, trader_map, current_day)


# --------------------------------------------------------------------------- #
# Manipulator (spoofer / momentum-igniter)
# --------------------------------------------------------------------------- #
class Manipulator(Trader):
    """
    Stateful spoofer. A small finite-state machine per cycle:

      IDLE   -> read imbalance; if the book is thin/lopsided, plant a large
                spoof order deep on one side to fake pressure. -> SPOOFING
      SPOOFING -> wait for the mid to drift in the intended direction. On
                success: cancel the spoof and fire a market order the OTHER
                way to harvest the momentum, then cool down. If a spoof
                order gets partially hit (or evaporates via LOB decay), or
                the move stalls past a timeout, cancel and abort. -> IDLE

    Spoof orders are planted ~`spoof_offset` away from the mid so they add
    visible depth (moving the imbalance that noise/chartists react to)
    without being marketable, and are pulled before they can be filled.
    """

    STATE_IDLE = 0
    STATE_SPOOFING = 1

    def __init__(self, trader_id: str, cash: float, shares: int,
                 spoof_size: int = 400, spoof_offset: float = 0.03,
                 attack_size: int = 40, cooldown: int = 6,
                 patience: int = 3, current_day: int = 0):
        super().__init__(trader_id, cash, shares,
                         trader_type='manipulator', current_day=current_day)
        self.spoof_size = spoof_size
        self.spoof_offset = spoof_offset
        self.attack_size = attack_size
        self.cooldown = cooldown
        self.patience = patience

        self.state = self.STATE_IDLE
        self.spoof_side: Optional[str] = None      # Side of the fake pressure
        self.spoof_order_id: Optional[int] = None
        self.spoof_started_day = 0
        self.mid_at_spoof = 0.0
        self.next_active_day = 0

    def _spoof_order_alive(self, order_book: "OrderBook") -> bool:
        if self.spoof_order_id is None:
            return False
        order = order_book.orders.get(self.spoof_order_id)
        return order is not None and order.active

    def _cancel_spoof(self, order_book: "OrderBook", trader_map: dict) -> None:
        if self.spoof_order_id is not None:
            order_book.cancel_order(self.spoof_order_id, trader_map)
        self.spoof_order_id = None
        self.spoof_side = None

    def act(self, mid: float, order_book: "OrderBook", trader_map: dict,
            current_day: int) -> None:
        """Advances the manipulation state machine by one trading day."""
        if current_day < self.next_active_day:
            return

        if self.state == self.STATE_IDLE:
            self._try_start_spoof(mid, order_book, trader_map, current_day)
        elif self.state == self.STATE_SPOOFING:
            self._manage_spoof(mid, order_book, trader_map, current_day)

    def _try_start_spoof(self, mid: float, order_book: "OrderBook",
                         trader_map: dict, current_day: int) -> None:
        # Read imbalance excluding our own resting orders.
        imbalance = order_book.get_imbalance(mid, exclude_trader=self.trader_id)

        # Spoof to *reinforce and exaggerate* the thinner side's opposite:
        # plant a big BID (fake buy pressure) when we intend to sell into the
        # induced rally, and vice-versa. Bias toward whichever side we can
        # actually monetise given current holdings.
        if imbalance <= 0.1 and self.cash > mid * self.spoof_size:
            self.spoof_side = 'BUY'          # fake buying pressure -> price up
        elif imbalance >= -0.1 and self.total_shares >= self.attack_size:
            self.spoof_side = 'SELL'         # fake selling pressure -> price down
        else:
            return

        if self.spoof_side == 'BUY':
            price = max(0.01, round(mid * (1.0 - self.spoof_offset), 2))
        else:
            price = max(0.01, round(mid * (1.0 + self.spoof_offset), 2))

        oid = order_book.get_next_order_id()
        order = LimitOrder(oid, self.trader_id, self.spoof_side, price,
                           self.spoof_size, current_day)
        order_book.add_limit_order(order, trader_map, current_day)

        # Only enter SPOOFING if it actually rested (didn't accidentally fill).
        if order_book.orders.get(oid) is not None and order.active:
            self.spoof_order_id = oid
            self.state = self.STATE_SPOOFING
            self.spoof_started_day = current_day
            self.mid_at_spoof = mid
        else:
            self._cancel_spoof(order_book, trader_map)
            self.spoof_side = None

    def _manage_spoof(self, mid: float, order_book: "OrderBook",
                      trader_map: dict, current_day: int) -> None:
        # Abort if our spoof got hit or decayed (defeats the plan).
        if not self._spoof_order_alive(order_book):
            self._reset_cycle(current_day)
            return

        move = (mid - self.mid_at_spoof) / self.mid_at_spoof
        elapsed = current_day - self.spoof_started_day
        target = 0.004  # 0.4% induced move is enough to harvest

        success = ((self.spoof_side == 'BUY' and move >= target) or
                   (self.spoof_side == 'SELL' and move <= -target))

        if success:
            profit_side = 'SELL' if self.spoof_side == 'BUY' else 'BUY'
            self._cancel_spoof(order_book, trader_map)   # pull before harvest
            if profit_side == 'SELL':
                qty = min(self.attack_size, self.shares)
            else:
                cost = mid * (1.0 + order_book.commission_rate)
                qty = min(self.attack_size, int(self.cash // cost))
            if qty > 0:
                order_book.execute_market_order(
                    MarketOrder(self.trader_id, profit_side, qty),
                    trader_map, current_day)
            self._reset_cycle(current_day)
        elif elapsed >= self.patience:
            # Move never materialised: pull the spoof and stand down.
            self._cancel_spoof(order_book, trader_map)
            self._reset_cycle(current_day)

    def _reset_cycle(self, current_day: int) -> None:
        self._clear_spoof_refs()
        self.state = self.STATE_IDLE
        self.next_active_day = current_day + self.cooldown

    def _clear_spoof_refs(self) -> None:
        self.spoof_order_id = None
        self.spoof_side = None


# --------------------------------------------------------------------------- #
# Simulation orchestrator
# --------------------------------------------------------------------------- #
class Simulation:
    """Main executor of the agent-based financial market simulation."""

    STRATEGIES = ('noise', 'fundamentalist', 'chartist')

    def __init__(self, num_traders: int = 60, initial_cash: float = 10_000.0,
                 initial_shares: int = 50, initial_price: float = 100.0,
                 rf_rate: float = 0.02, days: int = 1000,
                 num_manipulators: int = 2):
        self.days = days
        self.rf_rate = rf_rate
        self.initial_cash = initial_cash
        self.initial_shares = initial_shares
        self.initial_price = initial_price

        self.traders: list[Trader] = []          # Evolutionary population only
        self.trader_map: dict[str, Trader] = {}  # ALL participants (incl. MM)
        self.next_trader_id_counter = 0

        # Seed the evolutionary population in three equal cohorts.
        noise_count = num_traders // 3
        fund_count = num_traders // 3
        chart_count = num_traders - noise_count - fund_count
        for _ in range(noise_count):
            self.create_and_add_trader('noise')
        for _ in range(fund_count):
            self.create_and_add_trader('fundamentalist')
        for _ in range(chart_count):
            self.create_and_add_trader('chartist')

        # The MM lives in `trader_map` (so it settles trades) AND in
        # `macro_participants` (dividends and interest), but NOT in
        # `self.traders` (it is not subject to evolution).
        self.market_maker = MarketMaker(
            trader_id="T_MM", cash=1_000_000.0, shares=10_000,
            target_inventory=10_000, level_qty=15, num_levels=5)
        self.trader_map["T_MM"] = self.market_maker

        # Manipulators -- also full macro participants.
        self.manipulators: list[Manipulator] = []
        for i in range(num_manipulators):
            manip = Manipulator(
                trader_id=f"T_MANIP_{i + 1}", cash=500_000.0, shares=2_000,
                spoof_size=400, attack_size=40)
            self.manipulators.append(manip)
            self.trader_map[manip.trader_id] = manip

        # Asset and book. Part B, fix 3: the corporate balance is seeded
        # from the TRUE float (all holders, incl. MM and Manipulators) so
        # fundamental value == initial price at t=0 instead of starting the
        # market structurally ~58% overvalued.
        initial_balance = self.total_shares_outstanding() * initial_price
        self.asset = Asset("XYZ", initial_price, initial_balance)
        self.order_book = OrderBook()

        # One shared incremental EMA pair for the whole market (O(1)/day).
        self.ema_fast = IncrementalEMA(period=5)
        self.ema_slow = IncrementalEMA(period=15)
        self.ema_fast.update(initial_price)
        self.ema_slow.update(initial_price)

        # Rolling window of recent closes for volatility estimation.
        self.recent_closes: collections.deque = collections.deque(
            [initial_price], maxlen=20)

        # Part D, fix 1: volume regime tracking for dynamic friction.
        self.recent_volumes: collections.deque = collections.deque(maxlen=10)
        self.volume_baseline = IncrementalEMA(period=60)

        # Part A: logit-evolution state -- smoothed strategy attractiveness
        # and the per-strategy average wealth recorded at the last epoch.
        self.strategy_attractiveness = {s: 0.0 for s in self.STRATEGIES}
        self._epoch_wealth_marker: dict[str, Optional[float]] = {
            s: None for s in self.STRATEGIES}

        # Logging. All strategy series (incl. the two specialist agents).
        self.log_price = [initial_price]
        self.log_balance = [initial_balance]
        self.log_demographics = {s: [] for s in self.STRATEGIES}
        self.log_avg_wealth = {s: [] for s in self.STRATEGIES}
        self.log_mm_wealth: list[float] = []
        self.log_manip_wealth: list[float] = []

    # -- participant helpers ------------------------------------------------ #
    def macro_participants(self):
        """Every entity that receives dividends and interest."""
        yield from self.traders
        yield self.market_maker
        yield from self.manipulators

    def total_shares_outstanding(self) -> int:
        """True float across ALL holders, computed live."""
        return sum(p.total_shares for p in self.macro_participants())

    def create_and_add_trader(self, trader_type: str,
                              current_day: int = 0) -> Trader:
        self.next_trader_id_counter += 1
        t_id = f"T_{trader_type[0].upper()}_{self.next_trader_id_counter}"
        trader = Trader(t_id, self.initial_cash, self.initial_shares,
                        trader_type, current_day=current_day)
        self.traders.append(trader)
        self.trader_map[t_id] = trader
        return trader

    def get_fundamental_value(self) -> float:
        """Intrinsic value = corporate balance / live shares outstanding."""
        shares = self.total_shares_outstanding()
        if shares <= 0:
            return self.asset.get_last_price()
        return self.asset.balance / shares

    def is_weekend(self, day: int) -> bool:
        return (day % 7) == 6 or (day % 7) == 0

    def current_volatility(self) -> float:
        """Relative realised volatility of recent closes (sigma / mean)."""
        if len(self.recent_closes) < 2:
            return 0.0
        mean = statistics.fmean(self.recent_closes)
        if mean <= 0.0:
            return 0.0
        return statistics.pstdev(self.recent_closes) / mean

    # -- macro events ------------------------------------------------------- #
    def pay_dividends(self) -> None:
        """
        Solvency-constrained dividend: the per-share payout is capped so the
        total distribution never pushes the corporate balance below the
        $50k floor -- no money printing.
        """
        shares_out = self.total_shares_outstanding()
        if shares_out <= 0:
            return

        distributable = max(0.0, self.asset.balance - CORPORATE_BALANCE_FLOOR)
        per_share = min(BASE_DIVIDEND_PER_SHARE, distributable / shares_out)
        if per_share <= 0.0:
            return

        total_paid = 0.0
        for participant in self.macro_participants():
            payout = participant.total_shares * per_share
            participant.cash += payout
            total_paid += payout
        self.asset.balance -= total_paid  # guaranteed >= floor by construction

    def accrue_interest(self) -> None:
        """Risk-free daily interest on available cash for every holder."""
        daily = self.rf_rate / 365.0
        for participant in self.macro_participants():
            participant.cash += participant.cash * daily

    # -- fluid friction and LOB decay (Part D) ------------------------------- #
    def update_friction(self) -> None:
        """
        Scales commission and Tobin tax with the current volume regime:
        activity = short-run average volume / long-run EMA baseline. In
        quiet markets the friction relaxes toward its floor so transaction
        costs can no longer paralyse non-speculative flow; in active
        markets it returns to the full statutory level.
        """
        if self.recent_volumes:
            short_run = statistics.fmean(self.recent_volumes)
        else:
            short_run = 0.0
        baseline = self.volume_baseline.value
        if baseline is None or baseline <= 1e-9:
            activity = 0.0
        else:
            activity = min(short_run / baseline, 1.0)

        commission = MIN_COMMISSION_RATE \
            + (BASE_COMMISSION_RATE - MIN_COMMISSION_RATE) * activity
        tobin = MIN_TOBIN_RATE + (TOBIN_TAX_RATE - MIN_TOBIN_RATE) * activity
        self.order_book.set_friction(commission, tobin)

    def decay_resting_orders(self, day: int) -> None:
        """
        Part D, fix 2: probabilistic order evaporation. Each non-MM resting
        order is cancelled with a hazard that rises with age:

            h(age) = min(MAX, BASE * (1 + age / AGE_SCALE))

        Expected lifetimes are a few days with a smooth tail, so stale
        price walls dissolve organically instead of persisting for a full
        TTL and vanishing all at once. (The MM refreshes its own quotes
        daily and is exempt.) Cancellation refunds escrow as always.
        """
        for order in list(self.order_book.orders.values()):
            owner = self.trader_map.get(order.trader_id)
            if owner is self.market_maker:
                continue
            age = day - order.timestamp
            hazard = min(ORDER_DECAY_MAX_HAZARD,
                         ORDER_DECAY_BASE_HAZARD
                         * (1.0 + age / ORDER_DECAY_AGE_SCALE))
            if random.random() < hazard:
                self.order_book.cancel_order(order.order_id, self.trader_map)

    # -- evolutionary review (Part A: logit choice, memory, switch cap) ------ #
    def evolutionary_review(self, day: int, closing_price: float) -> int:
        """
        Discrete-choice strategy evolution, every EVOLUTION_EPOCH_DAYS:

          1. Fitness: each strategy's epoch return (average wealth now vs
             at the previous review) is folded into an exponentially
             smoothed attractiveness score (STRATEGY_MEMORY inertia), so a
             single lucky epoch cannot flip the population.
          2. Choice: migration targets are sampled from a softmax (logit /
             Gibbs) over the smoothed scores with intensity-of-choice
             INTENSITY_OF_CHOICE -- probabilistic, not winner-take-all.
          3. Inertia: only ~SWITCH_CONSIDERATION_RATE of traders re-evaluate
             at all this epoch.
          4. Cap: at most MAX_SWITCH_FRACTION of the whole population may
             actually change strategy, structurally bounding herd shocks.

        Returns the number of traders that switched.
        """
        wealth_by_type = {s: [] for s in self.STRATEGIES}
        for trader in self.traders:
            wealth_by_type[trader.type].append(trader.get_wealth(closing_price))
        avg_wealth = {
            s: (sum(v) / len(v) if v else 0.0)
            for s, v in wealth_by_type.items()
        }

        # 1. Epoch performance -> smoothed attractiveness (memory/inertia).
        for s in self.STRATEGIES:
            prev = self._epoch_wealth_marker[s]
            cur = avg_wealth[s]
            if prev is not None and prev > 0.0 and cur > 0.0:
                epoch_return = cur / prev - 1.0
            else:
                epoch_return = 0.0   # No comparable history: neutral fitness.
            self.strategy_attractiveness[s] = (
                STRATEGY_MEMORY * self.strategy_attractiveness[s]
                + (1.0 - STRATEGY_MEMORY) * epoch_return)
            if cur > 0.0:
                self._epoch_wealth_marker[s] = cur

        # 2. Logit choice probabilities (max-shifted softmax for stability).
        scores = [INTENSITY_OF_CHOICE * self.strategy_attractiveness[s]
                  for s in self.STRATEGIES]
        peak = max(scores)
        exp_scores = [math.exp(x - peak) for x in scores]
        norm = sum(exp_scores)
        probs = [x / norm for x in exp_scores]

        # 3 + 4. Inertia-filtered candidates, hard-capped migration budget.
        budget = max(1, int(MAX_SWITCH_FRACTION * len(self.traders)))
        candidates = [t for t in self.traders
                      if random.random() < SWITCH_CONSIDERATION_RATE]
        random.shuffle(candidates)

        switched = 0
        for trader in candidates:
            if switched >= budget:
                break
            new_type = random.choices(self.STRATEGIES, weights=probs, k=1)[0]
            if new_type != trader.type:
                trader.switch_strategy(new_type, day, self.order_book,
                                       self.trader_map)
                switched += 1
        return switched

    def handle_bankruptcies(self, day: int) -> None:
        """Removes broke traders and reseeds the population by type."""
        bankrupt = [t for t in self.traders
                    if t.total_cash < 1e-5 and t.total_shares == 0]
        for bt in bankrupt:
            for oid in list(bt.active_orders):
                self.order_book.cancel_order(oid, self.trader_map)
            self.traders.remove(bt)
            del self.trader_map[bt.trader_id]
            self.create_and_add_trader(bt.type, current_day=day)

    # -- logging ------------------------------------------------------------ #
    def log_daily_metrics(self, current_price: float) -> None:
        counts = {s: 0 for s in self.STRATEGIES}
        wealths = {s: [] for s in self.STRATEGIES}
        for trader in self.traders:
            counts[trader.type] += 1
            wealths[trader.type].append(trader.get_wealth(current_price))
        for s in self.STRATEGIES:
            self.log_demographics[s].append(counts[s])
            self.log_avg_wealth[s].append(
                sum(wealths[s]) / len(wealths[s]) if wealths[s] else 0.0)

        self.log_mm_wealth.append(self.market_maker.get_wealth(current_price))
        if self.manipulators:
            self.log_manip_wealth.append(
                sum(m.get_wealth(current_price) for m in self.manipulators)
                / len(self.manipulators))
        else:
            self.log_manip_wealth.append(0.0)

    # -- main loop ---------------------------------------------------------- #
    def run(self) -> None:
        print(f"Starting Financial Market Simulation for {self.days} days...")

        for day in range(1, self.days + 1):
            last_price = self.asset.get_last_price()

            # Weekends: interest accrues, no trading.
            if self.is_weekend(day):
                self.accrue_interest()
                self.asset.record_close(last_price)
                self.log_price.append(last_price)
                self.log_balance.append(self.asset.balance)
                self.log_daily_metrics(last_price)
                continue

            # 1. Organic information arrival: OU step of the fundamental
            #    (Part B), then quarterly solvency-constrained dividends.
            self.asset.update_daily_fundamental()
            if day % EVOLUTION_EPOCH_DAYS == 0:
                self.pay_dividends()

            # 2. Fluid friction for today's volume regime (Part D, fix 1)
            #    and probabilistic evaporation of stale orders (fix 2).
            self.update_friction()
            self.decay_resting_orders(day)

            # 3. Market maker re-quotes: tanh-skewed reservation price,
            #    asymmetric volatility-scaled spread (Part C).
            rel_vol = self.current_volatility()
            mid = self.order_book.get_midpoint(last_price)
            self.market_maker.place_quotes(
                mid, rel_vol, self.order_book, self.trader_map, day)
            # Part C, fix 3: daily thin-book check -- if overnight decay or
            # cancellations left near-mid depth hollow, backstop it before
            # any taker can gap the price through a void.
            self.market_maker.provide_structural_depth(
                mid, self.order_book, self.trader_map, day)

            # 4. Manipulators read the book and act.
            for manip in self.manipulators:
                manip.act(self.order_book.get_midpoint(last_price),
                          self.order_book, self.trader_map, day)

            # 5. Evolutionary traders act in randomised order.
            ema_ready = self.ema_slow.count >= 15
            ef, es = self.ema_fast.value, self.ema_slow.value

            active_traders = list(self.traders)
            random.shuffle(active_traders)
            day_trades = []

            for trader in active_traders:
                ref_price = self.order_book.get_midpoint(last_price)
                v_fund = self.get_fundamental_value()
                imbalance = self.order_book.get_imbalance(ref_price)

                decision = trader.decide_order(
                    ref_price, v_fund, ef, es, ema_ready, imbalance, rel_vol)
                if decision is None:
                    continue

                order_type, side, price, quantity = decision
                if order_type == 'LIMIT':
                    if side == 'BUY':
                        cost = price * quantity \
                            * (1.0 + self.order_book.commission_rate)
                        if trader.cash >= cost:
                            oid = self.order_book.get_next_order_id()
                            day_trades.extend(self.order_book.add_limit_order(
                                LimitOrder(oid, trader.trader_id, side, price,
                                           quantity, day),
                                self.trader_map, day))
                    elif trader.shares >= quantity:
                        oid = self.order_book.get_next_order_id()
                        day_trades.extend(self.order_book.add_limit_order(
                            LimitOrder(oid, trader.trader_id, side, price,
                                       quantity, day),
                            self.trader_map, day))
                else:  # MARKET
                    if side == 'BUY':
                        day_trades.extend(self.order_book.execute_market_order(
                            MarketOrder(trader.trader_id, side, quantity),
                            self.trader_map, day))
                    elif trader.shares > 0:
                        qty = min(quantity, trader.shares)
                        day_trades.extend(self.order_book.execute_market_order(
                            MarketOrder(trader.trader_id, side, qty),
                            self.trader_map, day))

            # 6. Daily interest.
            self.accrue_interest()

            # 7. Closing price: VWAP of the day's executions (a single deep
            #    sweep through a thin level can no longer print the close),
            #    persisted to the asset history.
            if day_trades:
                traded_value = sum(p * q for _, p, q in day_trades)
                traded_qty = sum(q for _, _, q in day_trades)
                closing_price = traded_value / traded_qty
            else:
                closing_price = last_price
            self.asset.record_close(closing_price)
            self.log_price.append(closing_price)
            self.log_balance.append(self.asset.balance)

            # 8. Update shared EMAs, volatility window, and volume regime.
            self.ema_fast.update(closing_price)
            self.ema_slow.update(closing_price)
            self.recent_closes.append(closing_price)
            day_volume = float(sum(qty for _, _, qty in day_trades))
            self.recent_volumes.append(day_volume)
            self.volume_baseline.update(day_volume)

            # 9. Bankruptcies and (capped, logit-driven) evolution.
            self.handle_bankruptcies(day)
            if day % EVOLUTION_EPOCH_DAYS == 0:
                switched = self.evolutionary_review(day, closing_price)
                if switched > 0:
                    # Part C, fix 3: the review mass-cancelled the switchers'
                    # resting orders -- backstop any resulting thin spots so
                    # the next market order cannot gap through a void.
                    self.market_maker.provide_structural_depth(
                        self.order_book.get_midpoint(closing_price),
                        self.order_book, self.trader_map, day)

            # 10. Log.
            self.log_daily_metrics(closing_price)

        print("Simulation complete.")

    # -- plotting ----------------------------------------------------------- #
    def plot_dashboard(self,
                       output_path: str = "market_simulation_dashboard.png"):
        plt.style.use('default')
        fig, axes = plt.subplots(4, 1, figsize=(12, 21))
        ax1, ax2, ax3, ax4 = axes
        days_range = list(range(self.days + 1))
        active_days = list(range(1, self.days + 1))
        colors = {'noise': '#d62728', 'fundamentalist': '#2ca02c',
                  'chartist': '#9467bd', 'mm': '#1f77b4',
                  'manip': '#8c564b'}

        # Subplot 1: price vs corporate balance.
        c_price = '#1f77b4'
        ax1.plot(days_range, self.log_price, color=c_price, linewidth=1.6,
                 label='Asset Price ($)')
        ax1.set_xlabel('Calendar Days', fontsize=11, fontweight='bold')
        ax1.set_ylabel('Market Price ($)', color=c_price, fontsize=11,
                       fontweight='bold')
        ax1.tick_params(axis='y', labelcolor=c_price)
        ax1.grid(True, linestyle=':', alpha=0.6)
        ax1_t = ax1.twinx()
        c_bal = '#ff7f0e'
        ax1_t.plot(days_range, self.log_balance, color=c_bal, linewidth=2,
                   linestyle='--', label='Corporate Balance ($)')
        ax1_t.set_ylabel('Corporate Balance ($)', color=c_bal, fontsize=11,
                         fontweight='bold')
        ax1_t.tick_params(axis='y', labelcolor=c_bal)
        l1, lab1 = ax1.get_legend_handles_labels()
        l2, lab2 = ax1_t.get_legend_handles_labels()
        ax1.legend(l1 + l2, lab1 + lab2, loc='upper left', frameon=True,
                   facecolor='white', framealpha=0.9)
        ax1.set_title('Asset Closing Price & Corporate Balance Sheet History',
                      fontsize=13, fontweight='bold', pad=15)

        # Subplot 2: evolutionary strategy wealth.
        for s in self.STRATEGIES:
            ax2.plot(active_days, self.log_avg_wealth[s], color=colors[s],
                     linewidth=1.8, label=f'{s.capitalize()} Wealth')
        ax2.set_title('Time-Series Evolution of Average Strategy Wealth',
                      fontsize=13, fontweight='bold', pad=15)
        ax2.set_xlabel('Calendar Days', fontsize=11, fontweight='bold')
        ax2.set_ylabel('Average Trader Wealth ($)', fontsize=11,
                       fontweight='bold')
        ax2.grid(True, linestyle=':', alpha=0.6)
        ax2.legend(loc='upper left', frameon=True, facecolor='white',
                   framealpha=0.9)

        # Subplot 3: specialist agents' wealth (MM + Manipulators).
        ax3.plot(active_days, self.log_mm_wealth, color=colors['mm'],
                 linewidth=1.8, label='Market Maker Wealth')
        ax3.plot(active_days, self.log_manip_wealth, color=colors['manip'],
                 linewidth=1.8, label='Manipulator Wealth (avg)')
        ax3.set_title('Specialist Agent Wealth: Market Maker & Manipulators',
                      fontsize=13, fontweight='bold', pad=15)
        ax3.set_xlabel('Calendar Days', fontsize=11, fontweight='bold')
        ax3.set_ylabel('Agent Wealth ($)', fontsize=11, fontweight='bold')
        ax3.grid(True, linestyle=':', alpha=0.6)
        ax3.legend(loc='upper left', frameon=True, facecolor='white',
                   framealpha=0.9)

        # Subplot 4: population demographics.
        for s in self.STRATEGIES:
            ax4.plot(active_days, self.log_demographics[s], color=colors[s],
                     linewidth=1.8, label=f'{s.capitalize()} Count')
        ax4.set_title('Trader Population Demographics Over Time',
                      fontsize=13, fontweight='bold', pad=15)
        ax4.set_xlabel('Calendar Days', fontsize=11, fontweight='bold')
        ax4.set_ylabel('Number of Active Agents', fontsize=11,
                       fontweight='bold')
        ax4.grid(True, linestyle=':', alpha=0.6)
        ax4.legend(loc='upper left', frameon=True, facecolor='white',
                   framealpha=0.9)

        plt.tight_layout()
        plt.savefig(output_path, dpi=300)
        print(f"Dashboard figure saved as '{output_path}'.")
        plt.close(fig)


def export_simulation_metrics(sim: Simulation,
                              csv_path: str = "simulation_results.csv") -> None:
    """Exports daily metrics (incl. specialist agents) to CSV."""
    with open(csv_path, mode='w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'day', 'asset_price', 'corporate_balance',
            'noise_count', 'fundamentalist_count', 'chartist_count',
            'noise_wealth', 'fundamentalist_wealth', 'chartist_wealth',
            'market_maker_wealth', 'manipulator_wealth',
        ])
        for d in range(sim.days + 1):
            if d == 0:
                writer.writerow([0, sim.log_price[0], sim.log_balance[0],
                                 "", "", "", "", "", "", "", ""])
            else:
                i = d - 1
                writer.writerow([
                    d, sim.log_price[d], sim.log_balance[d],
                    sim.log_demographics['noise'][i],
                    sim.log_demographics['fundamentalist'][i],
                    sim.log_demographics['chartist'][i],
                    sim.log_avg_wealth['noise'][i],
                    sim.log_avg_wealth['fundamentalist'][i],
                    sim.log_avg_wealth['chartist'][i],
                    sim.log_mm_wealth[i],
                    sim.log_manip_wealth[i],
                ])
    print(f"Simulation metrics exported to '{csv_path}'.")


if __name__ == '__main__':
    random.seed(42)
    sim = Simulation(num_traders=100, initial_cash=10_000.0,
                     initial_shares=100, initial_price=100.0,
                     rf_rate=0.03, days=2000, num_manipulators=2)
    sim.run()
    export_simulation_metrics(sim, "simulation_results.csv")
    sim.plot_dashboard("market_simulation_dashboard.png")
