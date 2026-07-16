"""
Corporate policy layer (Part G, WP2 + WP5): the greenwashing agent and
the NPV-driven continuous, reversible green transition.

Compatibility note: the 3%-proxy/audit optimization documented below is
the retained legacy Part-G experiment. With
``enable_greenwashing_supervision`` active, disclosure is delegated to
``corporate_communications.py`` and enforcement to
``greenwashing_supervision.py``; the legacy audit and generic 3% penalty are
bypassed. The real-transition machinery in this module remains active.

`CorporatePolicy` replaces the passive corporate side (the old stepped
heuristic in `Simulation._corporate_transitions` is DELETED) with one
explicit agent per listing, strategy-typed in {honest, greenwasher,
adaptive} via `asset_profiles`.

WP5 -- NPV of a marginal unit of TRUE greenness (module contract)
------------------------------------------------------------------
Daily discounting uses the live CentralBank policy rate r:

    delta = 1 / (1 + r/365),      A(H) = sum_{t=1..H} delta^t
                                       = delta * (1 - delta^H) / (1 - delta)

Each benefit sensitivity is estimated from CURRENT simulation state (no
oracle constants):

  Subsidy      S_i = B * d_i / sum_j d_j  per reporting period, so
               dS_i/dd_i = B * (sum_d - d_i) / (sum_d)^2 / T_rep  per day,
               with B = live epoch budget (capped by the treasury) and
               d = disclosed scores. A real transition moves d one-for-one
               (dd/dg = 1) because true improvements are always disclosed.
  Greenium     Fundamentalist fair value V_fair = V_fund * (1 + gamma*d)
               => dP/dd ~= gamma * V_fund. Monetized through treasury
               sales at clip q_bar = TREASURY_SELL_CLIP / T_rep shares
               per day => sensitivity q_bar * gamma * V_fund per day.
  FundingCost  (WP7) dRR/dd = -rho * phi * E  (rho = reserve base ratio,
               phi = green risk-weight discount, E = live credit exposure
               backed by this asset); freed reserves re-lend at the live
               credit rate r_L => rho * phi * E * r_L / 365 per day.
               Precomputed by the Simulation (which owns the CreditMarket)
               and injected -- zero when no exposure is backed by the
               asset (in this build only the primary listing backs
               collateral; documented partial-equilibrium limitation).
  GreenBond    (WP6) sovereign green proceeds are earmarked for subsidies
               and fund purchases, so an active bond program scales the
               expected subsidy capacity: the subsidy term is multiplied
               by (1 + green_proceeds / treasury). MODELING CHOICE with
               no directive basis -- a reduced-form spillover, not a
               corporate financing channel.
  Maintenance  Certification upkeep costs m = GREEN_MAINTENANCE_RATE per
               unit of true score per day; owning one more unit costs m
               forever, so it enters the NPV with a minus sign and is the
               ONLY thing recovered by backsliding (sunk CAPEX is sunk).

    NPV_per_unit = A(H) * [ s_subsidy * bond_mult + s_greenium
                            + s_funding - m ]  -  P_green(t) * C'(g)

with the convex marginal-cost curve

    C'(g) = GREEN_MC_BASE * (1 + GREEN_MC_CONVEXITY * g
                                 / (GREEN_MC_POLE - g)),

whose pole just above g = 1 makes the last 10% disproportionately
expensive.

Discretization (continuous control law, WP5):

    dg_t  = clamp(TRANSITION_RESPONSIVENESS * NPV_per_unit,
                  -G_DECAY_MAX, +G_STEP_MAX)
    g_t+1 = clamp(g_t + dg_t, 0, 1)

When `P_green` is high enough that NPV < 0, dg goes negative: the firm
lets certifications lapse and `true_green_score` decays. Backsliding
refunds nothing; only the maintenance saving m * |dg| is recovered
(it simply stops being paid). Real transition spend P_green * C'(g) * dg
is cent-quantized Decimal, paid through the `balance` property setter,
and always respects CORPORATE_BALANCE_FLOOR * GREEN_TRANSITION_SAFETY.

Known limitations (stated, not hidden): the horizon H is myopic and the
sensitivities are partial-equilibrium snapshots (they ignore the reaction
of other firms' scores, of the credibility beliefs kappa, and of the
subsidy budget to this firm's own move); the greenium monetization is
linearized around the current fundamental; the funding channel only binds
for the collateral-backing listing.

WP2 -- the greenwasher's one-period inflation argmax
----------------------------------------------------
Each reporting period the greenwasher picks the disclosure inflation
increment Dd from GREENWASH_CHOICE_GRID maximizing

    E[Dprofit](Dd) = dBenefit/dd * T_rep * Dd  +  FundBonus(Dd)
                     - p_audit * [p_det(w + Dd) - p_det(w)] * Penalty * a
                     - ReportCost * 1{Dd > 0}

where dBenefit/dd reuses the WP5 sensitivities (subsidy + greenium +
funding, all live-state), FundBonus prices the crossing of
STATE_GREEN_THRESHOLD (captured share of the incremental sovereign-fund
flow, read from live State budgets), w is the current UNLAWFUL wedge,
p_det the regulation's logistic detection curve, Penalty the live 3%-of-
turnover sanction, and `a` a risk-aversion multiplier (1 for pure
greenwashers; grows with own scandal count for adaptive firms).
Regulatory arbitrage: below the mandatory-size threshold the audit terms
are zero (voluntary regime), so the small firm inflates freely up to the
plausibility cap GREENWASH_MAX_WEDGE_STEP.

Conservation identities (asserted in the Simulation debug audit):
  - real CAPEX + report costs + maintenance leave the corporate balance
    and vanish from no ledger (they are corporate expenses, symmetric to
    the pre-existing GREEN_TRANSITION_COST sink);
  - treasury-sale proceeds move buyer cash -> corporate wallet -> balance
    (tracked in `total_treasury_swept`);
  - penalties move corporate balance -> State treasury (tracked in
    ESGRegulation.total_penalties_dec == State.penalty_inflow_dec).

Dependency position: imports `constants`, `models` and the stdlib;
consulted regulation state arrives as an injected `ESGRegulation`. Sits
between `models` and `simulation` in the package graph.
"""

