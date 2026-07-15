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

from decimal import Decimal

from market_sim.constants import (
    BASE_COMMISSION_RATE,
    CORPORATE_BALANCE_FLOOR,
    GREEN_CAPEX_FACTOR,
    LOG_CORPORATE_BALANCE_FLOOR,
    REG_OMISSION_RATE_DEFAULT,
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

    Part G, WP1.2 -- the single Part F `green_score` is split into:

      `true_green_score`       Drives real cash flows: CAPEX actually
                               spent (WP5 transition machinery and the
                               historical GREEN_CAPEX_FACTOR listing
                               penalty), certification maintenance, and
                               what an audit measures.
      `disclosed_green_score`  Drives market perception: the greenium
                               (traders, WP3), sovereign-fund eligibility
                               and subsidy allocation (State), bank risk
                               weights (WP7), green-bond spillovers (WP6),
                               and the GreenManipulator's sentiment.

    Re-pointing decisions for every legacy consumer of `green_score`:
      - `Trader._decide_fundamentalist` greenium  -> DISCLOSED (perception)
      - `Trader._decide_noise` green tilt (new)   -> DISCLOSED (perception)
      - `State.pay_subsidies` allocation          -> DISCLOSED (WP2.b exploit)
      - `State.invest_green` eligibility          -> DISCLOSED (WP3 reliance)
      - `GreenManipulator.green_sentiment`        -> DISCLOSED (narrative)
      - `CommercialBank` reserve weights (WP7)    -> DISCLOSED (model risk)
      - `GREEN_CAPEX_FACTOR` listing penalty      -> TRUE (real CAPEX spent)
      - WP5 NPV transition dynamics / maintenance -> TRUE (physical state)
      - Audits (`ESGRegulation`)                  -> compare DISCLOSED vs TRUE
    The legacy `green_score` property remains as a read alias of the
    DISCLOSED score (everything a market participant can observe); with
    the regulation layer off the two scores are identical by construction,
    so pre-Part-G behavior is preserved.
    """

    def __init__(self, symbol: str, initial_price: float = 100.0,
                 initial_balance: float = 300_000.0,
                 fundamental_drift: float = 0.00010,
                 fundamental_reversion: float = 0.015,
                 fundamental_vol: float = 0.005,
                 green_score: float = 0.0,
                 firm_size: Optional[float] = None,
                 omission_rate: float = REG_OMISSION_RATE_DEFAULT):
        self.symbol = symbol
        # Part F / Part G: sustainability profile in [0, 1]. At listing the
        # disclosed score equals the true score (no wedge yet); the wedge
        # can only open through CorporatePolicy disclosure (WP2).
        score = min(1.0, max(0.0, float(green_score)))
        self._true_green_score = score
        self._disclosed_green_score = score
        self.last_subsidy_day = -10**9      # Set by the State layer.
        self.last_transition_day = -10**9   # Set by real transitions (WP5).
        self.last_disclosure_day = -10**9   # Set by CorporatePolicy (WP2).
        self.last_upgrade_day = -10**9      # Set when a disclosure RAISES d.
        self.last_scandal_day = -10**9      # Set on audit detection (WP1.5).
        # WP1.4 -- lawful omission state: fraction of downward revisions a
        # firm may withhold, and the capped buffer of lawfully omitted
        # score that audits must not count as misreporting.
        self.omission_rate = omission_rate
        self.lawful_omission = 0.0
        # Historical capital penalty: pre-listing sustainable CAPEX
        # structurally reduces the opening balance sheet. Re-pointed to the
        # TRUE score (WP1.2): only real CAPEX shrinks a balance sheet.
        # Exactly neutral for score == 0 (multiplier 1.0 is exact).
        initial_balance = initial_balance \
            * (1.0 - GREEN_CAPEX_FACTOR * self._true_green_score)
        # WP1.1 -- firm size proxy (STYLIZATION: the directive scopes by
        # net turnover and headcount; the simulation proxies both with the
        # corporate balance at listing, overridable per asset_profile).
        self.firm_size = float(firm_size) if firm_size is not None \
            else initial_balance
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

    @property
    def green_score(self) -> float:
        """Legacy alias: what the market can observe is the DISCLOSED
        score (WP1.2). Identical to the true score while no wedge exists."""
        return self._disclosed_green_score

    @property
    def true_green_score(self) -> float:
        """Physical sustainability state; moves only through real CAPEX
        (WP5 continuous dynamics or the legacy transition step)."""
        return self._true_green_score

    @property
    def disclosed_green_score(self) -> float:
        """Reported sustainability; moves only through CorporatePolicy
        disclosure (WP2) or a scandal reset (WP1.5)."""
        return self._disclosed_green_score

    @property
    def wedge(self) -> float:
        """Raw disclosed-minus-true gap (>= 0 for inflating firms)."""
        return self._disclosed_green_score - self._true_green_score

    @property
    def unlawful_wedge(self) -> float:
        """The audit-relevant wedge: the raw gap net of the lawful
        omission buffer (WP1.4), floored at zero."""
        gap = self.wedge - self.lawful_omission
        return gap if gap > 0.0 else 0.0

    def apply_green_transition(self, increment: float, cost: float,
                               current_day: int) -> None:
        """
        Executes one REAL corporate transition step: pays `cost` out of
        the balance sheet (the property setter keeps the log-space OU
        state in sync) and permanently raises the TRUE green score. The
        caller is responsible for the solvency-floor check. The disclosed
        score follows in lock-step here (a real, announced improvement);
        strategic divergence happens only in CorporatePolicy.disclose().
        """
        self.balance -= cost
        self._true_green_score = min(
            1.0, self._true_green_score + increment)
        if self._disclosed_green_score < self._true_green_score:
            self._disclosed_green_score = self._true_green_score
        self.last_transition_day = current_day

    def set_true_score(self, value: float) -> None:
        """WP5 continuous-dynamics write path for the physical score."""
        self._true_green_score = min(1.0, max(0.0, value))

    def set_disclosed_score(self, value: float, current_day: int) -> None:
        """WP2 disclosure write path for the reported score. Upward
        revisions additionally stamp `last_upgrade_day` -- the "hot
        narrative" signal the GreenManipulator and the WP3 wedge-suspicion
        check both consume."""
        value = min(1.0, max(0.0, value))
        if value > self._disclosed_green_score:
            self.last_upgrade_day = current_day
        self._disclosed_green_score = value
        self.last_disclosure_day = current_day

    def apply_scandal(self, current_day: int) -> None:
        """WP1.5 forced reset on detection: disclosed := true, lawful
        omission buffer wiped, scandal timestamp marked."""
        self._disclosed_green_score = self._true_green_score
        self.lawful_omission = 0.0
        self.last_scandal_day = current_day

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


class AssetPosition:
    """
    Per-(holder, asset) ledger view for the multi-asset ecosystem (Part F).

    Presents exactly the surface the OrderBook mutates during matching and
    settlement -- `shares`, `shares_reserved`, `shares_ledger`,
    `active_orders`, `cash`, `cash_reserved` -- holding the share-side
    state per asset while delegating every cash field to the owner's
    single shared wallet. Each asset's book therefore operates on these
    views through its own trader_map and the matching engine stays
    byte-identical, while cash conservation holds across the whole
    portfolio automatically.

    Credit-facing surface (`debt`, `cash_lent`, `get_equity`,
    `pledge_collateral`) is also exposed so the existing CreditMarket can
    margin-lend against the primary listing without modification.
    """

    __slots__ = ("owner", "book", "book_map", "shares", "shares_reserved",
                 "shares_collateral", "shares_ledger", "active_orders")

    def __init__(self, owner, shares: int = 0, current_day: int = 0):
        self.owner = owner
        self.book = None            # Bound by the venue after construction
        self.book_map = None        # The venue's trader_map (for cancels)
        self.shares = int(shares)
        self.shares_reserved = 0
        self.shares_collateral = 0
        self.shares_ledger: collections.deque = collections.deque()
        if self.shares > 0:
            self.shares_ledger.append((current_day, self.shares, 100.0))
        self.active_orders: set[int] = set()

    # -- cash surface: pure delegation to the owner's shared wallet -------- #
    @property
    def cash(self) -> float:
        return self.owner.cash

    @cash.setter
    def cash(self, value: float) -> None:
        self.owner.cash = value

    @property
    def cash_reserved(self) -> float:
        return self.owner.cash_reserved

    @cash_reserved.setter
    def cash_reserved(self, value: float) -> None:
        self.owner.cash_reserved = value

    @property
    def cash_lent(self) -> float:
        return self.owner.cash_lent

    @cash_lent.setter
    def cash_lent(self, value: float) -> None:
        self.owner.cash_lent = value

    @property
    def debt(self) -> float:
        return self.owner.debt

    @debt.setter
    def debt(self, value: float) -> None:
        self.owner.debt = value

    # -- identity delegation ------------------------------------------------ #
    @property
    def trader_id(self) -> str:
        return self.owner.trader_id

    @property
    def type(self) -> str:
        return self.owner.type

    # -- accounting ---------------------------------------------------------- #
    @property
    def total_cash(self) -> float:
        return self.owner.cash + self.owner.cash_reserved

    @property
    def total_shares(self) -> int:
        return self.shares + self.shares_reserved + self.shares_collateral

    def get_wealth(self, current_price: float) -> float:
        """Owner cash + receivables + THIS position marked at `price`."""
        return (self.total_cash + self.owner.cash_lent
                + self.total_shares * current_price)

    def get_equity(self, current_price: float) -> float:
        """Conservative equity: this position + wallet, net of all debt."""
        return self.get_wealth(current_price) - self.owner.debt

    def pledge_collateral(self, qty: int) -> None:
        self.shares -= qty
        self.shares_collateral += qty

    def release_collateral(self, qty: int) -> None:
        self.shares_collateral -= qty
        self.shares += qty

    def __repr__(self) -> str:
        return (f"AssetPosition(owner={self.owner.trader_id}, "
                f"shares={self.shares}, reserved={self.shares_reserved}, "
                f"collateral={self.shares_collateral})")


class GreenBond:
    """
    Sovereign green bond (Part G, WP6). `__slots__` value object.

    Issued at par by the `State` under the EU green-bond framework
    stylization (Regulation (EU) 2023/2631, left in force by the Omnibus
    directive). The Decimal face value is the accounting canon; `face` is
    the float mirror used in hot-loop reserve arithmetic (WP7). The
    use-of-proceeds tag documents the earmarking constraint enforced by
    the State's `green_proceeds_dec` sub-ledger.
    """

    __slots__ = ("bond_id", "holder_id", "face_dec", "face", "coupon_rate",
                 "issue_day", "maturity_day", "use_of_proceeds",
                 "coupons_paid_dec", "rolled", "active")

    def __init__(self, bond_id: int, holder_id: str, face_dec: Decimal,
                 coupon_rate: float, issue_day: int, maturity_day: int,
                 use_of_proceeds: str = "green_subsidies_and_fund"):
        self.bond_id = bond_id
        self.holder_id = holder_id          # Buyer trader_id or 'BANK'
        self.face_dec = face_dec
        self.face = float(face_dec)         # Hot-loop float mirror (WP7 RR)
        self.coupon_rate = coupon_rate      # Annual; policy rate - greenium
        self.issue_day = issue_day
        self.maturity_day = maturity_day
        self.use_of_proceeds = use_of_proceeds
        self.coupons_paid_dec = Decimal("0")
        self.rolled = 0                     # Sovereign-stress roll count
        self.active = True

    def __repr__(self) -> str:
        return (f"GreenBond(id={self.bond_id}, holder={self.holder_id}, "
                f"face={self.face_dec}, coupon={self.coupon_rate:.4f}, "
                f"maturity={self.maturity_day})")


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
