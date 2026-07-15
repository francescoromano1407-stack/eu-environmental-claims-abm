"""
Credit layer (Part E): P2P lending, institutional banking, margin calls.

Three cooperating primitives:

  `CreditLine`      -- one collateralized debt contract (`__slots__`,
                       exact `decimal.Decimal` canon + float hot-loop
                       mirrors kept in lock-step).
  `CommercialBank`  -- institutional lender of last resort. Never places
                       LOB orders; grants revolving credit against
                       mark-to-market wealth under a macroprudential
                       debt-to-equity cap.
  `CreditMarket`    -- coordinator and clearing house: P2P vault
                       commitments, origination with volatility-scaled
                       LTV, endogenous rate discovery, daily compounding
                       accrual/servicing, and endogenous margin calls
                       with forced liquidations.

Exact double-entry discipline: every credit cash flow is decided in
cent-quantized Decimal space and then applied as the *identical* float to
both legs of the transfer (borrower/lender), so the float ledger conserves
bit-for-bit while the Decimal canon provides exact balance verification.
Aggregates (`total_principal_dec`, pool capacity, per-borrower line
index) are maintained incrementally, so rate discovery, utilization, and
leverage checks are O(1) -- no per-line re-summation in any hot path.

Circular-dependency note: this module imports `constants` at runtime
only. `OrderBook` and `Trader` appear strictly under
`typing.TYPE_CHECKING` as forward references; the book and the trader map
are injected into every method that needs them. The
`OrderBook -> CreditMarket` interaction is a duck-typed one-way
`clearing_house` callback slot, so the dependency graph stays acyclic:

    constants <- models <- credit_market
                             ^
                             | (runtime construction, one direction)
                        simulation
"""

from __future__ import annotations

import random
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING, Optional

from market_sim.constants import (
    BANK_INITIAL_CAPITAL_DEC,
    BORROWER_CASH_MULTIPLE,
    COLLATERAL_FRACTION,
    CREDIT_ATTRACTIVENESS_FLOOR,
    CREDIT_BASE_ANNUAL_RATE_DEC,
    CREDIT_CENT_DEC,
    CREDIT_DAY_COUNT,
    CREDIT_LTV_VOL_SENSITIVITY,
    CREDIT_MAX_LINES_PER_BORROWER,
    CREDIT_MAX_LTV,
    CREDIT_MIN_LTV,
    CREDIT_UTILIZATION_ALPHA_DEC,
    MAINTENANCE_MARGIN_RATIO,
    RESERVE_BASE_RATIO_DEC,
    MAX_DEBT_TO_EQUITY,
    MIN_COLLATERAL_SHARES,
    P2P_LENDER_MIN_CASH,
    P2P_VAULT_FRACTION,
    TAYLOR_BETA_PI,
    TAYLOR_BETA_Y,
    TAYLOR_PI_STAR,
    TAYLOR_R_TARGET,
    TAYLOR_RATE_CAP,
    TAYLOR_RATE_FLOOR,
    TAYLOR_SHOCK_SIGMA,
)

if TYPE_CHECKING:
    from market_sim.order_book import OrderBook
    from market_sim.traders import Trader

_ZERO = Decimal("0")
_DAY_COUNT_DEC = Decimal(CREDIT_DAY_COUNT)

BANK_ID = "BANK"


def _dec_cents(value: float) -> Decimal:
    """Exact float -> cent-quantized Decimal (rounded down, conservative)."""
    return Decimal(repr(value)).quantize(CREDIT_CENT_DEC, rounding=ROUND_DOWN)


