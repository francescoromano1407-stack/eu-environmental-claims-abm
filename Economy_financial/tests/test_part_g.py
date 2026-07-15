"""
Part G deterministic unit tests (cross-cutting requirement 6).

Covers the six mandated properties:
  (a) wedge detection probability monotonicity        (WP1.3)
  (b) penalty ledger symmetry                          (WP1.5)
  (c) mixture-weight simplex invariance                (WP4)
  (d) sign of dg/dt flipping with P_green              (WP5)
  (e) RR monotonicity in green share                   (WP7)
  (f) green-bond proceeds earmarking                   (WP6)

All tests are deterministic: RNG is either unused or explicitly seeded.
Run from the repository root:  python -m unittest discover -s tests
"""

import random
import unittest
from decimal import Decimal
from types import SimpleNamespace

from market_sim.constants import (
    CORPORATE_BALANCE_FLOOR,
    GREEN_BOND_FACE_DEC,
    OMEGA_MIN,
)
from market_sim.corporates import CorporatePolicy
from market_sim.credit_market import (
    BANK_ID,
    CommercialBank,
    CreditLine,
    CreditMarket,
)
from market_sim.models import Asset
from market_sim.order_book import OrderBook
from market_sim.regulation import ESGRegulation
from market_sim.state_intervention import State
from market_sim.traders import Trader


class TestDetectionMonotonicity(unittest.TestCase):
    """(a) The limited-assurance detection curve is monotone in the wedge."""

    def test_probability_is_monotone_nondecreasing(self):
        regulation = ESGRegulation()
        wedges = [i / 100.0 for i in range(0, 101)]
        probs = [regulation.detection_probability(w) for w in wedges]
        for lo, hi in zip(probs, probs[1:]):
            self.assertLessEqual(lo, hi)

    def test_sub_tolerance_wedges_are_undetectable(self):
        regulation = ESGRegulation()
        self.assertEqual(regulation.detection_probability(0.0), 0.0)
        self.assertEqual(
            regulation.detection_probability(regulation.wedge_tolerance),
            0.0)

    def test_large_wedge_approaches_certainty(self):
        regulation = ESGRegulation()
        self.assertGreater(regulation.detection_probability(1.0), 0.99)


class TestPenaltyLedgerSymmetry(unittest.TestCase):
    """(b) A sanction is a transfer: corporate balance -> State treasury,
    with the identical amount on both legs (Decimal canon + float mirror)."""

    def test_penalty_transfer_is_symmetric(self):
        regulation = ESGRegulation()
        asset = Asset("TST", 100.0, 500_000.0)
        ledger = Trader("T_STATE", cash=5_000_000.0, shares=0,
                        trader_type='state')
        state = State(ledger)

        balance_before = asset.balance
        treasury_before = state.treasury_dec
        wallet_before = ledger.cash

        penalty_dec = regulation.penalty_for(asset.balance)
        self.assertGreater(penalty_dec, Decimal("0"))
        # 3% of the 0.5x-balance turnover proxy, cent-quantized.
        self.assertEqual(
            penalty_dec,
            (Decimal("0.03") * Decimal("0.50")
             * Decimal(repr(round(asset.balance, 2)))).quantize(
                Decimal("0.01")))

        asset.balance -= float(penalty_dec)
        state.receive_penalty(penalty_dec)
        regulation.record_scandal(10, "TST", 0.3, penalty_dec)

        self.assertEqual(state.penalty_inflow_dec, penalty_dec)
        self.assertEqual(state.treasury_dec - treasury_before, penalty_dec)
        self.assertEqual(regulation.total_penalties_dec, penalty_dec)
        # Float legs are the identical mirror on both sides.
        self.assertAlmostEqual(balance_before - asset.balance,
                               float(penalty_dec), places=9)
        self.assertAlmostEqual(ledger.cash - wallet_before,
                               float(penalty_dec), places=9)
        # WP1.5 audit identity.
        self.assertEqual(regulation.total_penalties_dec,
                         state.penalty_inflow_dec)


