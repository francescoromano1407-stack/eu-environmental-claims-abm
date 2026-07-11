"""
State / government climate intervention layer (Part F).

The `State` is a programmatic fiscal entity -- it never places retail
limit orders. It wields two instruments:

  Subsidies              -- every EVOLUTION_EPOCH_DAYS, an epoch budget is
                            split across listed companies proportionally
                            to their green scores and injected straight
                            into the corporate balance sheets (the OU
                            property setter keeps the log-space state in
                            sync). Cent-quantized Decimal, exact ledger.
  Sovereign green fund   -- a daily investment budget crosses the spread
                            with automated MarketOrder BUYs, exclusively
                            on assets whose green_score clears the
                            regulatory threshold, mechanically supporting
                            green market prices.

Double-entry discipline: the treasury has a Decimal canon and a float
mirror. Subsidies move treasury -> corporate balance (a tracked drain on
the participants' cash universe, symmetric to how dividends are a
tracked injection); market purchases settle through a normal per-venue
`AssetPosition` view, so the cash simply changes hands inside the system.

Circular-dependency note: imports `constants` and `models.MarketOrder` at
runtime; `Trader` only under TYPE_CHECKING. Venues are duck-typed.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import TYPE_CHECKING

from market_sim.constants import (
    CREDIT_CENT_DEC,
    STATE_DAILY_INVESTMENT_DEC,
    STATE_GREEN_THRESHOLD,
    STATE_SUBSIDY_EPOCH_BUDGET_DEC,
    STATE_TREASURY_DEC,
)
from market_sim.models import MarketOrder

if TYPE_CHECKING:
    from market_sim.traders import Trader

_ZERO = Decimal("0")

STATE_ID = "T_STATE"


class State:
    """Sovereign climate-policy agent (fiscal + green-fund instruments)."""

    __slots__ = ("ledger", "treasury_dec", "total_subsidies_dec",
                 "total_invested_dec", "subsidy_events", "buy_events")

    def __init__(self, ledger: "Trader"):
        # The ledger is a plain Trader shell (type='state' has no decision
        # handler, so it can never emit retail orders); its cash wallet IS
        # the treasury's float mirror and settles all fund purchases.
        self.ledger = ledger
        self.treasury_dec = STATE_TREASURY_DEC
        self.total_subsidies_dec = _ZERO
        self.total_invested_dec = _ZERO
        self.subsidy_events = 0
        self.buy_events = 0

    # -- instrument 1: green-scaled corporate subsidies ---------------------- #
    def pay_subsidies(self, venues: list, current_day: int) -> float:
        """
        Splits the epoch budget across companies proportionally to their
        green scores and injects it into the corporate balance sheets.
        Returns the exact float total drained from the treasury.
        """
        total_score = sum(v.asset.green_score for v in venues)
        if total_score <= 0.0:
            return 0.0
        budget = min(STATE_SUBSIDY_EPOCH_BUDGET_DEC, self.treasury_dec)
        if budget <= _ZERO:
            return 0.0

        paid = _ZERO
        for venue in venues:
            share = venue.asset.green_score / total_score
            subsidy_dec = (budget * Decimal(repr(round(share, 9)))).quantize(
                CREDIT_CENT_DEC, rounding=ROUND_DOWN)
            if subsidy_dec <= _ZERO:
                continue
            venue.asset.balance += float(subsidy_dec)
            venue.asset.last_subsidy_day = current_day
            paid += subsidy_dec

        self.treasury_dec -= paid
        self.total_subsidies_dec += paid
        self.ledger.cash -= float(paid)      # Float mirror stays in step.
        self.subsidy_events += 1
        return float(paid)

    # -- instrument 2: sovereign green fund (direct market investment) ------- #
    def invest_green(self, venues: list, current_day: int) -> None:
        """
        Crosses the spread with automated market BUYs on every asset whose
        green score clears the regulatory sustainability threshold. The
        daily budget is split evenly across eligible assets; quantities
        are sized against the current best ask plus taker commission.
        """
        eligible = [v for v in venues
                    if v.asset.green_score >= STATE_GREEN_THRESHOLD]
        if not eligible:
            return
        budget_each = float(STATE_DAILY_INVESTMENT_DEC) / len(eligible)

        for venue in eligible:
            book = venue.order_book
            best_ask = book.best_ask()
            if best_ask is None:
                continue
            cost_per_share = best_ask.price * (1.0 + book.commission_rate)
            qty = int(min(budget_each, self.ledger.cash) // cost_per_share)
            if qty <= 0:
                continue
            cash_before = self.ledger.cash
            book.execute_market_order(
                MarketOrder(STATE_ID, 'BUY', qty),
                venue.trader_map, current_day)
            spent = cash_before - self.ledger.cash
            if spent > 0.0:
                self.treasury_dec -= Decimal(repr(round(spent, 9)))
                self.total_invested_dec += Decimal(repr(round(spent, 9)))
                self.buy_events += 1

    # -- reporting ------------------------------------------------------------#
    def treasury(self) -> float:
        """Float mirror of the remaining treasury (O(1))."""
        return float(self.treasury_dec)