class CreditLine:
    """
    One collateralized debt contract.

    The Decimal fields are the accounting canon; `principal` /
    `accrued_interest` are float mirrors refreshed on every mutation so
    hot-loop margin checks never touch Decimal arithmetic.
    """

    __slots__ = ("line_id", "borrower_id", "lender_id", "principal_dec",
                 "accrued_interest_dec", "collateral_shares",
                 "origination_day", "principal", "accrued_interest",
                 "active")

    def __init__(self, line_id: int, borrower_id: str, lender_id: str,
                 principal_dec: Decimal, collateral_shares: int,
                 origination_day: int):
        self.line_id = line_id
        self.borrower_id = borrower_id
        self.lender_id = lender_id            # Agent trader_id or 'BANK'
        self.principal_dec = principal_dec
        self.accrued_interest_dec = _ZERO
        self.collateral_shares = collateral_shares
        self.origination_day = origination_day
        self.principal = float(principal_dec)  # Hot-loop float mirror
        self.accrued_interest = 0.0
        self.active = True

    @property
    def debt_dec(self) -> Decimal:
        return self.principal_dec + self.accrued_interest_dec

    @property
    def debt(self) -> float:
        return self.principal + self.accrued_interest

    def sync_mirrors(self) -> None:
        """Refreshes the float mirrors from the Decimal canon."""
        self.principal = float(self.principal_dec)
        self.accrued_interest = float(self.accrued_interest_dec)

    def __repr__(self) -> str:
        return (f"CreditLine(id={self.line_id}, borrower={self.borrower_id}, "
                f"lender={self.lender_id}, debt={self.debt_dec}, "
                f"collateral={self.collateral_shares}, "
                f"day={self.origination_day})")


class CommercialBank:
    """
    Institutional lender of last resort.

    Holds loanable capital as cash (it never places LOB orders), extends
    revolving credit against mark-to-market wealth, and absorbs default
    write-offs. The Decimal fields are the exact canon; `cash` is the
    float mirror participating in the system-wide cash conservation law.

    Part G, WP7 -- green-weighted mandatory reserves ("green supporting
    factor"): `required_reserves_dec` is recomputed daily by the
    CreditMarket from the bank's exposures weighted by the DISCLOSED
    green score of the backing asset (WP3 institutional reliance --
    deliberate model risk: a successful greenwasher lowers MEASURED risk
    while true risk is unchanged). Lending capacity becomes
    `capital - RR` instead of raw capital: `can_fund` subtracts the
    requirement, which is exactly zero (a Decimal identity) whenever the
    regulation layer is off, so the legacy path is bit-identical.
    """

    __slots__ = ("bank_id", "cash", "cash_dec", "loans_outstanding_dec",
                 "interest_income_dec", "writeoffs_dec",
                 # Part G, WP6 + WP7 state.
                 "bond_holdings", "required_reserves_dec",
                 "required_reserves", "reserve_shortfall_events")

    def __init__(self, capital_dec: Decimal = BANK_INITIAL_CAPITAL_DEC):
        self.bank_id = BANK_ID
        self.cash_dec = capital_dec
        self.cash = float(capital_dec)
        self.loans_outstanding_dec = _ZERO
        self.interest_income_dec = _ZERO
        self.writeoffs_dec = _ZERO
        self.bond_holdings: list = []        # GreenBond instruments (WP6)
        self.required_reserves_dec = _ZERO   # WP7 Decimal canon
        self.required_reserves = 0.0         # WP7 float mirror
        self.reserve_shortfall_events = 0    # Systemic-risk audit counter

    def can_fund(self, amount_dec: Decimal) -> bool:
        """Lending capacity net of required reserves (WP7). With the
        regulation layer off the requirement is exactly Decimal 0 and
        this reduces to the legacy `cash_dec >= amount_dec`."""
        return self.cash_dec - self.required_reserves_dec >= amount_dec

    def pay_out(self, amount_dec: Decimal) -> float:
        """Disburses funds; returns the exact float leg of the transfer."""
        leg = float(amount_dec)
        self.cash_dec -= amount_dec
        self.cash -= leg
        self.loans_outstanding_dec += amount_dec
        return leg

    def receive(self, amount_dec: Decimal, principal_dec: Decimal) -> float:
        """
        Receives a payment split into principal repayment and interest
        income; returns the exact float leg of the transfer.
        """
        leg = float(amount_dec)
        self.cash_dec += amount_dec
        self.cash += leg
        self.loans_outstanding_dec -= principal_dec
        self.interest_income_dec += amount_dec - principal_dec
        return leg

    def write_off(self, principal_dec: Decimal, total_dec: Decimal) -> None:
        """Absorbs a default loss (no cash moves; receivable destroyed)."""
        self.loans_outstanding_dec -= principal_dec
        self.writeoffs_dec += total_dec