class TestMixtureSimplexInvariance(unittest.TestCase):
    """(c) The WP4 evolutionary weight step keeps w on the simplex."""

    def test_weight_steps_preserve_simplex(self):
        trader = Trader("T_X", cash=10_000.0, shares=0,
                        trader_type='noise')
        trader.enable_mixture((0.40, 0.10, 0.50))
        book = OrderBook()
        trader_map = {trader.trader_id: trader}

        targets = [0, 2, 1, 1, 0, 2, 2, 0, 1, 2] * 20
        for target in targets:
            moved = trader.apply_weight_step(target, 0.25, 1, book,
                                             trader_map)
            self.assertGreaterEqual(moved, 0.0)
            w = trader.weights
            self.assertAlmostEqual(sum(w), 1.0, places=12)
            for component in w:
                self.assertGreaterEqual(component, 0.0)
                self.assertLessEqual(component, 1.0)

    def test_dominant_label_tracks_weights(self):
        trader = Trader("T_Y", cash=10_000.0, shares=0,
                        trader_type='noise')
        trader.enable_mixture((0.34, 0.33, 0.33))
        book = OrderBook()
        trader_map = {trader.trader_id: trader}
        for _ in range(10):     # Push hard toward the chartist vertex.
            trader.apply_weight_step(2, 0.25, 1, book, trader_map)
        self.assertEqual(trader.type, 'chartist')
        self.assertIn('chartist', trader.label)

    def test_vertices_are_absorbing_only_under_own_target(self):
        trader = Trader("T_Z", cash=10_000.0, shares=0,
                        trader_type='fundamentalist')
        trader.enable_mixture(None)      # Exact legacy vertex.
        book = OrderBook()
        trader_map = {trader.trader_id: trader}
        moved = trader.apply_weight_step(1, 0.25, 1, book, trader_map)
        self.assertEqual(moved, 0.0)     # Already at the target vertex.
        self.assertEqual(trader.weights, (0.0, 1.0, 0.0))


class TestTransitionSignFlip(unittest.TestCase):
    """(d) dg/dt is positive when green capital is cheap and turns
    negative (backsliding, no refund) when P_green is expensive."""

    def _make_policy(self):
        asset = Asset("NPV", 100.0, 500_000.0, green_score=0.3)
        return CorporatePolicy(asset, 'honest', None, None), asset

    def test_cheap_green_capital_gives_positive_dg(self):
        policy, asset = self._make_policy()
        balance_before = asset.balance
        dg = policy.transition_step(
            day=10, p_green=0.01, policy_rate=0.05, epoch_budget=50_000.0,
            total_disclosed=5.0, v_fund=100.0, funding_sensitivity=0.0,
            bond_multiplier=1.0, period_days=60)
        self.assertGreater(dg, 0.0)
        self.assertGreater(asset.true_green_score, 0.3)
        self.assertLess(asset.balance, balance_before)   # Real CAPEX paid.

    def test_expensive_green_capital_gives_negative_dg(self):
        policy, asset = self._make_policy()
        balance_before = asset.balance
        dg = policy.transition_step(
            day=10, p_green=50.0, policy_rate=0.05, epoch_budget=50_000.0,
            total_disclosed=5.0, v_fund=100.0, funding_sensitivity=0.0,
            bond_multiplier=1.0, period_days=60)
        self.assertLess(dg, 0.0)
        self.assertLess(asset.true_green_score, 0.3)
        # Backsliding refunds NOTHING: the balance must not increase.
        self.assertEqual(asset.balance, balance_before)

    def test_solvency_floor_blocks_spend(self):
        asset = Asset("FLR", 100.0, CORPORATE_BALANCE_FLOOR + 1.0,
                      green_score=0.3)
        policy = CorporatePolicy(asset, 'honest', None, None)
        dg = policy.transition_step(
            day=10, p_green=0.01, policy_rate=0.05, epoch_budget=50_000.0,
            total_disclosed=5.0, v_fund=100.0, funding_sensitivity=0.0,
            bond_multiplier=1.0, period_days=60)
        self.assertEqual(dg, 0.0)        # Cannot fund CAPEX near the floor.


class TestReserveMonotonicity(unittest.TestCase):
    """(e) Required reserves decrease in the disclosed green share."""

    def _rr_for(self, disclosed_score: float,
                regulation: ESGRegulation) -> Decimal:
        bank = CommercialBank()
        credit = CreditMarket(bank, OrderBook())
        asset = Asset("COL", 100.0, 500_000.0)
        if disclosed_score > 0.0:
            asset.set_disclosed_score(disclosed_score, 1)
        credit.esg_regulation = regulation
        credit.collateral_asset = asset
        line = CreditLine(1, "T_B", BANK_ID, Decimal("100000.00"), 100, 1)
        credit.lines[1] = line
        credit.update_reserve_requirements()
        return bank.required_reserves_dec

    def test_rr_monotone_decreasing_in_green_share(self):
        regulation = ESGRegulation()
        scores = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
        rrs = [self._rr_for(s, regulation) for s in scores]
        for hi, lo in zip(rrs, rrs[1:]):
            self.assertGreater(hi, lo)
        # Exact endpoints: omega(0) = 1, omega(1) = 1 - discount = 0.5.
        self.assertEqual(rrs[0], Decimal("10000.00"))
        self.assertEqual(rrs[-1], Decimal("5000.00"))

    def test_omega_floor_keeps_weights_strictly_positive(self):
        regulation = ESGRegulation()
        regulation.green_risk_weight_discount = 1.0   # Policy experiment.
        rr = self._rr_for(1.0, regulation)
        floored = (Decimal("0.10") * Decimal("100000.00")
                   * Decimal(repr(OMEGA_MIN))).quantize(Decimal("0.01"))
        self.assertEqual(rr, floored)


