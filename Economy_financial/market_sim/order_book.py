"""
High-performance P2P Limit Order Book.

Bisect-maintained price-time priority arrays with O(1) best-level access,
lazy tombstone cancellation with periodic compaction, and exact
double-entry escrow settlement under dynamic friction (Part D, fix 1).

Circular-dependency note: the book operates on `LimitOrder`/`MarketOrder`
instances and a `trader_map` of participants, but it never constructs
traders and never imports `traders` at runtime. Order types are needed
only for annotations, so they are imported under `TYPE_CHECKING` (all
annotations are lazy via `from __future__ import annotations`).
"""

from __future__ import annotations

import bisect
from typing import TYPE_CHECKING, Optional

from market_sim.constants import (
    BASE_COMMISSION_RATE,
    IMBALANCE_BAND,
    TOBIN_HOLDING_DAYS,
    TOBIN_TAX_RATE,
)

if TYPE_CHECKING:
    from market_sim.models import LimitOrder, MarketOrder


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
