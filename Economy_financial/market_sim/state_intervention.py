"""
State / government climate intervention layer (Part F + Part G WP6).

The `State` is a programmatic fiscal entity -- it never places retail
limit orders. It wields four instruments:

  Subsidies              -- every EVOLUTION_EPOCH_DAYS, an epoch budget is
                            split across listed companies proportionally
                            to their DISCLOSED green scores (Part G WP1.2
                            re-pointing: the regulator can only allocate
                            on what firms report -- this is harvesting
                            channel (b) of the greenwasher) and injected
                            straight into the corporate balance sheets.
                            Cent-quantized Decimal, exact ledger.
  Sovereign green fund   -- a daily investment budget crosses the spread
                            with automated MarketOrder BUYs, exclusively
                            on assets whose DISCLOSED green_score clears
                            the regulatory threshold (WP3 institutional
                            reliance; harvesting channel (c) when the
                            true score is below it).
  Penalties              -- receives final sanctions from the applicable
                            legal track: corporate balance -> treasury.
                            The legacy WP1 path may still run its old proxy
                            experiment, while the opt-in supervisor never
                            treats the CSDDD 3% ceiling as a generic fine.
  Green bonds (WP6)      -- issues `GreenBond` instruments at par to the
                            CommercialBank and cash-rich traders when the
                            treasury runs low; the coupon is the policy
                            rate MINUS a greenium. Proceeds land in an
                            earmarked `green_proceeds_dec` sub-ledger
                            that can ONLY fund subsidies and sovereign-
                            fund purchases (use-of-proceeds constraint,
                            asserted). STYLIZATION: this stylizes the EU
                            green-bond framework (Regulation (EU)
                            2023/2631), which the Omnibus directive
                            leaves in force; the
                            `ESGRegulation.green_bonds_allowed` flag is
                            the experiment lever, not a directive fact.

Double-entry discipline: the treasury has a Decimal canon and a float
mirror (the ledger Trader's wallet). Subsidies move treasury -> corporate
balance (a tracked drain on the participants' cash universe, symmetric to
how dividends are a tracked injection); penalties are the exact reverse;
bond sales move buyer wallet -> treasury INSIDE the universe; coupons and
redemptions move treasury -> holder inside the universe (bank coupons
leave the universe into the bank ledger, tracked). Market purchases
settle through a normal per-venue `AssetPosition` view.

WP6 conservation identity (asserted in the Simulation debug audit):

    bonds_issued_dec  ==  green_proceeds_dec + green_proceeds_spent_dec
    (every earmarked euro is either still in the sub-ledger or was spent
     on subsidies / fund purchases -- never on generic treasury outflow)

Sovereign default is out of scope BY DESIGN: if the unearmarked treasury
cannot service a coupon or redemption, a sovereign-stress event is logged
and the bond is rolled for another full term at the same coupon
(`rolled` counter on the bond). This is a documented simplification --
modeling sovereign default cascades is beyond Part G's research object.

Circular-dependency note: imports `constants` and `models` at runtime;
`Trader` only under TYPE_CHECKING. Venues, banks and the regulation
object are duck-typed.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING, Optional

from market_sim.constants import (
    CREDIT_CENT_DEC,
    GREEN_BOND_COUPON_PERIOD_DAYS,
    GREEN_BOND_FACE_DEC,
    GREEN_BOND_GREENIUM,
    GREEN_BOND_ISSUE_THRESHOLD_DEC,
    GREEN_BOND_MATURITY_DAYS,
    GREEN_BOND_MAX_OUTSTANDING,
    P2P_LENDER_MIN_CASH,
    STATE_DAILY_INVESTMENT_DEC,
    STATE_GREEN_THRESHOLD,
    STATE_SUBSIDY_EPOCH_BUDGET_DEC,
    STATE_TREASURY_DEC,
)
from market_sim.models import GreenBond, MarketOrder

if TYPE_CHECKING:
    from market_sim.traders import Trader

_ZERO = Decimal("0")

STATE_ID = "T_STATE"


class State:
    """Sovereign climate-policy agent (fiscal + green-fund + green-bond
    instruments)."""

    __slots__ = ("ledger", "treasury_dec", "total_subsidies_dec",
                 "total_invested_dec", "subsidy_events", "buy_events",
                 # Part G, WP1.5: penalty inflow (exact mirror of subsidies).
                 "penalty_inflow_dec",
                 # Part G, WP6: green-bond program state.
                 "bonds", "next_bond_id", "green_proceeds_dec",
                 "green_proceeds_spent_dec", "bonds_issued_dec",
                 "bonds_redeemed_dec", "coupons_paid_dec",
                 "sovereign_stress_events",
                 # Part H: policy-experiment operating costs (hub /
                 # connector). Generic outflows -- never earmarked money.
                 "policy_cost_dec", "policy_cost_shortfalls")

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
        self.penalty_inflow_dec = _ZERO
        self.bonds: list[GreenBond] = []
        self.next_bond_id = 0
        self.green_proceeds_dec = _ZERO         # Earmarked sub-ledger (WP6)
        self.green_proceeds_spent_dec = _ZERO   # Audit: earmarked euros used
        self.bonds_issued_dec = _ZERO
        self.bonds_redeemed_dec = _ZERO
        self.coupons_paid_dec = _ZERO
        self.sovereign_stress_events = 0
        self.policy_cost_dec = _ZERO
        self.policy_cost_shortfalls = 0

    # -- WP6 earmarking primitives ------------------------------------------- #
    def _drain_earmarked(self, amount_dec: Decimal) -> None:
        """
        Books `amount_dec` of GREEN spending (subsidies / fund buys)
        against the earmarked sub-ledger first. Only the overflow beyond
        the earmarked pool touches unearmarked treasury money.
        """
        from_green = min(self.green_proceeds_dec, amount_dec)
        if from_green > _ZERO:
            self.green_proceeds_dec -= from_green
            self.green_proceeds_spent_dec += from_green

    def _unearmarked_dec(self) -> Decimal:
        """Treasury money that may fund generic (non-green) outflows."""
        return self.treasury_dec - self.green_proceeds_dec

    # -- instrument 1: green-scaled corporate subsidies ---------------------- #
    def pay_subsidies(self, venues: list, current_day: int,
                      regulation=None,
                      use_supported_information: bool = False,
                      raw_disclosure_counterfactual: bool = False) -> float:
        """
        Splits the epoch budget across companies proportionally to their
        DISCLOSED green scores and injects it into the corporate balance
        sheets. Returns the exact float total drained from the treasury.

        Part G: subsidy euros count as GREEN spending and drain the
        earmarked bond-proceeds sub-ledger first (WP6). When the
        regulation layer is active, the wedge-attributable slice of each
        firm's subsidy (actual disclosed-keyed payment minus the
        counterfactual true-score payment) is booked into the firm's
        harvesting channels: channel (b), with the bond-funded fraction
        reclassified as channel (e) spillover.
        """
        def policy_score(venue):
            if use_supported_information \
                    and not raw_disclosure_counterfactual:
                return venue.asset.regulatory_eligibility_score
            return venue.asset.disclosed_green_score

        allocation_scores = {v.asset.symbol: policy_score(v) for v in venues}
        total_disclosed = sum(allocation_scores.values())
        if total_disclosed <= 0.0:
            return 0.0
        budget = min(STATE_SUBSIDY_EPOCH_BUDGET_DEC, self.treasury_dec)
        if budget <= _ZERO:
            return 0.0

        # Counterfactual true-score allocation (wedge accounting, WP2.b).
        total_true = sum(v.asset.true_green_score for v in venues) \
            if regulation is not None and not use_supported_information \
            else 0.0

        # Bond-funded fraction of THIS epoch's green spending (WP2.e).
        green_frac = 0.0
        if self.green_proceeds_dec > _ZERO and budget > _ZERO:
            green_frac = float(min(self.green_proceeds_dec, budget) / budget)

        paid = _ZERO
        for venue in venues:
            asset = venue.asset
            share = allocation_scores[asset.symbol] / total_disclosed
            subsidy_dec = (budget * Decimal(repr(round(share, 9)))).quantize(
                CREDIT_CENT_DEC, rounding=ROUND_DOWN)
            if subsidy_dec <= _ZERO:
                continue
            asset.balance += float(subsidy_dec)
            asset.last_subsidy_day = current_day
            paid += subsidy_dec

            if regulation is not None and total_true > 0.0:
                true_share = asset.true_green_score / total_true
                counterfactual = float(budget) * true_share
                wedge_gain = float(subsidy_dec) - counterfactual
                policy = getattr(venue, "policy", None)
                if policy is not None and wedge_gain > 0.0:
                    policy.harvest['subsidies'] += wedge_gain \
                        * (1.0 - green_frac)
                    policy.harvest['bonds'] += wedge_gain * green_frac

        self.treasury_dec -= paid
        self._drain_earmarked(paid)          # WP6: green use of proceeds.
        self.total_subsidies_dec += paid
        self.ledger.cash -= float(paid)      # Float mirror stays in step.
        self.subsidy_events += 1
        return float(paid)

    # -- instrument 2: sovereign green fund (direct market investment) ------- #
    def invest_green(self, venues: list, current_day: int,
                     regulation=None,
                     credibility_index: Optional[dict] = None,
                     use_supported_information: bool = False,
                     raw_disclosure_counterfactual: bool = False) -> None:
        """
        Crosses the spread with automated market BUYs on every asset whose
        DISCLOSED green score clears the regulatory sustainability
        threshold (WP3: institutional reliance on the raw disclosure --
        unless the `institutions_use_credibility` counterfactual toggle
        discounts it by the market's average kappa). The daily budget is
        split evenly across eligible assets; quantities are sized against
        the current best ask plus taker commission.

        Part G channel (c): purchases on assets that are eligible ONLY
        because of the disclosure wedge (true score below the threshold)
        are booked as sovereign-flow harvesting.
        """
        use_kappa = (regulation is not None
                     and regulation.institutions_use_credibility
                     and credibility_index is not None)
        eligible = []
        for v in venues:
            score = v.asset.regulatory_eligibility_score \
                if (use_supported_information
                    and not raw_disclosure_counterfactual) \
                else v.asset.disclosed_green_score
            if use_kappa:
                score *= credibility_index.get(v.symbol, 1.0)
            if score >= STATE_GREEN_THRESHOLD:
                eligible.append(v)
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
                spent_dec = Decimal(repr(round(spent, 9)))
                self.treasury_dec -= spent_dec
                self._drain_earmarked(          # WP6: green use of proceeds.
                    spent_dec.quantize(CREDIT_CENT_DEC,
                                       rounding=ROUND_HALF_EVEN))
                self.total_invested_dec += spent_dec
                self.buy_events += 1
                # Channel (c): flow earned purely by the wedge.
                if regulation is not None and not use_supported_information \
                        and venue.asset.true_green_score \
                        < STATE_GREEN_THRESHOLD:
                    policy = getattr(venue, "policy", None)
                    if policy is not None:
                        policy.harvest['sovereign'] += spent

    # -- instrument 3 (Part G, WP1.5): penalty inflow ------------------------- #
    def receive_penalty(self, penalty_dec: Decimal) -> None:
        """
        Books a detected-scandal sanction: the caller has already deducted
        the exact amount from the corporate balance; here it enters the
        treasury (Decimal canon + float mirror). Penalties are NOT
        earmarked -- they are generic fiscal revenue.
        """
        self.treasury_dec += penalty_dec
        self.penalty_inflow_dec += penalty_dec
        self.ledger.cash += float(penalty_dec)

    # -- Part H: policy-experiment operating costs ----------------------------- #
    def pay_policy_cost(self, amount_dec: Decimal) -> Decimal:
        """
        Pays hub / connector implementation and operating costs to
        external providers. GENERIC treasury spending: it must never
        touch the earmarked green-bond sub-ledger (WP6 use-of-proceeds
        constraint), so it is funded exclusively from
        ``_unearmarked_dec()``. Underfunded amounts are skipped and
        counted, never borrowed from earmarked money. Returns the amount
        actually paid.
        """
        if amount_dec <= _ZERO:
            return _ZERO
        payable = min(amount_dec, max(_ZERO, self._unearmarked_dec()))
        if payable < amount_dec:
            self.policy_cost_shortfalls += 1
        if payable > _ZERO:
            self.treasury_dec -= payable
            self.ledger.cash -= float(payable)
            self.policy_cost_dec += payable
        return payable

    # -- instrument 4 (Part G, WP6): sovereign green bonds --------------------- #
    def issue_green_bonds(self, current_day: int, policy_rate: float,
                          bank, trader_map: dict, regulation) -> int:
        """
        Primary-market issuance sweep. Fires only while the regulation
        gate `green_bonds_permitted` is open AND the treasury float
        mirror sits below the funding threshold. Bonds are sold at par,
        one face-value unit per buyer pass: the CommercialBank first
        (its demand is endogenous -- WP7 gives green bonds a reduced
        reserve weight, so buying them costs little lending capacity),
        then cash-rich traders (reusing the P2P-vault eligibility
        heuristic: free cash above P2P_LENDER_MIN_CASH). Settlement is
        exact-ledger: the Decimal face moves symmetrically, buyer wallet
        -> treasury, and the proceeds are earmarked. Returns the number
        of bonds issued.
        """
        if regulation is None or not regulation.green_bonds_allowed:
            return 0
        if self.treasury_dec >= GREEN_BOND_ISSUE_THRESHOLD_DEC:
            return 0
        outstanding = sum(1 for b in self.bonds if b.active)
        if outstanding >= GREEN_BOND_MAX_OUTSTANDING:
            return 0

        coupon = max(policy_rate - GREEN_BOND_GREENIUM, 0.0)
        face_dec = GREEN_BOND_FACE_DEC
        issued = 0

        # Endogenous bank demand first (reduced reserve weight, WP7).
        if bank is not None and bank.can_fund(face_dec):
            self._settle_issue(bank, None, face_dec, coupon, current_day)
            issued += 1
            outstanding += 1

        # Cash-rich traders (P2P-vault eligibility logic reused).
        if outstanding < GREEN_BOND_MAX_OUTSTANDING \
                and self.treasury_dec < GREEN_BOND_ISSUE_THRESHOLD_DEC:
            for trader in trader_map.values():
                if outstanding >= GREEN_BOND_MAX_OUTSTANDING:
                    break
                buyer = getattr(trader, "owner", trader)  # Position views
                if buyer.trader_id == STATE_ID:
                    continue
                if buyer.cash <= P2P_LENDER_MIN_CASH + float(face_dec):
                    continue
                self._settle_issue(None, buyer, face_dec, coupon,
                                   current_day)
                issued += 1
                outstanding += 1
        return issued

    def _settle_issue(self, bank, buyer, face_dec: Decimal, coupon: float,
                      current_day: int) -> None:
        """Par settlement of one bond: symmetric Decimal-quantized legs."""
        self.next_bond_id += 1
        leg = float(face_dec)
        if bank is not None:
            holder_id = bank.bank_id
            bank.cash_dec -= face_dec
            bank.cash -= leg
        else:
            holder_id = buyer.trader_id
            buyer.cash -= leg
        bond = GreenBond(self.next_bond_id, holder_id, face_dec, coupon,
                         current_day,
                         current_day + GREEN_BOND_MATURITY_DAYS)
        self.bonds.append(bond)
        if bank is not None:
            bank.bond_holdings.append(bond)
        self.treasury_dec += face_dec
        self.ledger.cash += leg
        self.green_proceeds_dec += face_dec      # Use-of-proceeds earmark.
        self.bonds_issued_dec += face_dec

    def service_bonds(self, current_day: int, bank,
                      trader_map: dict) -> None:
        """
        Daily end-of-day hook (runs next to `accrue_interest`): pays
        periodic coupons and redeems matured bonds. Coupons and
        redemptions are GENERIC treasury outflows -- they must never
        touch the earmarked sub-ledger, so they are funded exclusively
        from `_unearmarked_dec()`. If that pool cannot pay, a
        sovereign-stress event is logged and the bond is rolled for a
        full term (default out of scope; documented simplification).
        """
        for bond in self.bonds:
            if not bond.active:
                continue
            # Periodic coupon.
            age = current_day - bond.issue_day
            if age > 0 and age % GREEN_BOND_COUPON_PERIOD_DAYS == 0 \
                    and bond.coupon_rate > 0.0:
                coupon_dec = (bond.face_dec
                              * Decimal(repr(round(bond.coupon_rate, 9)))
                              * Decimal(GREEN_BOND_COUPON_PERIOD_DAYS)
                              / Decimal(365)).quantize(
                    CREDIT_CENT_DEC, rounding=ROUND_HALF_EVEN)
                if coupon_dec > _ZERO:
                    if self._unearmarked_dec() >= coupon_dec:
                        self._pay_holder(bond, coupon_dec, bank, trader_map)
                        bond.coupons_paid_dec += coupon_dec
                        self.coupons_paid_dec += coupon_dec
                    else:
                        self.sovereign_stress_events += 1
            # Redemption at maturity (or roll under stress).
            if current_day >= bond.maturity_day:
                if self._unearmarked_dec() >= bond.face_dec:
                    self._pay_holder(bond, bond.face_dec, bank, trader_map)
                    self.bonds_redeemed_dec += bond.face_dec
                    bond.active = False
                    if bank is not None and bond.holder_id == bank.bank_id:
                        bank.bond_holdings.remove(bond)
                else:
                    self.sovereign_stress_events += 1
                    bond.maturity_day = current_day \
                        + GREEN_BOND_MATURITY_DAYS
                    bond.rolled += 1

    def _pay_holder(self, bond: GreenBond, amount_dec: Decimal, bank,
                    trader_map: dict) -> None:
        """Treasury -> holder transfer with identical float legs."""
        leg = float(amount_dec)
        self.treasury_dec -= amount_dec
        self.ledger.cash -= leg
        if bank is not None and bond.holder_id == bank.bank_id:
            bank.cash_dec += amount_dec
            bank.cash += leg
            return
        holder = trader_map.get(bond.holder_id)
        if holder is not None:
            owner = getattr(holder, "owner", holder)
            owner.cash += leg
        # Holder left the market: the payment stays with the treasury's
        # float mirror consistency (leg already deducted) -- re-credit.
        else:
            self.treasury_dec += amount_dec
            self.ledger.cash += leg

    # -- reporting ------------------------------------------------------------#
    def treasury(self) -> float:
        """Float mirror of the remaining treasury (O(1))."""
        return float(self.treasury_dec)

    def bond_stock(self) -> float:
        """Face value of all active bonds (float, for logging)."""
        return float(sum(b.face_dec for b in self.bonds if b.active))