class TestGreenBondEarmarking(unittest.TestCase):
    """(f) Bond proceeds fund ONLY subsidies / fund purchases; generic
    outflows (coupons, redemptions) come from unearmarked treasury."""

    def _make_state(self, treasury: str) -> State:
        ledger = Trader("T_STATE", cash=float(Decimal(treasury)), shares=0,
                        trader_type='state')
        state = State(ledger)
        state.treasury_dec = Decimal(treasury)
        return state

    def test_issue_earmarks_proceeds_and_identity_holds(self):
        random.seed(7)
        regulation = ESGRegulation()
        state = self._make_state("1000000.00")   # Below issue threshold.
        rich = Trader("T_RICH", cash=1_000_000.0, shares=0,
                      trader_type='noise')
        issued = state.issue_green_bonds(
            10, 0.05, None, {"T_RICH": rich}, regulation)
        self.assertGreaterEqual(issued, 1)
        self.assertEqual(state.green_proceeds_dec,
                         GREEN_BOND_FACE_DEC * issued)
        self.assertEqual(state.bonds_issued_dec,
                         state.green_proceeds_dec
                         + state.green_proceeds_spent_dec)
        # Buyer paid exactly par, treasury mirror moved symmetrically.
        self.assertAlmostEqual(rich.cash,
                               1_000_000.0 - float(GREEN_BOND_FACE_DEC)
                               * issued, places=6)

    def test_subsidies_drain_earmarked_pool_first(self):
        state = self._make_state("1000000.00")
        state.green_proceeds_dec = Decimal("100000.00")
        state.bonds_issued_dec = Decimal("100000.00")
        venues = [SimpleNamespace(asset=Asset("GRN", 100.0, 300_000.0,
                                              green_score=0.8),
                                  policy=None)]
        paid = state.pay_subsidies(venues, 60, None)
        self.assertGreater(paid, 0.0)
        spent_dec = Decimal(repr(round(paid, 2)))
        self.assertEqual(state.green_proceeds_dec,
                         Decimal("100000.00") - spent_dec)
        self.assertEqual(state.green_proceeds_spent_dec, spent_dec)
        # The WP6 identity survives the green spend.
        self.assertEqual(state.bonds_issued_dec,
                         state.green_proceeds_dec
                         + state.green_proceeds_spent_dec)

    def test_generic_outflows_never_touch_earmarked_euros(self):
        random.seed(7)
        regulation = ESGRegulation()
        state = self._make_state("1000000.00")
        rich = Trader("T_RICH", cash=1_000_000.0, shares=0,
                      trader_type='noise')
        state.issue_green_bonds(10, 0.05, None, {"T_RICH": rich},
                                regulation)
        # Make EVERY treasury euro earmarked: coupons must then stall
        # with a sovereign-stress event instead of spending green money.
        state.green_proceeds_dec = state.treasury_dec
        bond = state.bonds[0]
        coupon_day = bond.issue_day + 30    # GREEN_BOND_COUPON_PERIOD_DAYS
        proceeds_before = state.green_proceeds_dec
        state.service_bonds(coupon_day, None, {"T_RICH": rich})
        self.assertEqual(state.green_proceeds_dec, proceeds_before)
        self.assertEqual(state.coupons_paid_dec, Decimal("0"))
        self.assertGreaterEqual(state.sovereign_stress_events, 1)

    def test_redemption_rolls_under_stress(self):
        random.seed(7)
        regulation = ESGRegulation()
        state = self._make_state("1000000.00")
        rich = Trader("T_RICH", cash=1_000_000.0, shares=0,
                      trader_type='noise')
        state.issue_green_bonds(10, 0.05, None, {"T_RICH": rich},
                                regulation)
        state.green_proceeds_dec = state.treasury_dec   # Fully earmarked.
        bond = state.bonds[0]
        maturity = bond.maturity_day
        state.service_bonds(maturity, None, {"T_RICH": rich})
        self.assertTrue(bond.active)                    # Rolled, not paid.
        self.assertEqual(bond.rolled, 1)
        self.assertGreater(bond.maturity_day, maturity)


if __name__ == '__main__':
    unittest.main()