class CentralBank:
    """
    Monetary-policy engine (Part F): a Taylor rule with Gaussian surprise.

        rate_t = R_target + beta_pi * (pi_t - pi*)
                          + beta_y  * output_gap_t
                          + eps_t,      eps_t ~ N(0, sigma^2)

    `pi_t` is the short-run price-growth gap of the traded economy and
    `output_gap_t` the system trading-volume deviation from its long-run
    baseline, both supplied daily by the Simulation. The Gaussian shock
    injects an unanticipated monetary "surprise" that propagates straight
    into the CreditMarket's borrowing base, stress-testing leveraged
    agents against liquidity tightening. The rate is clamped to
    [TAYLOR_RATE_FLOOR, TAYLOR_RATE_CAP].
    """

    __slots__ = ("policy_rate", "policy_rate_dec", "last_shock",
                 "rate_history")

    def __init__(self):
        self.policy_rate = TAYLOR_R_TARGET
        self.policy_rate_dec = Decimal(repr(TAYLOR_R_TARGET))
        self.last_shock = 0.0
        self.rate_history: list[float] = []

    def update_policy_rate(self, price_gap: float,
                           output_gap: float) -> float:
        """One daily Taylor-rule evaluation; returns the new annual rate."""
        shock = random.gauss(0.0, TAYLOR_SHOCK_SIGMA)
        rate = (TAYLOR_R_TARGET
                + TAYLOR_BETA_PI * (price_gap - TAYLOR_PI_STAR)
                + TAYLOR_BETA_Y * output_gap
                + shock)
        if rate < TAYLOR_RATE_FLOOR:
            rate = TAYLOR_RATE_FLOOR
        elif rate > TAYLOR_RATE_CAP:
            rate = TAYLOR_RATE_CAP
        self.last_shock = shock
        self.policy_rate = rate
        self.policy_rate_dec = Decimal(repr(round(rate, 9)))
        self.rate_history.append(rate)
        return rate


