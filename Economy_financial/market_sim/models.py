"""
Lightweight data structures and analytical primitives.

Contains the order value objects (`LimitOrder`, `MarketOrder` -- both
`__slots__`-optimized to avoid per-instance dict overhead and preserve
cache locality in large-scale runs), the traded `Asset` with its log-space
Ornstein-Uhlenbeck fundamental process (Part B), and the O(1)
`IncrementalEMA` tracker.

This module sits at the bottom of the package dependency graph: it imports
only `constants` and the standard library.
"""

from __future__ import annotations

import collections
import math
import random
from typing import Optional

from market_sim.constants import (
    BASE_COMMISSION_RATE,
    CORPORATE_BALANCE_FLOOR,
    LOG_CORPORATE_BALANCE_FLOOR,
)

# Bounded history horizon: price/balance histories are capped so unbounded
# runs cannot grow the heap (and thrash the GC) indefinitely. The macro
# orchestrator keeps its own full-length logs for plotting/export; the
# asset only ever needs a localized recent window.
HISTORY_MAXLEN = 4096


class LimitOrder:
    """A resting limit order in the book."""

    __slots__ = ("order_id", "trader_id", "side", "price", "quantity",
                 "timestamp", "active", "escrow_rate", "escrow_remaining")

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
        # Exact remaining cash escrowed against this order. Fills deduct
        # from it and the final fill / cancellation releases exactly what
        # is left, so escrow accounting telescopes bit-for-bit and no cash
        # can be created or destroyed by partial-fill rounding.
        self.escrow_remaining = 0.0

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

    The OU state lives permanently in log space (`_log_balance`): the daily
    step needs no `math.log()` call at all -- only one `math.exp()` to
    expose the nominal `balance`. External writes to `balance` (dividend
    deductions) re-sync the log state through the property setter, which is
    the only remaining `math.log()` site and runs once per dividend event.
    """

    def __init__(self, symbol: str, initial_price: float = 100.0,
                 initial_balance: float = 300_000.0,
                 fundamental_drift: float = 0.00010,
                 fundamental_reversion: float = 0.015,
                 fundamental_vol: float = 0.005):
        self.symbol = symbol
        self.price_history: collections.deque = collections.deque(
            [initial_price], maxlen=HISTORY_MAXLEN)
        self.balance_history: collections.deque = collections.deque(
            [initial_balance], maxlen=HISTORY_MAXLEN)
        self.fundamental_drift = fundamental_drift
        self.fundamental_reversion = fundamental_reversion
        self.fundamental_vol = fundamental_vol
        self._log_floor = LOG_CORPORATE_BALANCE_FLOOR
        self.balance = initial_balance    # Property setter seeds _log_balance
        self._log_anchor = self._log_balance

    # `balance` is a property so external mutations (dividend payouts) keep
    # the log-space OU state consistent without any log() in the daily loop.
    @property
    def balance(self) -> float:
        return self._balance

    @balance.setter
    def balance(self, value: float) -> None:
        if value < CORPORATE_BALANCE_FLOOR:
            value = CORPORATE_BALANCE_FLOOR
            self._log_balance = self._log_floor
        else:
            self._log_balance = math.log(value)
        self._balance = value

    def record_close(self, price: float) -> None:
        """Appends the daily closing price."""
        self.price_history.append(price)

    def update_daily_fundamental(self) -> None:
        """One OU step of the balance-sheet information process (Part B)."""
        self._log_anchor += self.fundamental_drift
        log_b = self._log_balance
        log_b += self.fundamental_reversion * (self._log_anchor - log_b)
        log_b += random.gauss(0.0, self.fundamental_vol)
        if log_b < self._log_floor:
            log_b = self._log_floor
            balance = CORPORATE_BALANCE_FLOOR
        else:
            balance = math.exp(log_b)
        self._log_balance = log_b
        self._balance = balance
        self.balance_history.append(balance)

    def get_last_price(self) -> float:
        """Returns the most recent closing price."""
        return self.price_history[-1]


class IncrementalEMA:
    """
    O(1) incremental exponential moving average.

    Stores only the previous EMA value and an observation counter; one
    `update()` per observation replaces any O(N) history re-scan. The
    complementary decay constant is pre-computed once at construction so
    the hot path performs no repeated subtraction.
    """

    __slots__ = ("alpha", "one_minus_alpha", "value", "count")

    def __init__(self, period: int):
        self.alpha = 2.0 / (period + 1.0)
        self.one_minus_alpha = 1.0 - self.alpha
        self.value: Optional[float] = None
        self.count = 0

    def update(self, price: float) -> float:
        """Folds a new observation into the EMA in constant time."""
        value = self.value
        if value is not None:            # Hot path: steady-state fold.
            value = price * self.alpha + value * self.one_minus_alpha
        else:                            # Cold path: first observation only.
            value = price
        self.value = value
        self.count += 1
        return value