from __future__ import annotations

import math
import random
from decimal import ROUND_DOWN, Decimal
from typing import TYPE_CHECKING, Optional

from market_sim.constants import (
    ADAPTIVE_RISK_AVERSION_STEP,
    ADAPTIVE_SCANDAL_MEMORY_DAYS,
    CORPORATE_BALANCE_FLOOR,
    CREDIT_CENT_DEC,
    G_DECAY_MAX,
    G_STEP_MAX,
    GREEN_MAINTENANCE_RATE,
    GREEN_MC_BASE,
    GREEN_MC_CONVEXITY,
    GREEN_MC_POLE,
    GREEN_TRANSITION_SAFETY,
    GREENIUM_GAMMA,
    GREENWASH_CHOICE_GRID,
    GREENWASH_MAX_WEDGE_STEP,
    GREENWASH_REPORT_COST,
    GREENWASH_REPORT_COST_DEC,
    NPV_HORIZON_DAYS,
    PGREEN_INITIAL,
    PGREEN_LOG_REVERSION,
    PGREEN_LOG_VOL,
    REG_MANDATED_MIN_STEP,
    REG_OMISSION_BUFFER_CAP,
    SOVEREIGN_FLOW_CAPTURE,
    STATE_GREEN_THRESHOLD,
    TRANSITION_RESPONSIVENESS,
    TREASURY_MIN_PREMIUM,
    TREASURY_SELL_CLIP,
)
from market_sim.models import MarketOrder

if TYPE_CHECKING:
    from market_sim.models import Asset
    from market_sim.regulation import ESGRegulation
    from market_sim.traders import Trader

CORPORATE_STRATEGIES = ('honest', 'greenwasher', 'adaptive')

_ZERO = Decimal("0")


