from decimal import Decimal
from types import SimpleNamespace

from market_sim.credit_market import (
    BANK_ID,
    CommercialBank,
    CreditLine,
    CreditMarket,
)
from market_sim.environmental_claims import InvestorEnvironmentalContext
from market_sim.models import Asset
from market_sim.order_book import OrderBook
from market_sim.regulation import ESGRegulation
from market_sim.state_intervention import State
from market_sim.traders import Trader


def test_fundamentalist_fair_value_uses_posterior_and_controversy_once():
    trader = Trader("F", 10_000, 10, "fundamentalist")
    trader.sophisticated = True
    clean = InvestorEnvironmentalContext(0.8, credibility=0.8,
                                         controversy_discount=0.0)
    controversy = InvestorEnvironmentalContext(
        0.8, credibility=0.8, controversy_discount=0.20)
    low_score = InvestorEnvironmentalContext(0.3, credibility=0.8,
                                             controversy_discount=0.0)
    v_clean = trader.environmental_fair_value(100.0,
                                               environmental_context=clean)
    v_bad = trader.environmental_fair_value(
        100.0, environmental_context=controversy)
    v_low = trader.environmental_fair_value(
        100.0, environmental_context=low_score)
    assert v_clean > v_low
    assert v_clean > v_bad
    expected = 100.0 * (1.0 + trader.GREENIUM_GAMMA * 0.8 * 0.8) * 0.8
    assert v_bad == expected


def test_sophisticated_investor_applies_larger_controversy_discount():
    sophisticated = Trader("S", 10_000, 10, "fundamentalist")
    unsophisticated = Trader("U", 10_000, 10, "fundamentalist")
    sophisticated.sophisticated = True
    context = InvestorEnvironmentalContext(
        0.7, credibility=0.8, controversy_discount=0.25)
    assert sophisticated.environmental_fair_value(
        100, environmental_context=context) \
        < unsophisticated.environmental_fair_value(
            100, environmental_context=context)


def test_state_uses_supported_score_and_raw_disclosure_only_when_explicit():
    ledger = Trader("STATE", 10_000_000, 0, "state")
    state = State(ledger)
    low_supported = Asset("A", green_score=0.2)
    high_supported = Asset("B", green_score=0.8)
    low_supported.set_disclosed_score(0.9, 1)
    high_supported.set_disclosed_score(0.4, 1)
    low_supported.supported_green_score = 0.2
    high_supported.supported_green_score = 0.8
    venues = [SimpleNamespace(symbol="A", asset=low_supported, policy=None),
              SimpleNamespace(symbol="B", asset=high_supported, policy=None)]
    before = {v.symbol: v.asset.balance for v in venues}
    state.pay_subsidies(venues, 60, ESGRegulation(),
                        use_supported_information=True)
    supported_gain = {v.symbol: v.asset.balance - before[v.symbol]
                      for v in venues}
    assert supported_gain["B"] > supported_gain["A"]

    ledger2 = Trader("STATE2", 10_000_000, 0, "state")
    counterfactual_state = State(ledger2)
    before = {v.symbol: v.asset.balance for v in venues}
    counterfactual_state.pay_subsidies(
        venues, 60, ESGRegulation(), use_supported_information=True,
        raw_disclosure_counterfactual=True)
    raw_gain = {v.symbol: v.asset.balance - before[v.symbol]
                for v in venues}
    assert raw_gain["A"] > raw_gain["B"]


def _reserve_requirement(use_supported, raw_counterfactual=False):
    bank = CommercialBank()
    credit = CreditMarket(bank, OrderBook())
    credit.esg_regulation = ESGRegulation()
    asset = Asset("COLL", green_score=0.0)
    asset.set_disclosed_score(1.0, 1)
    asset.supported_green_score = 0.0
    credit.collateral_asset = asset
    credit.use_supported_environmental_information = use_supported
    credit.raw_disclosure_counterfactual = raw_counterfactual
    line = CreditLine(1, "B", BANK_ID, Decimal("100000.00"), 10, 1)
    credit.lines[1] = line
    credit.update_reserve_requirements()
    return bank.required_reserves_dec


def test_bank_uses_supported_information_unless_counterfactual_is_explicit():
    supported_rr = _reserve_requirement(True)
    raw_rr = _reserve_requirement(True, raw_counterfactual=True)
    legacy_raw_rr = _reserve_requirement(False)
    assert supported_rr > raw_rr
    assert raw_rr == legacy_raw_rr
