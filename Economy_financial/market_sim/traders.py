"""
Multi-agent behavioral layer.

Contains the base `Trader` (noise / fundamentalist / chartist decision
logic with the elastic erf-based valuation corridor of Part B), the
inventory-adaptive `MarketMaker` (tanh skew and asymmetric vol-scaled
spreads of Part C), and the stateful `Manipulator` spoofing finite-state
machine.

Strategy dispatch is resolved once per strategy change: each trader holds
a bound `_decision_handler` selected at construction / `switch_strategy`,
so `decide_order` performs zero string comparisons in the hot loop.

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

from market_sim.constants import (
    GREEN_SENTIMENT_EVENT_BOOST,
    GREEN_SENTIMENT_WINDOW_DAYS,
    GREENIUM_GAMMA,
    STATE_GREEN_THRESHOLD,
)
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

    # Pre-computed Gaussian ogive denominator constant (erf corridor).
    SQRT_2 = math.sqrt(2.0)

    # Part F: market-wide sustainable conviction (greenium sensitivity).
    GREENIUM_GAMMA = GREENIUM_GAMMA

    # Strategy -> handler-method name; resolved to a bound method once per
    # strategy change (O(1) dynamic dispatch, no if/elif chain per call).
    _HANDLER_NAMES = {
        'noise': '_decide_noise',
        'fundamentalist': '_decide_fundamentalist',
        'chartist': '_decide_chartist',
    }

    def __init__(self, trader_id: str, cash: float, shares: int,
                 trader_type: str, current_day: int = 0):
        self.trader_id = trader_id            # Immutable canonical id (map key)
        self.cash = float(cash)
        self.cash_reserved = 0.0              # Cash escrowed in resting bids
        self.shares = int(shares)
        self.shares_reserved = 0              # Shares escrowed in resting asks
        self.type = trader_type
        self._bind_decision_handler()
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

        # -- credit state (Part E) -- all zero (and provably inert) unless
        # the Simulation is constructed with enable_credit=True.
        self.shares_collateral = 0   # Shares pledged against credit lines
        self.debt = 0.0              # Float mirror of total outstanding debt
        self.cash_lent = 0.0         # P2P receivables owed to this trader

        # -- multi-asset state (Part F) -- None in single-asset mode; a
        # {symbol: AssetPosition} dict when the ESG ecosystem is active.
        self.positions = None

    # -- identity ---------------------------------------------------------- #
    @property
    def label(self) -> str:
        """Log-friendly id whose prefix always reflects the current strategy."""
        return f"{self.trader_id}[{self.type}]"

    def _bind_decision_handler(self) -> None:
        """Resolves the current strategy to a bound decision method."""
        name = self._HANDLER_NAMES.get(self.type)
        self._decision_handler = getattr(self, name) if name else None

    def switch_strategy(self, new_type: str, day: int,
                        order_book: "OrderBook", trader_map: dict) -> None:
        """
        Switches strategy, records it, and cancels all open orders (they
        were priced under the old strategy's logic). In multi-asset mode
        the cancellation sweeps every venue through the position views.
        """
        if new_type == self.type:
            return
        if self.positions is not None:
            for pos in self.positions.values():
                for oid in list(pos.active_orders):
                    pos.book.cancel_order(oid, pos.book_map)
        else:
            for oid in list(self.active_orders):
                order_book.cancel_order(oid, trader_map)
        self.type = new_type
        self._bind_decision_handler()
        self.strategy_history.append((day, new_type))

    # -- accounting -------------------------------------------------------- #
    @property
    def total_cash(self) -> float:
        return self.cash + self.cash_reserved

    @property
    def total_shares(self) -> int:
        return self.shares + self.shares_reserved + self.shares_collateral

    def get_wealth(self, current_price: float) -> float:
        """
        Mark-to-market gross asset value: all cash (free + escrowed), all
        shares (free + escrowed + pledged as collateral), and any P2P
        lending receivables. Liabilities are NOT netted here -- see
        `get_equity` for wealth net of debt. With the credit system off,
        the extra terms are exactly zero and this is bit-identical to the
        pre-credit definition.
        """
        return (self.total_cash + self.total_shares * current_price
                + self.cash_lent)

    # -- leverage (Part E): assess and update credit conditions ------------- #
    def get_equity(self, current_price: float) -> float:
        """Mark-to-market equity: gross wealth minus outstanding debt."""
        return self.get_wealth(current_price) - self.debt

    def debt_to_equity(self, current_price: float) -> float:
        """Leverage ratio for the macroprudential cap; inf if insolvent."""
        equity = self.get_equity(current_price)
        if equity <= 0.0:
            return math.inf
        return self.debt / equity

    def pledge_collateral(self, qty: int) -> None:
        """Locks free shares as credit collateral (escrow-style move)."""
        self.shares -= qty
        self.shares_collateral += qty

    def release_collateral(self, qty: int) -> None:
        """Returns pledged shares to the freely tradable pool."""
        self.shares_collateral -= qty
        self.shares += qty

    # -- decision logic ---------------------------------------------------- #
    def decide_order(self, current_price: float, v_fundamental: float,
                     ema_fast: float, ema_slow: float, ema_ready: bool,
                     book_imbalance: float, rel_volatility: float,
                     green_score: float = 0.0) -> Optional[tuple]:
        """
        Returns (order_type, side, price, quantity) or None.

        `book_imbalance` in [-1, 1] is the depth imbalance near the mid
        (the surface the Manipulator's spoof orders exploit).
        `rel_volatility` is the realised relative volatility of recent
        closes, which stretches the fundamentalist corridor (Part B).
        `green_score` (Part F) is the asset's sustainability score; the
        default 0.0 makes the greenium a multiplication by exactly 1.0,
        so single-asset behavior is bit-identical.
        """
        handler = self._decision_handler
        if handler is None:
            return None
        return handler(current_price, v_fundamental, ema_fast, ema_slow,
                       ema_ready, book_imbalance, rel_volatility,
                       green_score)

    def _decide_noise(self, current_price: float, v_fundamental: float,
                      ema_fast: float, ema_slow: float, ema_ready: bool,
                      imbalance: float, rel_volatility: float,
                      green_score: float = 0.0) -> Optional[tuple]:
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
                               v_fundamental: float, ema_fast: float,
                               ema_slow: float, ema_ready: bool,
                               imbalance: float, rel_volatility: float,
                               green_score: float = 0.0) -> Optional[tuple]:
        """
        Part B, fix 2: elastic probabilistic corridor.
        Part F: greenium-adjusted fair value. The raw OU fundamental is
        stretched by the market's sustainable conviction,

            V_green_fair = V_fundamental * (1 + GREENIUM_GAMMA * score),

        so fundamentalists accumulate green assets (which look structurally
        undervalued at par) and distribute brown ones. For score == 0 the
        multiplier is exactly 1.0 -- a bit-exact float identity -- and the
        legacy valuation is untouched.

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
        v_green_fair = v_fundamental * (1.0 + self.GREENIUM_GAMMA
                                        * green_score)

        mispricing = (v_green_fair - current_price) / v_green_fair
        band = min(self.FUND_BAND_MAX,
                   self.FUND_BAND_BASE
                   + self.FUND_BAND_VOL_SCALE * rel_volatility)
        conviction = math.erf(abs(mispricing) / (band * self.SQRT_2))
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
            limit = min(v_green_fair * (1.0 - random.uniform(0.1, 0.5) * band),
                        current_price * (1.0 + 0.5 * band))
            return ('LIMIT', 'BUY', max(0.01, round(limit, 2)), qty)

        # Overvalued -> distribute.
        if random.random() < p_market:
            return ('MARKET', 'SELL', None, qty)
        limit = max(v_green_fair * (1.0 + random.uniform(0.1, 0.5) * band),
                    current_price * (1.0 - 0.5 * band))
        return ('LIMIT', 'SELL', max(0.01, round(limit, 2)), qty)

    def _decide_chartist(self, current_price: float, v_fundamental: float, ema_fast: float, ema_slow: float, ema_ready: bool, imbalance: float, rel_volatility: float, green_score: float = 0.0) -> Optional[tuple]:
        """
        CONTRARIAN MEAN-REVERSION TRADER (Optimized)
        Invece di inseguire il trend in ritardo, vende i picchi e compra i minimi.
        Usa solo ordini limite passivi per incassare lo spread anziché pagarlo,
        ed è immune allo spoofing dei manipolatori.
        """
        if not ema_ready:
            # Warm-up: rimaniamo fermi a accumulare liquidità invece di fare noise trading costoso
            return None

        # 1. Pulizia del segnale: eliminiamo l'imbalance per diventare immuni ai Manipolatori
        pure_trend = (ema_fast - ema_slow) / ema_slow

        # Applichiamo la deadzone per evitare micro-operazioni inutili
        if abs(pure_trend) < self.CHARTIST_DEADZONE:
            return None

        qty = random.randint(2, 6) # Leggermente più aggressivi sulla dimensione

        # 2. Logica Contrarian (Invertiamo il trend)
        # Se il prezzo è salito troppo velocemente (pure_trend > 0), shortiamo il picco!
        if pure_trend > 0.0:
            # Piazziamo un ordine limite PASSIVO sopra il mid per vendere al prezzo più alto possibile
            price = current_price * (1.0 + random.uniform(0.001, 0.005))
            return ('LIMIT', 'SELL', max(0.01, round(price, 2)), qty)

        # Se il prezzo è sceso troppo velocemente (pure_trend < 0), compriamo il deep!
        else:
            # Piazziamo un ordine limite PASSIVO sotto il mid, aspettando che il mercato ci colpisca
            price = current_price * (1.0 - random.uniform(0.001, 0.005))
            return ('LIMIT', 'BUY', max(0.01, round(price, 2)), qty)


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

    Inertial quoting: re-quoting is skipped entirely when the freshly
    computed ladder is quantization-identical (cent-rounded prices,
    integer sizes) to the one already resting and none of it has been
    filled or decayed. Static regimes therefore stop flooding the book
    with cancel/repost tombstone churn.
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
        # Inertial-quoting state: the last posted ladder plus the resting
        # order count/volume observed right after posting it.
        self._last_quote_ladder: Optional[tuple] = None
        self._last_quote_count = -1
        self._last_quote_resting_qty = -1

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

    def _compute_ladder(self, mid: float, rel_volatility: float) -> tuple:
        """
        Deterministically derives the quote ladder for the current state:
        a tuple of (side, price, qty) triples. Pure function of (mid,
        rel_volatility, inventory stress) -- used both for posting and for
        the inertial identical-ladder skip.
        """
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

        ladder = []
        for i in range(self.num_levels):
            step = mid * self.level_step * i
            bid_price = max(0.01, round(reservation - bid_half - step, 2))
            ask_price = round(reservation + ask_half + step, 2)
            ask_price = max(ask_price, bid_price + 0.01)
            ladder.append(('BUY', bid_price,
                           max(1, int(self.level_qty * bid_scale))))
            ladder.append(('SELL', ask_price,
                           max(1, int(self.level_qty * ask_scale))))
        return tuple(ladder)

    def _resting_quote_qty(self, order_book: "OrderBook") -> int:
        """Total unfilled volume across the MM's own resting orders."""
        orders = order_book.orders
        total = 0
        for oid in self.active_orders:
            order = orders.get(oid)
            if order is not None:
                total += order.quantity
        return total

    # -- quoting -------------------------------------------------------------#
    def place_quotes(self, mid: float, rel_volatility: float,
                     order_book: "OrderBook", trader_map: dict,
                     current_day: int) -> None:
        """Cancels stale quotes, recomputes skew/spread, re-quotes the ladder."""
        ladder = self._compute_ladder(mid, rel_volatility)

        # Inertial tolerance: if the state-derived ladder is identical to
        # the one already resting (mid/stress/vol moved less than the cent
        # and integer-size quantization) and nothing has been filled or
        # decayed since it was posted, keep the existing quotes -- no
        # mass-cancellation, no tombstone churn, and time priority is kept.
        if (ladder == self._last_quote_ladder
                and len(self.active_orders) == self._last_quote_count
                and self._resting_quote_qty(order_book)
                == self._last_quote_resting_qty):
            return

        # Refresh: cancel our own resting quotes before re-quoting.
        for oid in list(self.active_orders):
            order_book.cancel_order(oid, trader_map)

        for side, price, qty in ladder:
            self._place_own_limit(side, price, qty, order_book, trader_map,
                                  current_day)

        self._last_quote_ladder = ladder
        self._last_quote_count = len(self.active_orders)
        self._last_quote_resting_qty = self._resting_quote_qty(order_book)

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

        Local solvency is checked *before* any depth scan: a side on which
        the MM could not post even one share never touches the LOB.
        """
        # Cheapest possible backstop bid: the deepest layer (largest
        # offset). If even one share there is unaffordable, skip the scan.
        lowest_bid = max(0.01, round(mid * (1.0 - 0.03), 2))
        can_bid = self.cash >= lowest_bid * (1.0 + order_book.commission_rate)
        if can_bid and order_book.depth_within(
                'BUY', mid, band) < self.backstop_min_depth:
            for offset in (0.015, 0.03):
                price = max(0.01, round(mid * (1.0 - offset), 2))
                self._place_own_limit('BUY', price, self.backstop_qty,
                                      order_book, trader_map, current_day)
        if self.shares > 0 and order_book.depth_within(
                'SELL', mid, band) < self.backstop_min_depth:
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
        # Local economic state first: if neither side of a spoof cycle is
        # fundable, stand down before paying for any LOB depth scan.
        can_spoof_buy = self.cash > mid * self.spoof_size
        can_spoof_sell = self.total_shares >= self.attack_size
        if not can_spoof_buy and not can_spoof_sell:
            return

        # Read imbalance excluding our own resting orders.
        imbalance = order_book.get_imbalance(mid, exclude_trader=self.trader_id)

        # Spoof to *reinforce and exaggerate* the thinner side's opposite:
        # plant a big BID (fake buy pressure) when we intend to sell into the
        # induced rally, and vice-versa. Bias toward whichever side we can
        # actually monetise given current holdings.
        if imbalance <= 0.1 and can_spoof_buy:
            self.spoof_side = 'BUY'          # fake buying pressure -> price up
        elif imbalance >= -0.1 and can_spoof_sell:
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
# Part F: Green Manipulator (greenwashing momentum-ignition FSM)
# --------------------------------------------------------------------------- #
class GreenManipulator(Manipulator):
    """
    Multi-asset spoofer specialised in sustainable narrative cycles.

    Target selection replaces the generic depth-imbalance read: in
    STATE_IDLE the agent scores every listed asset's *green sentiment* --
    its green score plus event boosts for a recent state subsidy or a
    recent corporate transition step -- and attacks the hottest narrative
    above the regulatory threshold. This covers both genuinely green
    assets and "greenwashed" brown assets whose transition announcements
    are freshly in the news.

    The attack plants a massive fake BUY wall below the mid on the target
    asset (manufacturing an artificial sustainable rally for the
    imbalance-following noise/chartist crowd); once the induced move
    clears the harvest threshold, the wall is pulled and an aggressive
    market SELL dumps inventory into the manufactured demand, banking the
    green premium before the cooldown.

    Operates exclusively through per-asset `AssetPosition` views, so cash
    stays in the shared wallet and each venue's book sees a normal
    counterparty.
    """

    def __init__(self, trader_id: str, cash: float, shares: int,
                 spoof_size: int = 400, spoof_offset: float = 0.03,
                 attack_size: int = 40, cooldown: int = 6,
                 patience: int = 3, current_day: int = 0):
        super().__init__(trader_id, cash, shares, spoof_size=spoof_size,
                         spoof_offset=spoof_offset, attack_size=attack_size,
                         cooldown=cooldown, patience=patience,
                         current_day=current_day)
        self._target_venue = None      # Venue under attack while SPOOFING
        self.green_spoofs = 0          # Ignitions launched (audit)
        self.green_harvests = 0        # Successful premium harvests (audit)

    @staticmethod
    def green_sentiment(asset, current_day: int) -> float:
        """Green score plus news boosts for recent subsidy/transition."""
        sentiment = asset.green_score
        if current_day - asset.last_subsidy_day \
                <= GREEN_SENTIMENT_WINDOW_DAYS:
            sentiment += GREEN_SENTIMENT_EVENT_BOOST
        if current_day - asset.last_transition_day \
                <= GREEN_SENTIMENT_WINDOW_DAYS:
            sentiment += GREEN_SENTIMENT_EVENT_BOOST
        return sentiment

    def act_green(self, venues: list, current_day: int) -> None:
        """Advances the greenwashing state machine by one trading day."""
        if current_day < self.next_active_day:
            return
        if self.state == self.STATE_IDLE:
            self._try_start_green_spoof(venues, current_day)
        elif self.state == self.STATE_SPOOFING:
            self._manage_green_spoof(current_day)

    def _try_start_green_spoof(self, venues: list,
                               current_day: int) -> None:
        # Hottest green narrative above the regulatory threshold wins.
        target, best = None, STATE_GREEN_THRESHOLD
        for venue in venues:
            sentiment = self.green_sentiment(venue.asset, current_day)
            if sentiment >= best:
                target, best = venue, sentiment
        if target is None:
            return

        book = target.order_book
        mid = book.get_midpoint(target.asset.get_last_price())
        position = self.positions[target.symbol]
        # Local economic state first (cash escrow for the wall, inventory
        # for the later dump) -- no book scan happens before this gate.
        if self.cash <= mid * self.spoof_size \
                or position.shares < self.attack_size:
            return

        price = max(0.01, round(mid * (1.0 - self.spoof_offset), 2))
        oid = book.get_next_order_id()
        order = LimitOrder(oid, self.trader_id, 'BUY', price,
                           self.spoof_size, current_day)
        book.add_limit_order(order, target.trader_map, current_day)

        if book.orders.get(oid) is not None and order.active:
            self.spoof_order_id = oid
            self.spoof_side = 'BUY'
            self.state = self.STATE_SPOOFING
            self.spoof_started_day = current_day
            self.mid_at_spoof = mid
            self._target_venue = target
            self.green_spoofs += 1
        else:
            self._cancel_spoof(book, target.trader_map)

    def _manage_green_spoof(self, current_day: int) -> None:
        venue = self._target_venue
        book = venue.order_book
        if not self._spoof_order_alive(book):
            self._reset_cycle(current_day)
            return

        mid = book.get_midpoint(venue.asset.get_last_price())
        move = (mid - self.mid_at_spoof) / self.mid_at_spoof
        elapsed = current_day - self.spoof_started_day

        if move >= 0.004:      # The manufactured rally is harvestable.
            self._cancel_spoof(book, venue.trader_map)
            position = self.positions[venue.symbol]
            qty = min(self.attack_size, position.shares)
            if qty > 0:
                book.execute_market_order(
                    MarketOrder(self.trader_id, 'SELL', qty),
                    venue.trader_map, current_day)
                self.green_harvests += 1
            self._reset_cycle(current_day)
        elif elapsed >= self.patience:
            self._cancel_spoof(book, venue.trader_map)
            self._reset_cycle(current_day)

    def _reset_cycle(self, current_day: int) -> None:
        super()._reset_cycle(current_day)
        self._target_venue = None