class CreditMarket:
    """
    Credit coordinator and clearing house.

    Daily cycle (invoked once per trading day by the Simulation):
      1. endogenous rate discovery from pool utilization (O(1)),
      2. compounding interest accrual + cash servicing per line,
      3. margin enforcement at the closing mark,
      4. P2P vault re-commitment and new originations.

    Intraday, the OrderBook notifies `notify_trade` (an O(1) flag set) on
    every settlement; `poll_intraday` then runs the margin scan only when
    the mark price actually moved, keeping the per-trader hot loop O(1)
    when nothing happened.
    """

    MAX_CASCADE_PASSES = 8   # Fire-sale cascade safety bound per sweep.

    def __init__(self, bank: CommercialBank, order_book: "OrderBook"):
        self.bank = bank
        self.order_book = order_book
        self.lines: dict[int, CreditLine] = {}
        self._lines_by_borrower: dict[str, set[int]] = {}
        self._line_id_counter = 0

        # Incremental aggregates: O(1) utilization / rate discovery.
        self.total_principal_dec = _ZERO
        self._p2p_capacity: dict[str, float] = {}   # lender_id -> headroom
        self._p2p_available = 0.0

        # Endogenous rate state (annual, plus exact daily Decimal factor).
        self.annual_rate_dec = CREDIT_BASE_ANNUAL_RATE_DEC
        self.annual_rate = float(self.annual_rate_dec)
        self._daily_rate_dec = self.annual_rate_dec / _DAY_COUNT_DEC

        # Clearing-house mark state (set by OrderBook.notify_trade).
        self._mark_price = 0.0
        self._margin_dirty = False

        # Part F: optional monetary-policy anchor. When set, the Taylor
        # rate replaces the static base in rate discovery; None preserves
        # the original engine exactly.
        self.central_bank: Optional[CentralBank] = None

        # Part G, WP7: optional regulation hookup, set by the Simulation
        # in ESG+regulation mode. `esg_regulation` supplies the risk-
        # weight schedule (single source of truth); `collateral_asset` is
        # the asset backing margin collateral (the primary listing in
        # this build). Both None => the reserve machinery never runs and
        # required reserves stay exactly Decimal 0 (legacy-identical).
        self.esg_regulation = None
        self.collateral_asset = None

        # Audit counters (Decimal canon; cash legs mirror into the float
        # ledger as internal transfers, so system cash is unaffected).
        self.total_disbursed_dec = _ZERO
        self.total_interest_collected_dec = _ZERO
        self.total_repaid_dec = _ZERO
        self.total_writeoffs_dec = _ZERO
        self.liquidation_count = 0
        self.denied_leverage_cap = 0

    # -- OrderBook-facing clearing hook (O(1), no re-entrancy) --------------- #
    def notify_trade(self, price: float) -> None:
        """Called by the book after every settlement: marks the ledger dirty."""
        self._mark_price = price
        self._margin_dirty = True

    def poll_intraday(self, trader_map: dict, current_day: int) -> None:
        """Runs the margin scan iff the mark moved since the last poll."""
        if not self._margin_dirty:
            return
        self._margin_dirty = False
        if self.lines:
            self._enforce_margins(self._mark_price, trader_map, current_day)

    # -- leverage / risk metrics --------------------------------------------- #
    @staticmethod
    def max_ltv(rel_volatility: float) -> float:
        """Volatility-scaled LTV ceiling (inverse scaling, clamped)."""
        ltv = CREDIT_MAX_LTV / (1.0 + CREDIT_LTV_VOL_SENSITIVITY
                                * rel_volatility)
        if ltv < CREDIT_MIN_LTV:
            return CREDIT_MIN_LTV
        return ltv

    def utilization(self) -> float:
        """Borrowed / (borrowed + available pool), in [0, 1]. O(1)."""
        borrowed = float(self.total_principal_dec)
        pool = borrowed + self.bank.cash + self._p2p_available
        if pool <= 0.0:
            return 0.0
        return borrowed / pool

    def _update_rate(self) -> None:
        """
        Rate = base + alpha * utilization (annual), refreshed daily.
        With a CentralBank attached (Part F), the Taylor policy rate --
        including its Gaussian surprise -- becomes the base, so monetary
        shocks propagate immediately into borrowing costs.
        """
        util_dec = Decimal(repr(round(self.utilization(), 9)))
        base_dec = (self.central_bank.policy_rate_dec
                    if self.central_bank is not None
                    else CREDIT_BASE_ANNUAL_RATE_DEC)
        self.annual_rate_dec = (base_dec
                                + CREDIT_UTILIZATION_ALPHA_DEC * util_dec)
        self.annual_rate = float(self.annual_rate_dec)
        self._daily_rate_dec = self.annual_rate_dec / _DAY_COUNT_DEC

    # -- Part G, WP7: green-weighted mandatory reserves ------------------------#
    def update_reserve_requirements(self) -> None:
        """
        Recomputes the bank's required reserves under the green
        supporting factor:

            RR = RESERVE_BASE_RATIO * [ sum_lines principal_i * omega_i
                                        + sum_bonds face_j * omega_bond ]

        with omega_i = max(OMEGA_MIN, 1 - discount * DISCLOSED score of
        the collateral asset) supplied by the ESGRegulation (single
        source of truth). Only bank-funded lines are bank exposures
        (P2P receivables sit on lender wallets, not the bank book).

        Deliberate model risk (WP7): omega uses the DISCLOSED score. On a
        scandal the asset's disclosed score snaps back to true (WP1.5),
        omega jumps on the next daily cycle, RR spikes, and `can_fund`
        may refuse new originations -- the systemic amplification is
        observable through `reserve_shortfall_events` and the exported
        reserve series. All arithmetic stays in the Decimal canon with
        float mirrors, consistent with the ledger style.
        """
        regulation = self.esg_regulation
        bank = self.bank
        if regulation is None:
            return
        asset = self.collateral_asset
        omega = regulation.risk_weight(
            asset.disclosed_green_score if asset is not None else 0.0)
        omega_dec = Decimal(repr(round(omega, 9)))

        exposure_dec = _ZERO
        for line in self.lines.values():
            if line.lender_id == BANK_ID:
                exposure_dec += line.principal_dec
        weighted_dec = exposure_dec * omega_dec

        bond_omega_dec = Decimal(repr(round(regulation.green_bond_omega, 9)))
        for bond in bank.bond_holdings:
            weighted_dec += bond.face_dec * bond_omega_dec

        rr_dec = (RESERVE_BASE_RATIO_DEC * weighted_dec).quantize(
            CREDIT_CENT_DEC, rounding=ROUND_HALF_EVEN)
        bank.required_reserves_dec = rr_dec
        bank.required_reserves = float(rr_dec)
        if rr_dec > bank.cash_dec:
            bank.reserve_shortfall_events += 1

    # -- exact transfer primitives ------------------------------------------- #
    def _route_to_lender(self, line: CreditLine, amount_dec: Decimal,
                         principal_part_dec: Decimal,
                         trader_map: dict) -> None:
        """
        Credits `amount_dec` to the line's lender: the bank ledger or a P2P
        lender's cash, shrinking the P2P receivable by the principal part.
        The float leg is identical on both sides of every transfer.
        """
        if line.lender_id == BANK_ID:
            self.bank.receive(amount_dec, principal_part_dec)
            return
        lender = trader_map.get(line.lender_id)
        if lender is None:            # Lender left the market: bank absorbs.
            self.bank.receive(amount_dec, _ZERO)
            return
        lender.cash += float(amount_dec)
        lender.cash_lent -= float(principal_part_dec)

    def _sync_borrower_debt(self, borrower: "Trader") -> None:
        """Refreshes the borrower's float debt mirror from their lines."""
        ids = self._lines_by_borrower.get(borrower.trader_id)
        if not ids:
            borrower.debt = 0.0
            return
        total = _ZERO
        lines = self.lines
        for line_id in ids:
            total += lines[line_id].debt_dec
        borrower.debt = float(total)

    # -- origination ----------------------------------------------------------#
    def request_loan(self, borrower: "Trader", price: float,
                     rel_volatility: float, current_day: int,
                     trader_map: dict) -> Optional[CreditLine]:
        """
        Evaluates and (if approved) originates one collateralized loan.

        Denial reasons, checked cheapest-first: open-line count,
        collateral floor, macroprudential leverage cap, then funding
        availability (largest P2P commitment first, bank as lender of
        last resort).
        """
        open_ids = self._lines_by_borrower.get(borrower.trader_id)
        if open_ids and len(open_ids) >= CREDIT_MAX_LINES_PER_BORROWER:
            return None

        collateral = int(borrower.shares * COLLATERAL_FRACTION)
        if collateral < MIN_COLLATERAL_SHARES:
            return None

        principal_dec = _dec_cents(collateral * price
                                   * self.max_ltv(rel_volatility))
        if principal_dec <= _ZERO:
            return None

        # Macroprudential leverage cap on post-loan debt-to-equity.
        equity = borrower.get_equity(price)
        if equity <= 0.0 or ((borrower.debt + float(principal_dec)) / equity
                             > MAX_DEBT_TO_EQUITY):
            self.denied_leverage_cap += 1
            return None

        lender_id = self._select_lender(principal_dec, trader_map)
        if lender_id is None:
            return None

        # Disburse: identical float leg on both sides (exact double entry).
        if lender_id == BANK_ID:
            leg = self.bank.pay_out(principal_dec)
        else:
            lender = trader_map[lender_id]
            leg = float(principal_dec)
            lender.cash -= leg
            lender.cash_lent += leg
            self._p2p_capacity[lender_id] -= leg
            self._p2p_available -= leg
        borrower.cash += leg

        # Lock the collateral out of the tradable share pool.
        borrower.pledge_collateral(collateral)

        self._line_id_counter += 1
        line = CreditLine(self._line_id_counter, borrower.trader_id,
                          lender_id, principal_dec, collateral, current_day)
        self.lines[line.line_id] = line
        self._lines_by_borrower.setdefault(
            borrower.trader_id, set()).add(line.line_id)
        self.total_principal_dec += principal_dec
        self.total_disbursed_dec += principal_dec
        borrower.debt += float(principal_dec)
        return line

    def _select_lender(self, principal_dec: Decimal,
                       trader_map: dict) -> Optional[str]:
        """Largest committed P2P vault first; bank as last resort."""
        need = float(principal_dec)
        best_id, best_cap = None, 0.0
        for lender_id, cap in self._p2p_capacity.items():
            if cap >= need and cap > best_cap and lender_id in trader_map:
                best_id, best_cap = lender_id, cap
        if best_id is not None:
            return best_id
        if self.bank.can_fund(principal_dec):
            return BANK_ID
        return None

    # -- daily servicing ------------------------------------------------------#
    def daily_cycle(self, current_day: int, closing_price: float,
                    rel_volatility: float, strategy_attractiveness: dict,
                    trader_map: dict, traders: list,
                    market_maker: "Trader") -> None:
        """The end-of-day credit hook (see class docstring for the order)."""
        self._update_rate()
        if self.lines:
            self._accrue_and_service(current_day, trader_map)
            self._enforce_margins(closing_price, trader_map, current_day)
        self._refresh_p2p_vault(traders, market_maker)
        # Part G, WP7: refresh the green-weighted reserve requirement
        # BEFORE originations so today's lending capacity is capital - RR.
        # No-op (and required reserves stay exactly 0) without regulation.
        if self.esg_regulation is not None:
            self.update_reserve_requirements()
        self._originate(current_day, closing_price, rel_volatility,
                        strategy_attractiveness, trader_map, traders)

    def _accrue_and_service(self, current_day: int, trader_map: dict) -> None:
        """
        Compounds one day of interest into every line (Decimal-exact,
        cent-quantized) and services it from the borrower's cash pool,
        transferring the identical float leg to the lender. Unpaid
        interest stays in the debt balance and compounds.
        """
        rate = self._daily_rate_dec
        for line in list(self.lines.values()):
            interest_dec = (line.debt_dec * rate).quantize(
                CREDIT_CENT_DEC, rounding=ROUND_HALF_EVEN)
            line.accrued_interest_dec += interest_dec

            borrower = trader_map.get(line.borrower_id)
            if borrower is None:
                line.sync_mirrors()
                continue

            due_dec = line.accrued_interest_dec
            if due_dec > _ZERO and borrower.cash > 0.0:
                pay_dec = min(due_dec, _dec_cents(borrower.cash))
                if pay_dec > _ZERO:
                    borrower.cash -= float(pay_dec)
                    line.accrued_interest_dec -= pay_dec
                    self._route_to_lender(line, pay_dec, _ZERO, trader_map)
                    self.total_interest_collected_dec += pay_dec
            line.sync_mirrors()
            self._sync_borrower_debt(borrower)

    # -- margin calls and forced liquidation ----------------------------------#
    def _enforce_margins(self, price: float, trader_map: dict,
                         current_day: int) -> None:
        """
        Endogenous margin sweep: liquidates every line whose debt exceeds
        MAINTENANCE_MARGIN_RATIO of the mark-to-market collateral value.
        Liquidations move the mark, so the sweep cascades (bounded passes)
        until the ledger is clean -- the fire-sale dynamic is endogenous.
        """
        if price <= 0.0:
            return
        for _ in range(self.MAX_CASCADE_PASSES):
            threshold = MAINTENANCE_MARGIN_RATIO * price
            breached = [line for line in self.lines.values()
                        if line.debt > threshold * line.collateral_shares]
            if not breached:
                return
            for line in breached:
                self._liquidate(line, trader_map, current_day)
            if self._mark_price > 0.0:   # Fire sales moved the mark.
                price = self._mark_price

    def _liquidate(self, line: CreditLine, trader_map: dict,
                   current_day: int) -> None:
        """
        Forced liquidation state:
          1. cancel the borrower's resting orders,
          2. dump the collateral into the active bids at market,
          3. sweep the proceeds (plus freed escrow) into the liability --
             interest first, then principal -- and leave any remainder
             with the trader. Unrecoverable residue is written off
             against the lender (default).
        """
        self.liquidation_count += 1
        borrower = trader_map.get(line.borrower_id)
        if borrower is None:
            self._write_off(line, line.debt_dec, trader_map)
            self._close_line(line)
            return

        # Release the pledge into the sellable pool, then dump it.
        qty = line.collateral_shares
        borrower.release_collateral(qty)
        line.collateral_shares = 0
        self.order_book.force_liquidation(line.borrower_id, qty,
                                          trader_map, current_day)

        # Hard-route available cash into the liability.
        debt_dec = line.debt_dec
        pay_dec = min(debt_dec, _dec_cents(borrower.cash)) \
            if borrower.cash > 0.0 else _ZERO
        if pay_dec > _ZERO:
            interest_part = min(pay_dec, line.accrued_interest_dec)
            principal_part = pay_dec - interest_part
            borrower.cash -= float(pay_dec)
            line.accrued_interest_dec -= interest_part
            line.principal_dec -= principal_part
            self.total_principal_dec -= principal_part
            self._route_to_lender(line, pay_dec, principal_part, trader_map)
            self.total_repaid_dec += principal_part
            self.total_interest_collected_dec += interest_part

        # Whatever the sweep could not recover is a default write-off.
        residue = line.debt_dec
        if residue > _ZERO:
            self._write_off(line, residue, trader_map)
        self._close_line(line)
        self._sync_borrower_debt(borrower)

    def _write_off(self, line: CreditLine, amount_dec: Decimal,
                   trader_map: dict) -> None:
        """Destroys an unrecoverable receivable (no cash moves)."""
        principal_loss = min(amount_dec, line.principal_dec)
        if line.lender_id == BANK_ID:
            self.bank.write_off(principal_loss, amount_dec)
        else:
            lender = trader_map.get(line.lender_id)
            if lender is not None:    # Receivable mirror absorbs the loss.
                lender.cash_lent -= float(principal_loss)
        line.principal_dec -= principal_loss
        line.accrued_interest_dec = _ZERO
        self.total_principal_dec -= principal_loss
        self.total_writeoffs_dec += amount_dec

    def _close_line(self, line: CreditLine) -> None:
        line.active = False
        line.sync_mirrors()
        self.lines.pop(line.line_id, None)
        ids = self._lines_by_borrower.get(line.borrower_id)
        if ids is not None:
            ids.discard(line.line_id)
            if not ids:
                del self._lines_by_borrower[line.borrower_id]

    # -- population events ----------------------------------------------------#
    def on_trader_removed(self, trader: "Trader", trader_map: dict) -> None:
        """
        Bankruptcy hook: closes every line touching the removed trader.
        As borrower: residual debt defaults (write-off). As lender: the
        receivable dies with them (recorded in the write-off counter).
        """
        tid = trader.trader_id
        doomed = [line for line in self.lines.values()
                  if line.borrower_id == tid or line.lender_id == tid]
        for line in doomed:
            if line.collateral_shares > 0 and line.borrower_id == tid:
                trader.release_collateral(line.collateral_shares)
                line.collateral_shares = 0
            self._write_off(line, line.debt_dec, trader_map)
            self._close_line(line)
        self._p2p_capacity.pop(tid, None)

    # -- P2P vault and origination sweep --------------------------------------#
    def _refresh_p2p_vault(self, traders: list,
                           market_maker: "Trader") -> None:
        """
        Recomputes surplus agents' lending commitments: the MarketMaker
        and wealthy fundamentalists pledge P2P_VAULT_FRACTION of idle
        cash above the liquidity threshold. Deterministic, O(N) daily.
        """
        capacity: dict[str, float] = {}
        total = 0.0
        idle = market_maker.cash - P2P_LENDER_MIN_CASH
        if idle > 0.0:
            cap = P2P_VAULT_FRACTION * idle
            capacity[market_maker.trader_id] = cap
            total += cap
        for trader in traders:
            if trader.type != 'fundamentalist':
                continue
            idle = trader.cash - P2P_LENDER_MIN_CASH
            if idle > 0.0:
                cap = P2P_VAULT_FRACTION * idle
                capacity[trader.trader_id] = cap
                total += cap
        self._p2p_capacity = capacity
        self._p2p_available = total

    def _originate(self, current_day: int, price: float,
                   rel_volatility: float, strategy_attractiveness: dict,
                   trader_map: dict, traders: list) -> None:
        """
        Deterministic borrowing sweep: cash-constrained chartist/noise
        agents whose strategy attractiveness clears the floor request a
        margin loan against their free shares.
        """
        cash_floor = BORROWER_CASH_MULTIPLE * price
        for trader in traders:
            t_type = trader.type
            if t_type not in ('chartist', 'noise'):
                continue
            if strategy_attractiveness.get(t_type, 0.0) \
                    <= CREDIT_ATTRACTIVENESS_FLOOR:
                continue
            if trader.cash >= cash_floor:
                continue
            self.request_loan(trader, price, rel_volatility, current_day,
                              trader_map)

    # -- reporting -------------------------------------------------------------#
    def outstanding_debt(self) -> float:
        """Float mirror of total outstanding principal (O(1))."""
        return float(self.total_principal_dec)

    def bank_exposure(self) -> float:
        """Bank-funded principal only (P2P receivables excluded) -- the
        exposure base of the WP7 reserve requirement. O(lines)."""
        total = _ZERO
        for line in self.lines.values():
            if line.lender_id == BANK_ID:
                total += line.principal_dec
        return float(total)
