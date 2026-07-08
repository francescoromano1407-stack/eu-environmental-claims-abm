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

import math
import random
from typing import Optional

from market_sim.constants import BASE_COMMISSION_RATE, CORPORATE_BALANCE_FLOOR


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