class GreenCapitalPrice:
    """
    Exogenous stochastic price of green capital P_green(t) (WP5):
    log-space Ornstein-Uhlenbeck around a flat anchor, reusing the Asset
    OU pattern (one gauss draw per trading day, gated to ESG mode):

        log P_t = log P_{t-1} + theta * (log P_anchor - log P_{t-1})
                              + sigma * N(0, 1)
    """

    __slots__ = ("_log_price", "_log_anchor", "value", "history")

    def __init__(self, initial: float = PGREEN_INITIAL):
        self._log_price = math.log(initial)
        self._log_anchor = self._log_price
        self.value = initial
        self.history: list[float] = [initial]

    def update_daily(self) -> float:
        """One OU step; returns the new price level."""
        log_p = self._log_price
        log_p += PGREEN_LOG_REVERSION * (self._log_anchor - log_p)
        log_p += random.gauss(0.0, PGREEN_LOG_VOL)
        self._log_price = log_p
        self.value = math.exp(log_p)
        self.history.append(self.value)
        return self.value


def marginal_cost_curve(g: float) -> float:
    """Convex marginal cost C'(g) of one unit of true greenness (WP5)."""
    return GREEN_MC_BASE * (1.0 + GREEN_MC_CONVEXITY
                            * g / (GREEN_MC_POLE - g))


