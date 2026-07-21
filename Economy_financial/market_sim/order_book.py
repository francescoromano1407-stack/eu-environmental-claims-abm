"""
High-performance P2P Limit Order Book.

Bisect-maintained price-time priority arrays with O(1) best-level access,
O(log N) banded depth queries, lazy tombstone cancellation with relative
(amortized O(1)) compaction, and exact double-entry escrow settlement
under dynamic friction (Part D, fix 1).

Circular-dependency note: the book operates on `LimitOrder`/`MarketOrder`
instances and a `trader_map` of participants, but it never constructs
traders and never imports `traders` at runtime. Order types are needed
only for annotations, so they are imported under `TYPE_CHECKING` (all
annotations are lazy via `from __future__ import annotations`).
"""

from __future__ import annotations

import bisect
from typing import TYPE_CHECKING, Any, Callable, Optional

from market_sim.constants import (
    BASE_COMMISSION_RATE,
    IMBALANCE_BAND,
    TOBIN_HOLDING_DAYS,
    TOBIN_TAX_RATE,
)
from market_sim.models import MarketOrder

if TYPE_CHECKING:
    from market_sim.models import LimitOrder


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
    when it surfaces at the top of the book or during compaction. The
    compaction trigger is *relative*: a sweep runs only when tombstones
    exceed COMPACT_RATIO of all resting entries (with a small absolute
    floor), so the O(N) rebuild is amortized O(1) per cancellation at any
    book size while cache locality stays bounded.

    Part D, fix 1 -- dynamic friction with exact escrow accounting:
    `commission_rate` and `tobin_rate` are set daily by the Simulation.
    Takers pay the rate in force at execution. Makers' cash escrow is taken
    at the rate in force at placement, tracked exactly on the order
    (`escrow_remaining`): every partial fill deducts its slice, and the
    final fill or cancellation releases exactly the remainder, so escrowed
    cash telescopes bit-for-bit -- no cash can appear or vanish through
    partial-fill rounding (this replaces the old refund-truncation guard,
    which silently destroyed precision residue).

    `total_fees_collected` accumulates the exact cash removed from the
    participants' combined ledgers by commissions and Tobin taxes, enabling
    closed-system conservation audits.
    """

    COMPACT_THRESHOLD = 256   # Retained for API compatibility (legacy abs.)
    COMPACT_MIN_DEAD = 64     # Never sweep for fewer tombstones than this.
    COMPACT_RATIO = 0.20      # Sweep when dead / total entries exceeds this.

    def __init__(self):
        self._bids: list[tuple] = []
        self._asks: list[tuple] = []
        self.orders: dict[int, LimitOrder] = {}   # Active orders by id
        self._dead = 0                            # Tombstones awaiting sweep
        self.order_id_counter = 0
        self.commission_rate = BASE_COMMISSION_RATE
        self.tobin_rate = TOBIN_TAX_RATE
        self.total_fees_collected = 0.0           # Exact fee/tax drain audit
        # Optional clearing-house hook (Part E). Duck-typed one-way slot:
        # the book never imports the credit module; when set, every
        # settlement notifies it in O(1) so leveraged positions can be
        # margin-checked on each mark move. None => zero overhead.
        self.clearing_house = None
        # Optional research-only event observer.  It is unset in every
        # production/LHS run and receives only order-book state that is
        # already available to the matching engine.  It cannot feed values
        # back into agents or change matching/settlement decisions.
        self.event_sink: Optional[Callable[[dict[str, Any]], None]] = None
        self.observation_day: Optional[int] = None

    def set_event_sink(
            self, sink: Optional[Callable[[dict[str, Any]], None]]) -> None:
        """Attach/detach a passive order-event observer."""
        self.event_sink = sink

    def set_observation_day(self, day: Optional[int]) -> None:
        """Set passive calendar context for legacy APIs lacking a day arg."""
        self.observation_day = None if day is None else int(day)

    def _emit_event(self, event_type: str, current_day: Optional[int],
                    **values: Any) -> None:
        sink = self.event_sink
        if sink is None:
            return
        # Never call best_bid/best_ask here: those methods intentionally
        # skim lazy tombstones and would let an observer mutate matching
        # state.  This reverse scan is slower but strictly passive and is
        # paid only when validation logging is explicitly enabled.
        bid = next((order for _, order in reversed(self._bids)
                    if order.active and order.quantity > 0), None)
        ask = next((order for _, order in reversed(self._asks)
                    if order.active and order.quantity > 0), None)
        best_bid = bid.price if bid is not None else None
        best_ask = ask.price if ask is not None else None
        bid_depth = sum(order.quantity for _, order in self._bids
                        if order.active and order.quantity > 0)
        ask_depth = sum(order.quantity for _, order in self._asks
                        if order.active and order.quantity > 0)
        sink({
            "day": int(current_day) if current_day is not None else None,
            "event_type": event_type,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": (best_ask - best_bid)
            if best_bid is not None and best_ask is not None else None,
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "mid_price": ((best_bid + best_ask) / 2.0)
            if best_bid is not None and best_ask is not None
            else (best_bid if best_bid is not None else best_ask),
            **values,
        })

    def _emit_fill(self, order_id: Optional[int], trader_id: str,
                   side: str, order_type: str, limit_price: Optional[float],
                   remaining: int, original: int, executed: int,
                   execution_price: float, current_day: int,
                   counterparty_order_id: Optional[int],
                   trade_sign: int,
                   mid_price_before: Optional[float]) -> None:
        common = {
            "order_id": order_id,
            "counterparty_order_id": counterparty_order_id,
            "trader_id": trader_id,
            "side": side,
            "order_type": order_type,
            "limit_price": limit_price,
            "quantity": original,
            "executed_quantity": executed,
            "execution_price": execution_price,
            "mid_price_before": mid_price_before,
        }
        self._emit_event(
            "trade", current_day, trade_volume=executed,
            trade_sign=trade_sign, **common)
        self._emit_event(
            "full_execution" if remaining == 0 else "partial_execution",
            current_day, trade_volume=None, trade_sign=None, **common)

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
        """
        Total active quantity on one side within `band` of the mid.

        O(log N + M): the band boundary is located with a binary search on
        the sorted key arrays (the in-band region is always a suffix, since
        the best order sits at the end), then only the M in-band entries
        are summed -- no linear scan of the full side.
        """
        total = 0
        if side == 'BUY':
            # Bid keys ascend with price: in-band == price >= floor_price.
            # The probe key (floor_price,) sorts before every real key with
            # that price, so bisect_left lands on the band's first entry.
            floor_price = mid * (1.0 - band)
            entries = self._bids
            lo = bisect.bisect_left(entries, ((floor_price,),))
        else:
            # Ask keys ascend with -price: in-band == price <= cap_price.
            cap_price = mid * (1.0 + band)
            entries = self._asks
            lo = bisect.bisect_left(entries, ((-cap_price,),))
        for i in range(lo, len(entries)):
            order = entries[i][1]
            if order.active and order.trader_id != exclude_trader:
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
        """Cancels a resting order and refunds its escrow exactly. O(1)."""
        order = self.orders.get(order_id)
        if order is None or not order.active:
            return False

        trader = trader_map[order.trader_id]
        cancelled_quantity = order.quantity
        if order.side == 'BUY':
            # Release exactly the cash still escrowed against this order:
            # the telescoped remainder after all partial fills. No
            # truncation guard is needed (or permitted -- it destroyed
            # precision residue instead of conserving it).
            refund = order.escrow_remaining
            order.escrow_remaining = 0.0
            trader.cash_reserved -= refund
            trader.cash += refund
        else:
            trader.shares_reserved -= order.quantity
            trader.shares += order.quantity

        trader.active_orders.discard(order_id)
        order.active = False
        del self.orders[order_id]
        self._dead += 1
        if (self._dead >= self.COMPACT_MIN_DEAD
                and self._dead >= self.COMPACT_RATIO
                * (len(self._bids) + len(self._asks))):
            self._compact()
        self._emit_event(
            "cancellation", self.observation_day,
            order_id=order.order_id, counterparty_order_id=None,
            trader_id=order.trader_id, side=order.side,
            order_type="LIMIT", limit_price=order.price,
            quantity=cancelled_quantity, executed_quantity=0,
            execution_price=None, trade_volume=None, trade_sign=None)
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

        The top-of-book reference is cached across iterations of the
        matching loop and re-polled only when the standing order is fully
        consumed, avoiding a redundant best-level lookup per fill.
        """
        trades = []
        submitted_quantity = order.quantity
        self._emit_event(
            "order_submission", current_day, order_id=order.order_id,
            counterparty_order_id=None, trader_id=order.trader_id,
            side=order.side, order_type="LIMIT", limit_price=order.price,
            quantity=submitted_quantity, executed_quantity=0,
            execution_price=None, trade_volume=None, trade_sign=None)

        if order.side == 'BUY':
            best = self.best_ask()
            while (order.quantity > 0 and best is not None
                    and order.price >= best.price):
                trade_price = best.price            # Maker's price
                trade_qty = min(order.quantity, best.quantity)
                mid_before = self.get_midpoint(trade_price)
                self.execute_trade(order.trader_id, best.trader_id,
                                   trade_price, trade_qty, current_day,
                                   trader_map, buyer_is_maker=False,
                                   seller_is_maker=True, maker_order=best)
                trades.append((current_day, trade_price, trade_qty))
                order.quantity -= trade_qty
                best.quantity -= trade_qty
                self._emit_fill(
                    order.order_id, order.trader_id, order.side, "LIMIT",
                    order.price, order.quantity, submitted_quantity,
                    trade_qty, trade_price, current_day, best.order_id, 1,
                    mid_before)
                if best.quantity == 0:
                    self._retire_top('SELL', trader_map)
                    best = self.best_ask()

            if order.quantity > 0:
                buyer = trader_map[order.trader_id]
                order.escrow_rate = self.commission_rate
                escrow = order.price * order.quantity \
                    * (1.0 + order.escrow_rate)
                order.escrow_remaining = escrow
                buyer.cash -= escrow
                buyer.cash_reserved += escrow
                bisect.insort(self._bids, (self._bid_key(order), order))
                self.orders[order.order_id] = order
                buyer.active_orders.add(order.order_id)

        else:  # SELL
            best = self.best_bid()
            while (order.quantity > 0 and best is not None
                    and order.price <= best.price):
                trade_price = best.price
                trade_qty = min(order.quantity, best.quantity)
                mid_before = self.get_midpoint(trade_price)
                self.execute_trade(best.trader_id, order.trader_id,
                                   trade_price, trade_qty, current_day,
                                   trader_map, buyer_is_maker=True,
                                   seller_is_maker=False, maker_order=best)
                trades.append((current_day, trade_price, trade_qty))
                order.quantity -= trade_qty
                best.quantity -= trade_qty
                self._emit_fill(
                    order.order_id, order.trader_id, order.side, "LIMIT",
                    order.price, order.quantity, submitted_quantity,
                    trade_qty, trade_price, current_day, best.order_id, -1,
                    mid_before)
                if best.quantity == 0:
                    self._retire_top('BUY', trader_map)
                    best = self.best_bid()

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
        submitted_quantity = order.quantity
        self._emit_event(
            "order_submission", current_day, order_id=None,
            counterparty_order_id=None, trader_id=order.trader_id,
            side=order.side, order_type="MARKET", limit_price=None,
            quantity=submitted_quantity, executed_quantity=0,
            execution_price=None, trade_volume=None, trade_sign=None)

        if order.side == 'BUY':
            buyer = trader_map[order.trader_id]
            best = self.best_ask()
            while order.quantity > 0 and best is not None:
                trade_price = best.price
                trade_qty = min(order.quantity, best.quantity)
                mid_before = self.get_midpoint(trade_price)
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
                self._emit_fill(
                    None, order.trader_id, order.side, "MARKET", None,
                    order.quantity, submitted_quantity, trade_qty,
                    trade_price, current_day, best.order_id, 1, mid_before)
                if best.quantity == 0:
                    self._retire_top('SELL', trader_map)
                    best = self.best_ask()

        else:  # SELL
            best = self.best_bid()
            while order.quantity > 0 and best is not None:
                trade_price = best.price
                trade_qty = min(order.quantity, best.quantity)
                mid_before = self.get_midpoint(trade_price)
                self.execute_trade(best.trader_id, order.trader_id,
                                   trade_price, trade_qty, current_day,
                                   trader_map, buyer_is_maker=True,
                                   seller_is_maker=False, maker_order=best)
                trades.append((current_day, trade_price, trade_qty))
                order.quantity -= trade_qty
                best.quantity -= trade_qty
                self._emit_fill(
                    None, order.trader_id, order.side, "MARKET", None,
                    order.quantity, submitted_quantity, trade_qty,
                    trade_price, current_day, best.order_id, -1, mid_before)
                if best.quantity == 0:
                    self._retire_top('BUY', trader_map)
                    best = self.best_bid()

        return trades

    # -- clearing house (Part E): forced liquidation ---------------------------#
    def force_liquidation(self, trader_id: str, qty: int, trader_map: dict,
                          current_day: int) -> float:
        """
        Forced Liquidation State (clearing-house rule):
          1. instantly cancels ALL of the trader's resting limit orders
             (refunding their escrow into free cash as always), then
          2. dumps `qty` shares into the active bids with an automated
             market order.
        Returns the exact net cash proceeds of the dump (sale revenue
        after commission/Tobin tax), measured as the trader's cash delta,
        so the caller can hard-route it into the outstanding liability.
        """
        trader = trader_map[trader_id]
        for oid in list(trader.active_orders):
            self.cancel_order(oid, trader_map)
        cash_before = trader.cash
        qty = min(qty, trader.shares)
        if qty > 0:
            self.execute_market_order(
                MarketOrder(trader_id, 'SELL', qty), trader_map, current_day)
        return trader.cash - cash_before

    # -- settlement ----------------------------------------------------------#
    def execute_trade(self, buyer_id: str, seller_id: str, price: float,
                      qty: int, current_day: int, trader_map: dict,
                      buyer_is_maker: bool, seller_is_maker: bool,
                      maker_order: Optional[LimitOrder] = None) -> None:
        """
        Double-entry settlement: cash, shares, commissions, Tobin tax.

        A maker-buyer settles out of the exact escrow tracked on the
        resting order: each partial fill deducts its slice from
        `escrow_remaining` and the final fill consumes exactly the
        remainder, so the sum of all releases equals the amount escrowed at
        placement bit-for-bit. Takers pay the current dynamic commission.
        Absolute conservation holds either way.
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
        if buyer_is_maker and maker_order is not None:
            # Cash was escrowed at the resting bid's price == trade price,
            # at the commission rate frozen on the order at placement. A
            # fill that consumes the whole order releases exactly the
            # remaining escrow (exact telescoping); partial fills release
            # their proportional slice.
            if qty == maker_order.quantity:
                release = maker_order.escrow_remaining
            else:
                release = price * qty * (1.0 + maker_order.escrow_rate)
            maker_order.escrow_remaining -= release
            buyer.cash_reserved -= release
            buyer_paid = release
        else:
            buyer_paid = trade_value * (1.0 + self.commission_rate)
            buyer.cash -= buyer_paid
        buyer.shares += qty
        buyer.shares_ledger.append((current_day, qty, price))

        # Seller side.
        if seller_is_maker:
            seller.shares_reserved -= qty
        else:
            seller.shares -= qty
        seller_proceeds = trade_value - seller_commission - tobin_tax
        seller.cash += seller_proceeds

        # Exact fee drain: what left the buyer minus what reached the
        # seller is precisely the cash removed from the closed system.
        self.total_fees_collected += buyer_paid - seller_proceeds

        # Part E: notify the clearing house that the mark moved (O(1)
        # flag set -- margin sweeps run from the simulation loop, never
        # re-entrantly inside matching).
        clearing_house = self.clearing_house
        if clearing_house is not None:
            clearing_house.notify_trade(price)
