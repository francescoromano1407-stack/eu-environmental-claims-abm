"""
Multi-agent behavioral layer.

Contains the base `Trader` (noise / fundamentalist / chartist decision
logic with the elastic erf-based valuation corridor of Part B), the
inventory-adaptive `MarketMaker` (tanh skew and asymmetric vol-scaled
spreads of Part C), and the stateful `Manipulator` spoofing finite-state
machine.

Circular-dependency note: agents construct `LimitOrder`/`MarketOrder`
instances (runtime import from `models`) but only *reference* the book,
which is injected into every method that needs it. `OrderBook` is
therefore imported strictly under `TYPE_CHECKING`, guaranteeing zero
circular imports at runtime.
"""

from __future__ import annotations

import collections
import math
import random
from typing import TYPE_CHECKING, Optional

from market_sim.models import LimitOrder, MarketOrder

if TYPE_CHECKING:
    from market_sim.order_book import OrderBook


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