class CorporatePolicy:
    """
    One listed firm's disclosure + transition policy (WP2 + WP5).

    strategy:
      honest       discloses the true score every reporting period (bad
                   news damped only by the lawful omission exemption).
      greenwasher  runs the one-period expected-profit argmax over
                   disclosure inflation; substitutes cheap talk for real
                   CAPEX whenever the argmax favors it.
      adaptive     greenwasher that reports honestly for
                   ADAPTIVE_SCANDAL_MEMORY_DAYS after its own scandal and
                   thereafter re-enters the argmax with penalty aversion
                   1 + ADAPTIVE_RISK_AVERSION_STEP * own_scandal_count.
    """

    __slots__ = ("asset", "strategy", "ledger", "regulation",
                 "scandal_count", "harvest",
                 "total_transition_spend_dec", "total_report_cost_dec",
                 "total_maintenance_dec", "total_treasury_swept",
                 "last_dg", "last_npv_per_unit")

    def __init__(self, asset: "Asset", strategy: str,
                 ledger: Optional["Trader"],
                 regulation: Optional["ESGRegulation"]):
        if strategy not in CORPORATE_STRATEGIES:
            raise ValueError(f"unknown corporate strategy: {strategy!r}")
        self.asset = asset
        self.strategy = strategy
        self.ledger = ledger              # Treasury Trader shell (or None)
        self.regulation = regulation      # None => regulation layer off
        self.scandal_count = 0
        # WP2 harvesting channels, all measured where the euros actually
        # flow (a: treasury sales; b: subsidy wedge gain; c: sovereign buy
        # pressure on wedge-eligible listings; d: funding advantage from
        # reserve relief on the wedge; e: bond-funded share of b).
        self.harvest = {'greenium': 0.0, 'subsidies': 0.0,
                        'sovereign': 0.0, 'funding': 0.0, 'bonds': 0.0}
        self.total_transition_spend_dec = _ZERO
        self.total_report_cost_dec = _ZERO
        self.total_maintenance_dec = _ZERO
        self.total_treasury_swept = 0.0
        self.last_dg = 0.0
        self.last_npv_per_unit = 0.0

    # -- WP5: benefit sensitivities (all from live state) -------------------- #
    @staticmethod
    def _annuity(policy_rate: float) -> float:
        """A(H) = sum_{t=1..H} delta^t with delta = 1/(1 + r/365)."""
        delta = 1.0 / (1.0 + max(policy_rate, 0.0) / 365.0)
        if delta >= 1.0:                      # r == 0: undiscounted sum.
            return float(NPV_HORIZON_DAYS)
        return delta * (1.0 - delta ** NPV_HORIZON_DAYS) / (1.0 - delta)

    @staticmethod
    def _subsidy_sensitivity(epoch_budget: float, total_disclosed: float,
                             own_disclosed: float,
                             period_days: int) -> float:
        """dS_i/dd_i per day: B * (sum_d - d_i) / (sum_d)^2 / T_rep."""
        if epoch_budget <= 0.0 or total_disclosed <= 0.0:
            return 0.0
        return (epoch_budget * (total_disclosed - own_disclosed)
                / (total_disclosed * total_disclosed) / period_days)

    def _greenium_sensitivity(self, v_fund: float,
                              period_days: int) -> float:
        """Treasury-clip monetization: q_bar * gamma * V_fund per day."""
        if self.ledger is None:
            return 0.0
        position = self.ledger.positions.get(self.asset.symbol) \
            if self.ledger.positions else None
        if position is None or position.shares <= 0:
            return 0.0
        clip = min(TREASURY_SELL_CLIP, position.shares)
        return (clip / period_days) * GREENIUM_GAMMA * v_fund

    def npv_per_unit(self, p_green: float, policy_rate: float,
                     epoch_budget: float, total_disclosed: float,
                     v_fund: float, funding_sensitivity: float,
                     bond_multiplier: float, period_days: int) -> float:
        """The WP5 marginal NPV of one unit of TRUE greenness (see module
        docstring for the derivation of every term)."""
        s_sub = self._subsidy_sensitivity(
            epoch_budget, total_disclosed,
            self.asset.disclosed_green_score, period_days)
        s_grn = self._greenium_sensitivity(v_fund, period_days)
        daily_benefit = (s_sub * bond_multiplier + s_grn
                         + funding_sensitivity - GREEN_MAINTENANCE_RATE)
        return (self._annuity(policy_rate) * daily_benefit
                - p_green * marginal_cost_curve(self.asset.true_green_score))

    # -- WP5: continuous, reversible transition dynamics ---------------------- #
    def transition_step(self, day: int, p_green: float, policy_rate: float,
                        epoch_budget: float, total_disclosed: float,
                        v_fund: float, funding_sensitivity: float,
                        bond_multiplier: float, period_days: int) -> float:
        """
        One daily step of dg/dt = TRANSITION_RESPONSIVENESS * NPV_per_unit,
        clamped to [-G_DECAY_MAX, +G_STEP_MAX] and g in [0, 1], with exact
        cash discipline for positive steps. Returns the realized dg.
        """
        asset = self.asset
        g = asset.true_green_score
        npv = self.npv_per_unit(p_green, policy_rate, epoch_budget,
                                total_disclosed, v_fund,
                                funding_sensitivity, bond_multiplier,
                                period_days)
        self.last_npv_per_unit = npv
        dg = TRANSITION_RESPONSIVENESS * npv
        if dg > G_STEP_MAX:
            dg = G_STEP_MAX
        elif dg < -G_DECAY_MAX:
            dg = -G_DECAY_MAX

        # WP1.6 counterfactual (pre-Omnibus): mandatory transition plans
        # prohibit backsliding and force a minimum daily step while g < 1.
        if self.regulation is not None \
                and self.regulation.transition_plans_mandatory:
            if g < 1.0 and dg < REG_MANDATED_MIN_STEP:
                dg = REG_MANDATED_MIN_STEP

        if dg > 0.0:
            dg = min(dg, 1.0 - g)
            if dg <= 0.0:
                self.last_dg = 0.0
                return 0.0
            # Cash discipline: spend = P_green * C'(g) * dg, cent-quantized,
            # only while the post-CAPEX balance clears the safety floor.
            spend_dec = Decimal(repr(round(
                p_green * marginal_cost_curve(g) * dg, 2))).quantize(
                CREDIT_CENT_DEC, rounding=ROUND_DOWN)
            floor = CORPORATE_BALANCE_FLOOR * GREEN_TRANSITION_SAFETY
            if asset.balance - float(spend_dec) < floor:
                self.last_dg = 0.0
                return 0.0
            if spend_dec > _ZERO:
                asset.balance -= float(spend_dec)   # OU-synced setter
                self.total_transition_spend_dec += spend_dec
            asset.set_true_score(g + dg)
            asset.last_transition_day = day
            # A real improvement is always (truthfully) disclosed at least
            # up to the true score -- free good news.
            if asset.disclosed_green_score < asset.true_green_score:
                asset.set_disclosed_score(asset.true_green_score, day)
        elif dg < 0.0:
            # Backsliding: certifications lapse, maintenance CAPEX is
            # reallocated. NO refund -- sunk costs stay sunk; the only
            # recovery is the maintenance saving that stops accruing.
            asset.set_true_score(g + dg)
            # Without the WP1 regulation layer there is no reporting
            # regime to lag behind: the market observes the physical
            # state directly, so the disclosed score tracks the true
            # score in BOTH directions (disclosed == true by
            # construction, preserving pre-Part-G Part F semantics).
            # Under regulation, a falling truth reaches the disclosed
            # score only through the next reporting period.
            if self.regulation is None:
                asset.set_disclosed_score(asset.true_green_score, day)
        self.last_dg = dg
        return dg

    def pay_maintenance(self) -> None:
        """
        Daily certification upkeep: m * g, cent-quantized, through the
        balance setter. If the balance cannot fund upkeep above the raw
        solvency floor, certifications decay instead of cash moving
        (endogenous distress backsliding; modeling choice).
        """
        g = self.asset.true_green_score
        if g <= 0.0:
            return
        cost_dec = Decimal(repr(round(GREEN_MAINTENANCE_RATE * g, 2))) \
            .quantize(CREDIT_CENT_DEC, rounding=ROUND_DOWN)
        if cost_dec <= _ZERO:
            return
        if self.asset.balance - float(cost_dec) < CORPORATE_BALANCE_FLOOR:
            self.asset.set_true_score(g - G_DECAY_MAX)
            return
        self.asset.balance -= float(cost_dec)
        self.total_maintenance_dec += cost_dec

    # -- WP2: disclosure policy ------------------------------------------------#
    def decide_disclosure(self, day: int, policy_rate: float,
                          epoch_budget: float, total_disclosed: float,
                          v_fund: float, funding_sensitivity: float,
                          state_daily_investment: float,
                          eligible_count: int, float_value: float,
                          period_days: int) -> float:
        """
        One reporting-period disclosure decision. Returns the disclosure
        inflation Dd chosen (0 for honest firms). All expected-profit
        terms are computed from live simulation state (see module
        docstring); nothing here is an oracle constant.
        """
        asset = self.asset
        regulation = self.regulation
        if regulation is None:
            return 0.0    # No regulation layer: disclosed tracks true.

        honest_mode = (self.strategy == 'honest'
                       or (self.strategy == 'adaptive'
                           and day - asset.last_scandal_day
                           <= ADAPTIVE_SCANDAL_MEMORY_DAYS))
        mandatory = regulation.is_mandatory_discloser(asset.firm_size, day)

        if honest_mode:
            self._disclose_honestly(day, mandatory)
            return 0.0
        return self._disclose_strategically(
            day, mandatory, policy_rate, epoch_budget, total_disclosed,
            v_fund, funding_sensitivity, state_daily_investment,
            eligible_count, float_value, period_days)

    def _disclose_honestly(self, day: int, mandatory: bool) -> None:
        """
        Truthful reporting with the WP1.4 omission exemption: downward
        revisions are damped by `omission_rate` up to the capped lawful
        buffer (commercial-prejudice / trade-secret omissions), never
        more. STYLIZATION: an honest VOLUNTARY reporter (Art. 29ca) could
        lawfully withhold bad news outright, but this build keeps honest
        firms truthful in both regimes -- outright non-publication of
        downward revisions is a strategic behaviour and is reserved to
        the greenwasher/adaptive types (whose disclosure base never
        reveals a falling truth at all).
        """
        asset = self.asset
        true = asset.true_green_score
        disclosed = asset.disclosed_green_score
        if true >= disclosed:
            asset.set_disclosed_score(true, day)
            asset.lawful_omission = 0.0
            return
        drop = disclosed - true
        withheld = min(asset.omission_rate * drop, REG_OMISSION_BUFFER_CAP)
        asset.set_disclosed_score(true + withheld, day)
        asset.lawful_omission = withheld

    def _disclose_strategically(self, day: int, mandatory: bool,
                                policy_rate: float, epoch_budget: float,
                                total_disclosed: float, v_fund: float,
                                funding_sensitivity: float,
                                state_daily_investment: float,
                                eligible_count: int, float_value: float,
                                period_days: int) -> float:
        """The WP2 one-period expected-profit argmax over Dd (see module
        docstring for the expression). Returns the chosen Dd."""
        asset = self.asset
        regulation = self.regulation
        # Free truthful news first: disclosed never lags a higher truth.
        base = max(asset.disclosed_green_score, asset.true_green_score)
        wedge_now = asset.unlawful_wedge

        # Live marginal benefit of one unit of DISCLOSED score per day.
        s_sub = self._subsidy_sensitivity(
            epoch_budget, total_disclosed, base, period_days)
        s_grn = self._greenium_sensitivity(v_fund, period_days)
        benefit_per_day = s_sub + s_grn + funding_sensitivity

        aversion = 1.0
        if self.strategy == 'adaptive':
            aversion += ADAPTIVE_RISK_AVERSION_STEP * self.scandal_count
        penalty = float(regulation.penalty_for(asset.balance))
        p_audit = regulation.audit_probability if mandatory else 0.0
        p_now = regulation.detection_probability(wedge_now)

        best_dd, best_profit = 0.0, 0.0
        for dd in GREENWASH_CHOICE_GRID:
            if dd > GREENWASH_MAX_WEDGE_STEP or base + dd > 1.0:
                continue
            gain = benefit_per_day * period_days * dd
            # Crossing the sovereign-fund threshold: captured share of the
            # incremental daily fund flow, priced from live State budgets.
            if base < STATE_GREEN_THRESHOLD <= base + dd \
                    and float_value > 0.0:
                extra_flow = state_daily_investment / (eligible_count + 1)
                gain += (extra_flow * period_days * SOVEREIGN_FLOW_CAPTURE)
            risk = 0.0
            if dd > 0.0 and mandatory:
                p_then = regulation.detection_probability(wedge_now + dd)
                risk = p_audit * (p_then - p_now) * penalty * aversion
            cost = GREENWASH_REPORT_COST if dd > 0.0 else 0.0
            profit = gain - risk - cost
            if profit > best_profit:
                best_profit, best_dd = profit, dd

        if best_dd > 0.0:
            # Cheap talk: pay the PR/reporting cost out of the balance
            # sheet (cent-quantized; orders of magnitude below real CAPEX).
            if self.asset.balance - GREENWASH_REPORT_COST \
                    > CORPORATE_BALANCE_FLOOR:
                self.asset.balance -= GREENWASH_REPORT_COST
                self.total_report_cost_dec += GREENWASH_REPORT_COST_DEC
                asset.set_disclosed_score(base + best_dd, day)
                return best_dd
            return 0.0
        asset.set_disclosed_score(base, day)
        return 0.0

    # -- WP2 channel (a): treasury sales into the greenium ---------------------#
    def sell_treasury(self, venue, day: int, v_fund: float) -> float:
        """
        Sells one treasury clip into the market when the price carries a
        premium over the TRUE-score fair value, then sweeps the proceeds
        into the corporate balance (market cash -> balance sheet; the
        Simulation tracks the sweep for the conservation audit). Returns
        the wedge-attributable greenium extraction estimate.
        """
        ledger = self.ledger
        if ledger is None:
            return 0.0
        position = ledger.positions.get(self.asset.symbol)
        if position is None or position.shares <= 0:
            return 0.0
        book = venue.order_book
        mid = book.get_midpoint(self.asset.get_last_price())
        v_fair_true = v_fund * (1.0 + GREENIUM_GAMMA
                                * self.asset.true_green_score)
        if v_fair_true <= 0.0 \
                or (mid - v_fair_true) / v_fair_true < TREASURY_MIN_PREMIUM:
            return 0.0
        qty = min(TREASURY_SELL_CLIP, position.shares)
        cash_before = ledger.cash
        book.execute_market_order(
            MarketOrder(ledger.trader_id, 'SELL', qty),
            venue.trader_map, day)
        proceeds = ledger.cash - cash_before
        if proceeds <= 0.0:
            return 0.0
        # Sweep: corporate wallet -> balance sheet (OU-synced setter).
        ledger.cash -= proceeds
        self.asset.balance += proceeds
        self.total_treasury_swept += proceeds
        # Channel (a) metric: proceeds above the true-score fair value.
        # ESTIMATE -- attributes the whole premium to the disclosure wedge.
        extraction = max(0.0, proceeds - qty * v_fair_true)
        self.harvest['greenium'] += extraction
        return extraction

    # -- WP1.5 / WP2: scandal dynamics ------------------------------------------#
    def on_scandal(self, day: int) -> None:
        """Audit detection hook: wedge reset + timestamps are applied on
        the Asset; this books the strategic memory for adaptive firms."""
        self.scandal_count += 1
        self.asset.apply_scandal(day)
