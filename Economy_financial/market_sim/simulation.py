"""
Macro-orchestrator of the agent-based financial market simulation.

`Simulation` wires the full daily cycle: OU fundamental updates (Part B),
volume-regime friction and probabilistic LOB decay (Part D), adaptive MM
quoting and backstop depth (Part C), manipulator activity, randomized
trader participation, solvency-constrained dividends, interest accrual,
bankruptcy reseeding, and the capped logit-driven evolutionary review
(Part A). `export_simulation_metrics` provides the CSV export pipeline.

Shares outstanding are a structural invariant of the closed system: they
change only when a bankrupt trader is reseeded. The total is therefore
maintained as a stateful counter (updated at trader creation/removal)
instead of being re-summed over every participant inside the per-trader
decision loop, turning the former O(N^2) daily path into O(N).

Conservation audit hooks: `total_interest_paid`, `total_dividends_paid`,
`total_reseed_cash` / `total_reseed_shares`, and
`total_bankrupt_cash_removed` accumulate every flow that legitimately
enters or leaves the participants' combined ledgers, complementing
`OrderBook.total_fees_collected` so a closed-system wealth audit can
balance to numerical precision.

Side-effect isolation: matplotlib is imported lazily inside
`plot_dashboard`, so importing this module (or the package) performs no
backend selection, spawns no GUI machinery, and executes nothing at
global scope beyond definitions.
"""

from __future__ import annotations

import collections
import csv
import math
import random
from typing import Optional

from market_sim.constants import (
    BASE_DIVIDEND_PER_SHARE,
    COMMISSION_RATE_SPAN,
    CORPORATE_BALANCE_FLOOR,
    EVOLUTION_EPOCH_DAYS,
    GREEN_TRANSITION_COST,
    GREEN_TRANSITION_SAFETY,
    GREEN_TRANSITION_STEP,
    INTENSITY_OF_CHOICE,
    LAMBDA_MEMORY,
    MAX_SWITCH_FRACTION,
    MIN_COMMISSION_RATE,
    MIN_TOBIN_RATE,
    ORDER_DECAY_AGE_SCALE,
    ORDER_DECAY_BASE_HAZARD,
    ORDER_DECAY_MAX_HAZARD,
    STATE_TREASURY,
    STRATEGY_MEMORY,
    SWITCH_CONSIDERATION_RATE,
    TOBIN_RATE_SPAN,
)
from market_sim.credit_market import CentralBank, CommercialBank, CreditMarket
from market_sim.models import (
    Asset,
    AssetPosition,
    IncrementalEMA,
    LimitOrder,
    MarketOrder,
)
from market_sim.order_book import OrderBook
from market_sim.state_intervention import STATE_ID, State
from market_sim.traders import (
    GreenManipulator,
    Manipulator,
    MarketMaker,
    Trader,
)

# Default listing profiles for the ESG multi-asset ecosystem (Part F):
# ten firms spanning the brown -> green spectrum, (symbol, green_score).
# Overridable via Simulation(asset_profiles=...).
DEFAULT_ESG_PROFILES = (
    ("BRN1", 0.05), ("BRN2", 0.15), ("BRN3", 0.25),
    ("MID1", 0.35), ("MID2", 0.45), ("MID3", 0.55), ("MID4", 0.65),
    ("GRN1", 0.75), ("GRN2", 0.85), ("GRN3", 0.95),
)


class MarketVenue:
    """
    One listed asset's complete market microstructure (Part F): the asset,
    its own OrderBook (matching mechanics reused byte-identical), a
    dedicated MarketMaker, per-venue EMAs / volatility / volume regime,
    the venue trader_map of AssetPosition views, and its log series.
    """

    __slots__ = ("symbol", "asset", "order_book", "market_maker",
                 "ema_fast", "ema_slow", "recent_closes", "recent_volumes",
                 "volume_baseline", "trader_map", "shares_outstanding",
                 "log_price", "log_balance", "log_green_score")

    def __init__(self, symbol: str, initial_price: float):
        self.symbol = symbol
        self.asset: Optional[Asset] = None   # Built after the float is known
        self.order_book = OrderBook()
        self.market_maker: Optional[MarketMaker] = None
        self.ema_fast = IncrementalEMA(period=5)
        self.ema_slow = IncrementalEMA(period=15)
        self.ema_fast.update(initial_price)
        self.ema_slow.update(initial_price)
        self.recent_closes: collections.deque = collections.deque(
            [initial_price], maxlen=20)
        self.recent_volumes: collections.deque = collections.deque(maxlen=10)
        self.volume_baseline = IncrementalEMA(period=60)
        self.trader_map: dict = {}
        self.shares_outstanding = 0
        self.log_price: list[float] = []
        self.log_balance: list[float] = []


class Simulation:
    """Main executor of the agent-based financial market simulation."""

    STRATEGIES = ('noise', 'fundamentalist', 'chartist')

    def __init__(self, num_traders: int = 60, initial_cash: float = 10_000.0,
                 initial_shares: int = 50, initial_price: float = 100.0,
                 rf_rate: float = 0.02, days: int = 1000,
                 num_manipulators: int = 2, enable_credit: bool = True,
                 enable_esg: bool = False,
                 asset_profiles: Optional[list] = None):
        self.days = days
        self.rf_rate = rf_rate
        self.initial_cash = initial_cash
        self.initial_shares = initial_shares
        self.initial_price = initial_price

        self.traders: list[Trader] = []          # Evolutionary population only
        self.trader_map: dict[str, Trader] = {}  # ALL participants (incl. MM)
        self.next_trader_id_counter = 0

        # Part F: multi-asset ESG mode is opt-in; None keeps every legacy
        # single-asset code path (and the baseline trajectory) untouched.
        self.venues: Optional[list[MarketVenue]] = None
        self.state: Optional[State] = None
        self.central_bank: Optional[CentralBank] = None
        self.total_subsidies_paid = 0.0
        self.green_transitions = 0
        self._multi_asset = bool(enable_esg or asset_profiles is not None)

        # Structural invariant: total float across ALL holders. Updated
        # only at trader creation/removal (bankruptcy reseeding) -- trades,
        # escrow moves, dividends and interest never change it.
        self._shares_outstanding = 0

        # Conservation-audit accumulators (exact flow bookkeeping).
        self.total_interest_paid = 0.0
        self.total_dividends_paid = 0.0
        self.total_reseed_cash = 0.0
        self.total_reseed_shares = 0
        self.total_bankrupt_cash_removed = 0.0

        if self._multi_asset:
            # Part F: the entire single-asset construction below is
            # replaced by the venue-based ecosystem; nothing else runs.
            self._init_multi_asset(
                list(asset_profiles or DEFAULT_ESG_PROFILES), num_traders,
                num_manipulators, enable_credit, enable_esg)
            return

        # Seed the evolutionary population in three equal cohorts.
        noise_count = num_traders // 3
        fund_count = num_traders // 3
        chart_count = num_traders - noise_count - fund_count
        for _ in range(noise_count):
            self.create_and_add_trader('noise')
        for _ in range(fund_count):
            self.create_and_add_trader('fundamentalist')
        for _ in range(chart_count):
            self.create_and_add_trader('chartist')

        # The MM lives in `trader_map` (so it settles trades) AND in
        # `macro_participants` (dividends and interest), but NOT in
        # `self.traders` (it is not subject to evolution).
        self.market_maker = MarketMaker(
            trader_id="T_MM", cash=1_000_000.0, shares=10_000,
            target_inventory=10_000, level_qty=15, num_levels=5)
        self.trader_map["T_MM"] = self.market_maker
        self._shares_outstanding += self.market_maker.total_shares

        # Manipulators -- also full macro participants.
        self.manipulators: list[Manipulator] = []
        for i in range(num_manipulators):
            manip = Manipulator(
                trader_id=f"T_MANIP_{i + 1}", cash=500_000.0, shares=2_000,
                spoof_size=400, attack_size=40)
            self.manipulators.append(manip)
            self.trader_map[manip.trader_id] = manip
            self._shares_outstanding += manip.total_shares

        # Asset and book. Part B, fix 3: the corporate balance is seeded
        # from the TRUE float (all holders, incl. MM and Manipulators) so
        # fundamental value == initial price at t=0 instead of starting the
        # market structurally ~58% overvalued.
        initial_balance = self.total_shares_outstanding() * initial_price
        self.asset = Asset("XYZ", initial_price, initial_balance)
        self.order_book = OrderBook()

        # Part E: optional credit layer. When disabled (the default) no
        # bank exists, the clearing-house slot stays None, and every
        # credit code path is provably unreachable -- the baseline
        # trajectory is preserved bit-for-bit.
        self.commercial_bank: Optional[CommercialBank] = None
        self.credit_market: Optional[CreditMarket] = None
        if enable_credit:
            self.commercial_bank = CommercialBank()
            self.credit_market = CreditMarket(self.commercial_bank,
                                              self.order_book)
            self.order_book.clearing_house = self.credit_market

        # One shared incremental EMA pair for the whole market (O(1)/day).
        self.ema_fast = IncrementalEMA(period=5)
        self.ema_slow = IncrementalEMA(period=15)
        self.ema_fast.update(initial_price)
        self.ema_slow.update(initial_price)

        # Rolling window of recent closes for volatility estimation.
        self.recent_closes: collections.deque = collections.deque(
            [initial_price], maxlen=20)

        # Part D, fix 1: volume regime tracking for dynamic friction.
        self.recent_volumes: collections.deque = collections.deque(maxlen=10)
        self.volume_baseline = IncrementalEMA(period=60)

        # Part A: logit-evolution state -- smoothed strategy attractiveness
        # and the per-strategy average wealth recorded at the last epoch.
        self.strategy_attractiveness = {s: 0.0 for s in self.STRATEGIES}
        self._epoch_wealth_marker: dict[str, Optional[float]] = {
            s: None for s in self.STRATEGIES}
        # Per-trader wealth computed by the latest evolutionary review,
        # reusable by same-day logging (avoids a duplicate wealth pass).
        self._epoch_wealth_cache: dict[str, float] = {}

        # Logging. All strategy series (incl. the two specialist agents).
        self.log_price = [initial_price]
        self.log_balance = [initial_balance]
        self.log_demographics = {s: [] for s in self.STRATEGIES}
        self.log_avg_wealth = {s: [] for s in self.STRATEGIES}
        self.log_mm_wealth: list[float] = []
        self.log_manip_wealth: list[float] = []
        # Part E credit series (all-zero when the credit layer is off).
        self.log_credit_outstanding: list[float] = []
        self.log_credit_rate: list[float] = []
        self.log_liquidations: list[int] = []
        # Part F policy-rate series (all-zero without a central bank).
        self.log_policy_rate: list[float] = []

    # -- Part F: multi-asset ecosystem construction --------------------------- #
    def _init_multi_asset(self, profiles: list, num_traders: int,
                          num_manipulators: int, enable_credit: bool,
                          enable_esg: bool) -> None:
        """
        Builds the ESG multi-asset ecosystem: one MarketVenue per listing
        (own OrderBook + MarketMaker + regime state), shared-wallet
        participants holding per-venue AssetPosition views, the State
        fiscal entity, the CentralBank, and the credit layer bound to the
        primary listing (venue 0).
        """
        self.venues = [MarketVenue(sym, self.initial_price)
                       for sym, _ in profiles]
        self._green_profiles = {sym: score for sym, score in profiles}

        # Evolutionary population: shared wallets, per-venue positions.
        noise_count = num_traders // 3
        fund_count = num_traders // 3
        chart_count = num_traders - noise_count - fund_count
        for trader_type, count in (('noise', noise_count),
                                   ('fundamentalist', fund_count),
                                   ('chartist', chart_count)):
            for _ in range(count):
                self.create_and_add_trader(trader_type)

        # One dedicated MarketMaker per venue (own wallet and inventory).
        for venue in self.venues:
            mm = MarketMaker(
                trader_id=f"T_MM_{venue.symbol}", cash=1_000_000.0,
                shares=10_000, target_inventory=10_000, level_qty=15,
                num_levels=5)
            venue.market_maker = mm
            venue.trader_map[mm.trader_id] = mm
            venue.shares_outstanding += mm.total_shares
            self.trader_map[mm.trader_id] = mm
        self.market_maker = self.venues[0].market_maker  # Legacy alias

        # Green Manipulators: multi-venue greenwashing FSMs.
        self.manipulators: list[Manipulator] = []
        for i in range(num_manipulators):
            manip = GreenManipulator(
                trader_id=f"T_MANIP_{i + 1}", cash=500_000.0, shares=0,
                spoof_size=400, attack_size=40)
            manip.positions = {}
            for venue in self.venues:
                self._add_position(venue, manip, 2_000)
            self.manipulators.append(manip)
            self.trader_map[manip.trader_id] = manip

        # The State: fiscal entity with a Trader shell for settlement
        # ('state' has no decision handler, so it can never emit retail
        # orders). Holds positions so sovereign-fund buys can settle.
        state_ledger = Trader(STATE_ID, cash=STATE_TREASURY, shares=0,
                              trader_type='state')
        state_ledger.positions = {}
        for venue in self.venues:
            self._add_position(venue, state_ledger, 0)
        self.state = State(state_ledger)
        self.trader_map[STATE_ID] = state_ledger

        # Each corporate balance is seeded from that venue's TRUE float;
        # Asset.__init__ then applies the historical green CAPEX penalty.
        for venue in self.venues:
            venue.asset = Asset(
                venue.symbol, self.initial_price,
                venue.shares_outstanding * self.initial_price,
                green_score=self._green_profiles[venue.symbol])
            venue.log_price.append(self.initial_price)
            venue.log_balance.append(venue.asset.balance)
            venue.log_green_score = [venue.asset.green_score]  # Initialize tracker

        # Legacy aliases: the primary listing backs every single-asset
        # accessor (asset, order_book, EMAs, volatility window), so
        # external tooling keeps working unmodified.
        primary = self.venues[0]
        self.asset = primary.asset
        self.order_book = primary.order_book
        self.ema_fast = primary.ema_fast
        self.ema_slow = primary.ema_slow
        self.recent_closes = primary.recent_closes
        self.recent_volumes = primary.recent_volumes
        self.volume_baseline = primary.volume_baseline

        # Part E credit layer, bound to the primary listing's book and
        # position views (margin lending on the primary collateral).
        self.commercial_bank: Optional[CommercialBank] = None
        self.credit_market: Optional[CreditMarket] = None
        if enable_credit:
            self.commercial_bank = CommercialBank()
            self.credit_market = CreditMarket(self.commercial_bank,
                                              primary.order_book)
            primary.order_book.clearing_house = self.credit_market

        # Part F monetary policy: Taylor rule with Gaussian surprise,
        # anchored on economy-wide price growth and volume output gaps.
        if enable_esg:
            self.central_bank = CentralBank()
            if self.credit_market is not None:
                self.credit_market.central_bank = self.central_bank
        self._taylor_volume_baseline = IncrementalEMA(period=60)

        # Part A evolution state + logging (legacy series map to venue 0).
        self.strategy_attractiveness = {s: 0.0 for s in self.STRATEGIES}
        self._epoch_wealth_marker: dict[str, Optional[float]] = {
            s: None for s in self.STRATEGIES}
        self._epoch_wealth_cache: dict[str, float] = {}

        self.log_price = [self.initial_price]
        self.log_balance = [primary.asset.balance]
        self.log_demographics = {s: [] for s in self.STRATEGIES}
        self.log_avg_wealth = {s: [] for s in self.STRATEGIES}
        self.log_mm_wealth: list[float] = []
        self.log_manip_wealth: list[float] = []
        self.log_credit_outstanding: list[float] = []
        self.log_credit_rate: list[float] = []
        self.log_liquidations: list[int] = []
        self.log_policy_rate: list[float] = []

    def _add_position(self, venue: MarketVenue, owner: Trader,
                      shares: int, current_day: int = 0) -> AssetPosition:
        """Registers an owner's per-venue position view with the venue."""
        position = AssetPosition(owner, shares, current_day)
        position.book = venue.order_book
        position.book_map = venue.trader_map
        owner.positions[venue.symbol] = position
        venue.trader_map[owner.trader_id] = position
        venue.shares_outstanding += position.total_shares
        return position

    # -- participant helpers ------------------------------------------------ #
    def macro_participants(self):
        """Every entity that receives dividends and interest."""
        yield from self.traders
        if self.venues is not None:
            for venue in self.venues:
                yield venue.market_maker
        else:
            yield self.market_maker
        yield from self.manipulators

    def total_shares_outstanding(self) -> int:
        """
        True float across ALL holders (stateful structural invariant).
        In multi-asset mode this reports the primary listing's float.
        """
        if self.venues is not None:
            return self.venues[0].shares_outstanding
        return self._shares_outstanding

    def create_and_add_trader(self, trader_type: str,
                              current_day: int = 0) -> Trader:
        self.next_trader_id_counter += 1
        t_id = f"T_{trader_type[0].upper()}_{self.next_trader_id_counter}"
        if self.venues is not None:
            # Multi-asset: shared wallet, per-venue position views seeded
            # with the standard endowment on every listing.
            trader = Trader(t_id, self.initial_cash, 0, trader_type,
                            current_day=current_day)
            trader.positions = {}
            for venue in self.venues:
                self._add_position(venue, trader, self.initial_shares,
                                   current_day)
        else:
            trader = Trader(t_id, self.initial_cash, self.initial_shares,
                            trader_type, current_day=current_day)
            self._shares_outstanding += trader.total_shares
        self.traders.append(trader)
        self.trader_map[t_id] = trader
        return trader

    def _trader_wealth(self, trader: Trader, current_price: float) -> float:
        """Mark-to-market wealth; portfolio-wide in multi-asset mode."""
        positions = trader.positions
        if positions is None:
            return trader.get_wealth(current_price)
        wealth = trader.cash + trader.cash_reserved + trader.cash_lent
        for venue in self.venues:
            position = positions.get(venue.symbol)
            if position is not None:
                wealth += position.total_shares \
                    * venue.asset.get_last_price()
        return wealth

    def _holder_total_shares(self, trader: Trader) -> int:
        """Total share exposure across every listing (legacy: one asset)."""
        if trader.positions is None:
            return trader.total_shares
        return sum(p.total_shares for p in trader.positions.values())

    def get_fundamental_value(self) -> float:
        """Intrinsic value = corporate balance / shares outstanding. O(1)."""
        if self.venues is not None:
            return self._venue_fundamental(self.venues[0])
        shares = self._shares_outstanding
        if shares <= 0:
            return self.asset.get_last_price()
        return self.asset.balance / shares

    @staticmethod
    def _venue_fundamental(venue: MarketVenue) -> float:
        shares = venue.shares_outstanding
        if shares <= 0:
            return venue.asset.get_last_price()
        return venue.asset.balance / shares

    def is_weekend(self, day: int) -> bool:
        return (day % 7) == 6 or (day % 7) == 0

    def current_volatility(self) -> float:
        """
        Relative realised volatility of recent closes (sigma / mean),
        computed in a single pass over the window (population variance via
        E[x^2] - E[x]^2 instead of a mean pass followed by a pstdev pass).
        """
        closes = self.recent_closes
        n = len(closes)
        if n < 2:
            return 0.0
        s = 0.0
        s2 = 0.0
        for x in closes:
            s += x
            s2 += x * x
        mean = s / n
        if mean <= 0.0:
            return 0.0
        variance = s2 / n - mean * mean
        if variance <= 0.0:      # Numerical guard: clamp catastrophic
            return 0.0           # cancellation residue to zero.
        return math.sqrt(variance) / mean

    # -- macro events ------------------------------------------------------- #
    def pay_dividends(self) -> None:
        """
        Solvency-constrained dividend: the per-share payout is capped so the
        total distribution never pushes the corporate balance below the
        $50k floor -- no money printing.
        """
        shares_out = self.total_shares_outstanding()
        if shares_out <= 0:
            return

        distributable = max(0.0, self.asset.balance - CORPORATE_BALANCE_FLOOR)
        per_share = min(BASE_DIVIDEND_PER_SHARE, distributable / shares_out)
        if per_share <= 0.0:
            return

        total_paid = 0.0
        for participant in self.macro_participants():
            payout = participant.total_shares * per_share
            participant.cash += payout
            total_paid += payout
        self.asset.balance -= total_paid  # guaranteed >= floor by construction
        self.total_dividends_paid += total_paid

    def accrue_interest(self) -> None:
        """Risk-free daily interest on available cash for every holder."""
        daily = self.rf_rate / 365.0
        accrued = 0.0
        for participant in self.macro_participants():
            delta = participant.cash * daily
            participant.cash += delta
            accrued += delta
        self.total_interest_paid += accrued

    # -- fluid friction and LOB decay (Part D) ------------------------------- #
    def update_friction(self) -> None:
        """
        Scales commission and Tobin tax with the current volume regime:
        activity = short-run average volume / long-run EMA baseline. In
        quiet markets the friction relaxes toward its floor so transaction
        costs can no longer paralyse non-speculative flow; in active
        markets it returns to the full statutory level.
        """
        volumes = self.recent_volumes
        short_run = (sum(volumes) / len(volumes)) if volumes else 0.0
        baseline = self.volume_baseline.value
        if baseline is None or baseline <= 1e-9:
            activity = 0.0
        else:
            activity = min(short_run / baseline, 1.0)

        commission = MIN_COMMISSION_RATE + COMMISSION_RATE_SPAN * activity
        tobin = MIN_TOBIN_RATE + TOBIN_RATE_SPAN * activity
        self.order_book.set_friction(commission, tobin)

    def decay_resting_orders(self, day: int) -> None:
        """
        Part D, fix 2: probabilistic order evaporation. Each non-MM resting
        order is cancelled with a hazard that rises with age:

            h(age) = min(MAX, BASE * (1 + age / AGE_SCALE))

        Expected lifetimes are a few days with a smooth tail, so stale
        price walls dissolve organically instead of persisting for a full
        TTL and vanishing all at once. (The MM refreshes its own quotes
        daily and is exempt.) Cancellation refunds escrow as always.
        """
        mm_id = self.market_maker.trader_id
        cancel = self.order_book.cancel_order
        for order in list(self.order_book.orders.values()):
            if order.trader_id == mm_id:
                continue
            age = day - order.timestamp
            hazard = min(ORDER_DECAY_MAX_HAZARD,
                         ORDER_DECAY_BASE_HAZARD
                         * (1.0 + age / ORDER_DECAY_AGE_SCALE))
            if random.random() < hazard:
                cancel(order.order_id, self.trader_map)

    # -- evolutionary review (Part A: logit choice, memory, switch cap) ------ #
    def evolutionary_review(self, day: int, closing_price: float) -> int:
        """
        Discrete-choice strategy evolution, every EVOLUTION_EPOCH_DAYS:

          1. Fitness: each strategy's epoch return (average wealth now vs
             at the previous review) is folded into an exponentially
             smoothed attractiveness score (STRATEGY_MEMORY inertia), so a
             single lucky epoch cannot flip the population.
          2. Choice: migration targets are sampled from a softmax (logit /
             Gibbs) over the smoothed scores with intensity-of-choice
             INTENSITY_OF_CHOICE -- probabilistic, not winner-take-all.
          3. Inertia: only ~SWITCH_CONSIDERATION_RATE of traders re-evaluate
             at all this epoch.
          4. Cap: at most MAX_SWITCH_FRACTION of the whole population may
             actually change strategy, structurally bounding herd shocks.

        The per-trader wealth computed here is cached in
        `_epoch_wealth_cache` so same-day logging can reuse it instead of
        re-marking the whole population to market.

        Returns the number of traders that switched.
        """
        wealth_cache: dict[str, float] = {}
        wealth_sum = {s: 0.0 for s in self.STRATEGIES}
        wealth_n = {s: 0 for s in self.STRATEGIES}
        for trader in self.traders:
            w = self._trader_wealth(trader, closing_price)
            wealth_cache[trader.trader_id] = w
            wealth_sum[trader.type] += w
            wealth_n[trader.type] += 1
        self._epoch_wealth_cache = wealth_cache
        avg_wealth = {
            s: (wealth_sum[s] / wealth_n[s] if wealth_n[s] else 0.0)
            for s in self.STRATEGIES
        }

        # 1. Epoch performance -> smoothed attractiveness (memory/inertia).
        for s in self.STRATEGIES:
            prev = self._epoch_wealth_marker[s]
            cur = avg_wealth[s]
            if prev is not None and prev > 0.0 and cur > 0.0:
                epoch_return = cur / prev - 1.0
            else:
                epoch_return = 0.0   # No comparable history: neutral fitness.
            self.strategy_attractiveness[s] = (
                STRATEGY_MEMORY * self.strategy_attractiveness[s]
                + LAMBDA_MEMORY * epoch_return)
            if cur > 0.0:
                self._epoch_wealth_marker[s] = cur

        # 2. Logit choice probabilities (max-shifted softmax for stability).
        scores = [INTENSITY_OF_CHOICE * self.strategy_attractiveness[s]
                  for s in self.STRATEGIES]
        peak = max(scores)
        exp_scores = [math.exp(x - peak) for x in scores]
        norm = sum(exp_scores)
        probs = [x / norm for x in exp_scores]

        # 3 + 4. Inertia-filtered candidates, hard-capped migration budget.
        budget = max(1, int(MAX_SWITCH_FRACTION * len(self.traders)))
        candidates = [t for t in self.traders
                      if random.random() < SWITCH_CONSIDERATION_RATE]
        random.shuffle(candidates)

        switched = 0
        for trader in candidates:
            if switched >= budget:
                break
            new_type = random.choices(self.STRATEGIES, weights=probs, k=1)[0]
            if new_type != trader.type:
                trader.switch_strategy(new_type, day, self.order_book,
                                       self.trader_map)
                switched += 1
        return switched

    def handle_bankruptcies(self, day: int) -> None:
        """Removes broke traders and reseeds the population by type."""
        # A trader holding P2P receivables is not broke: the claim is an
        # asset (cash_lent is exactly 0.0 with the credit layer off, so
        # the baseline condition is unchanged).
        bankrupt = [t for t in self.traders
                    if t.total_cash < 1e-5
                    and self._holder_total_shares(t) == 0
                    and t.cash_lent < 1e-5]
        for bt in bankrupt:
            if bt.positions is not None:
                # Multi-asset: sweep every venue's view out of the books.
                for venue in self.venues:
                    position = bt.positions[venue.symbol]
                    for oid in list(position.active_orders):
                        venue.order_book.cancel_order(oid, venue.trader_map)
                    venue.shares_outstanding -= position.total_shares
                    del venue.trader_map[bt.trader_id]
            else:
                for oid in list(bt.active_orders):
                    self.order_book.cancel_order(oid, self.trader_map)
                self._shares_outstanding -= bt.total_shares
            self.traders.remove(bt)
            del self.trader_map[bt.trader_id]
            if self.credit_market is not None:
                # Close every line touching the removed trader (residual
                # debt defaults; receivables die with the holder). In
                # multi-asset mode the credit layer knows the trader by
                # their primary-venue view.
                doomed = (bt.positions[self.venues[0].symbol]
                          if bt.positions is not None else bt)
                self.credit_market.on_trader_removed(doomed, self.trader_map)
            self.total_bankrupt_cash_removed += bt.total_cash
            self.create_and_add_trader(bt.type, current_day=day)
            self.total_reseed_cash += self.initial_cash
            reseeded = self.initial_shares * (len(self.venues)
                                              if self.venues else 1)
            self.total_reseed_shares += reseeded

    # -- Part F: per-venue regime helpers and ESG macro hooks ----------------- #
    @staticmethod
    def _venue_volatility(venue: MarketVenue) -> float:
        """Single-pass relative realised volatility of a venue's closes."""
        closes = venue.recent_closes
        n = len(closes)
        if n < 2:
            return 0.0
        s = 0.0
        s2 = 0.0
        for x in closes:
            s += x
            s2 += x * x
        mean = s / n
        if mean <= 0.0:
            return 0.0
        variance = s2 / n - mean * mean
        if variance <= 0.0:
            return 0.0
        return math.sqrt(variance) / mean

    @staticmethod
    def _venue_update_friction(venue: MarketVenue) -> None:
        """Volume-regime friction, per venue (same law as single-asset)."""
        volumes = venue.recent_volumes
        short_run = (sum(volumes) / len(volumes)) if volumes else 0.0
        baseline = venue.volume_baseline.value
        if baseline is None or baseline <= 1e-9:
            activity = 0.0
        else:
            activity = min(short_run / baseline, 1.0)
        venue.order_book.set_friction(
            MIN_COMMISSION_RATE + COMMISSION_RATE_SPAN * activity,
            MIN_TOBIN_RATE + TOBIN_RATE_SPAN * activity)

    def _venue_decay_orders(self, venue: MarketVenue, day: int) -> None:
        """Probabilistic order evaporation, per venue (MM exempt)."""
        mm_id = venue.market_maker.trader_id
        cancel = venue.order_book.cancel_order
        for order in list(venue.order_book.orders.values()):
            if order.trader_id == mm_id:
                continue
            age = day - order.timestamp
            hazard = min(ORDER_DECAY_MAX_HAZARD,
                         ORDER_DECAY_BASE_HAZARD
                         * (1.0 + age / ORDER_DECAY_AGE_SCALE))
            if random.random() < hazard:
                cancel(order.order_id, venue.trader_map)

    def _pay_dividends_multi(self) -> None:
        """
        Solvency-constrained dividends, per listing. The State forgoes
        dividends on sovereign-fund holdings (its treasury canon stays an
        exact mirror of the ledger wallet), which can only leave the
        corporate balance above the guaranteed floor.
        """
        for venue in self.venues:
            shares_out = venue.shares_outstanding
            if shares_out <= 0:
                continue
            distributable = max(0.0,
                                venue.asset.balance - CORPORATE_BALANCE_FLOOR)
            per_share = min(BASE_DIVIDEND_PER_SHARE,
                            distributable / shares_out)
            if per_share <= 0.0:
                continue
            total_paid = 0.0
            for holder in venue.trader_map.values():
                if holder.trader_id == STATE_ID:
                    continue
                payout = holder.total_shares * per_share
                holder.cash += payout
                total_paid += payout
            venue.asset.balance -= total_paid
            self.total_dividends_paid += total_paid

    def _corporate_transitions(self, day: int) -> None:
        """
        Part F, spec 2: endogenous corporate green transition. Any listing
        below a perfect score executes a CAPEX step whenever the balance
        sheet can absorb the cent-quantized cost while staying a safety
        multiple above the corporate solvency floor.
        """
        for venue in self.venues:
            asset = venue.asset
            if asset.green_score >= 1.0:
                continue
            if asset.balance - GREEN_TRANSITION_COST \
                    >= CORPORATE_BALANCE_FLOOR * GREEN_TRANSITION_SAFETY:
                asset.apply_green_transition(GREEN_TRANSITION_STEP,
                                             GREEN_TRANSITION_COST, day)
                self.green_transitions += 1

    def _update_policy_rate(self, total_volume: float) -> None:
        """
        Part F, spec 5: daily Taylor-rule inputs. The price gap is the
        economy-wide mean short-run price growth -- the fast EMA against
        the slow EMA, averaged across venues; the output gap is total
        traded volume against its long-run EMA baseline.
        """
        gap_sum = 0.0
        for venue in self.venues:
            fast, slow = venue.ema_fast.value, venue.ema_slow.value
            if fast and slow and slow > 0.0:
                gap_sum += fast / slow - 1.0
        price_gap = gap_sum / len(self.venues)

        baseline = self._taylor_volume_baseline.value
        if baseline is None or baseline <= 1e-9:
            output_gap = 0.0
        else:
            output_gap = max(-1.0, min(1.0, total_volume / baseline - 1.0))
        self._taylor_volume_baseline.update(total_volume)
        self.central_bank.update_policy_rate(price_gap, output_gap)

    # -- logging ------------------------------------------------------------ #
    def log_daily_metrics(self, current_price: float,
                          wealth_cache: Optional[dict] = None) -> None:
        """
        Appends the daily demographic and wealth series. When a
        `wealth_cache` (trader_id -> wealth, e.g. from the same-day
        evolutionary review) is supplied, the mark-to-market pass is
        skipped and the cached values are regrouped by *current* strategy.
        """
        counts = {s: 0 for s in self.STRATEGIES}
        sums = {s: 0.0 for s in self.STRATEGIES}
        if wealth_cache is None:
            for trader in self.traders:
                counts[trader.type] += 1
                sums[trader.type] += self._trader_wealth(trader,
                                                         current_price)
        else:
            for trader in self.traders:
                counts[trader.type] += 1
                w = wealth_cache.get(trader.trader_id)
                if w is None:
                    w = self._trader_wealth(trader, current_price)
                sums[trader.type] += w
        for s in self.STRATEGIES:
            n = counts[s]
            self.log_demographics[s].append(n)
            self.log_avg_wealth[s].append(sums[s] / n if n else 0.0)

        self.log_mm_wealth.append(self.market_maker.get_wealth(current_price))
        if self.manipulators:
            self.log_manip_wealth.append(
                sum(self._trader_wealth(m, current_price)
                    for m in self.manipulators) / len(self.manipulators))
        else:
            self.log_manip_wealth.append(0.0)

        credit = self.credit_market
        if credit is not None:
            self.log_credit_outstanding.append(credit.outstanding_debt())
            self.log_credit_rate.append(credit.annual_rate)
            self.log_liquidations.append(credit.liquidation_count)
        else:
            self.log_credit_outstanding.append(0.0)
            self.log_credit_rate.append(0.0)
            self.log_liquidations.append(0)
        self.log_policy_rate.append(
            self.central_bank.policy_rate
            if self.central_bank is not None else 0.0)

    # -- main loop ---------------------------------------------------------- #
    def run(self) -> None:
        if self.venues is not None:
            self._run_multi_asset()
            return
        print(f"Starting Financial Market Simulation for {self.days} days...")

        for day in range(1, self.days + 1):
            last_price = self.asset.get_last_price()

            # Weekends: interest accrues, no trading.
            if self.is_weekend(day):
                self.accrue_interest()
                self.asset.record_close(last_price)
                self.log_price.append(last_price)
                self.log_balance.append(self.asset.balance)
                self.log_daily_metrics(last_price)
                continue

            # 1. Organic information arrival: OU step of the fundamental
            #    (Part B), then quarterly solvency-constrained dividends.
            self.asset.update_daily_fundamental()
            if day % EVOLUTION_EPOCH_DAYS == 0:
                self.pay_dividends()

            # 2. Fluid friction for today's volume regime (Part D, fix 1)
            #    and probabilistic evaporation of stale orders (fix 2).
            self.update_friction()
            self.decay_resting_orders(day)

            # 3. Market maker re-quotes: tanh-skewed reservation price,
            #    asymmetric volatility-scaled spread (Part C).
            rel_vol = self.current_volatility()
            mid = self.order_book.get_midpoint(last_price)
            self.market_maker.place_quotes(
                mid, rel_vol, self.order_book, self.trader_map, day)
            # Part C, fix 3: daily thin-book check -- if overnight decay or
            # cancellations left near-mid depth hollow, backstop it before
            # any taker can gap the price through a void.
            self.market_maker.provide_structural_depth(
                mid, self.order_book, self.trader_map, day)

            # 4. Manipulators read the book and act.
            credit = self.credit_market
            for manip in self.manipulators:
                manip.act(self.order_book.get_midpoint(last_price),
                          self.order_book, self.trader_map, day)
            if credit is not None:
                # Part E: margin sweep iff the manipulators moved the mark.
                credit.poll_intraday(self.trader_map, day)

            # 5. Evolutionary traders act in randomised order. The
            #    fundamental value is a loop invariant (the corporate
            #    balance and shares outstanding cannot change intraday),
            #    so it is computed once per day, not once per trader.
            ema_ready = self.ema_slow.count >= 15
            ef, es = self.ema_fast.value, self.ema_slow.value
            v_fund = self.get_fundamental_value()

            active_traders = list(self.traders)
            random.shuffle(active_traders)
            day_trades = []

            for trader in active_traders:
                ref_price = self.order_book.get_midpoint(last_price)
                imbalance = self.order_book.get_imbalance(ref_price)

                decision = trader.decide_order(
                    ref_price, v_fund, ef, es, ema_ready, imbalance, rel_vol)
                if decision is None:
                    continue

                order_type, side, price, quantity = decision
                if order_type == 'LIMIT':
                    if side == 'BUY':
                        cost = price * quantity \
                            * (1.0 + self.order_book.commission_rate)
                        if trader.cash >= cost:
                            oid = self.order_book.get_next_order_id()
                            day_trades.extend(self.order_book.add_limit_order(
                                LimitOrder(oid, trader.trader_id, side, price,
                                           quantity, day),
                                self.trader_map, day))
                    elif trader.shares >= quantity:
                        oid = self.order_book.get_next_order_id()
                        day_trades.extend(self.order_book.add_limit_order(
                            LimitOrder(oid, trader.trader_id, side, price,
                                       quantity, day),
                            self.trader_map, day))
                else:  # MARKET
                    if side == 'BUY':
                        day_trades.extend(self.order_book.execute_market_order(
                            MarketOrder(trader.trader_id, side, quantity),
                            self.trader_map, day))
                    elif trader.shares > 0:
                        qty = min(quantity, trader.shares)
                        day_trades.extend(self.order_book.execute_market_order(
                            MarketOrder(trader.trader_id, side, qty),
                            self.trader_map, day))

                if credit is not None:
                    # Part E: endogenous margin calls -- the clearing house
                    # re-checks leveraged positions after every mark move
                    # (O(1) no-op when this trader's action left the book
                    # untouched).
                    credit.poll_intraday(self.trader_map, day)

            # 6. Daily interest.
            self.accrue_interest()

            # 7. Closing price: VWAP of the day's executions (a single deep
            #    sweep through a thin level can no longer print the close),
            #    persisted to the asset history. One pass computes traded
            #    value and volume together (volume feeds step 8).
            traded_value = 0.0
            traded_qty = 0
            for _, p, q in day_trades:
                traded_value += p * q
                traded_qty += q
            if traded_qty > 0:
                closing_price = traded_value / traded_qty
            else:
                closing_price = last_price
            self.asset.record_close(closing_price)
            self.log_price.append(closing_price)
            self.log_balance.append(self.asset.balance)

            # 8. Update shared EMAs, volatility window, and volume regime.
            self.ema_fast.update(closing_price)
            self.ema_slow.update(closing_price)
            self.recent_closes.append(closing_price)
            day_volume = float(traded_qty)
            self.recent_volumes.append(day_volume)
            self.volume_baseline.update(day_volume)

            # 8.5 Part E: daily credit cycle -- endogenous rate discovery,
            #     compounding interest accrual and cash servicing, margin
            #     enforcement at the closing mark, P2P vault refresh, and
            #     new originations. Runs before bankruptcies so defaulted
            #     borrowers flow into the reseeding pass below.
            if credit is not None:
                credit.daily_cycle(day, closing_price, rel_vol,
                                   self.strategy_attractiveness,
                                   self.trader_map, self.traders,
                                   self.market_maker)

            # 9. Bankruptcies and (capped, logit-driven) evolution.
            self.handle_bankruptcies(day)
            epoch_wealth_cache = None
            if day % EVOLUTION_EPOCH_DAYS == 0:
                switched = self.evolutionary_review(day, closing_price)
                epoch_wealth_cache = self._epoch_wealth_cache
                if switched > 0:
                    # Part C, fix 3: the review mass-cancelled the switchers'
                    # resting orders -- backstop any resulting thin spots so
                    # the next market order cannot gap through a void.
                    self.market_maker.provide_structural_depth(
                        self.order_book.get_midpoint(closing_price),
                        self.order_book, self.trader_map, day)

            # 10. Log (reusing the review's wealth pass on epoch days).
            self.log_daily_metrics(closing_price, epoch_wealth_cache)

        print("Simulation complete.")

    def _run_multi_asset(self) -> None:
        """
        Part F daily cycle over every listed venue. Mirrors the legacy
        loop step-for-step, adding: corporate green transitions and state
        subsidies on epoch days, the sovereign green fund's daily market
        buys, greenwashing manipulator FSMs, and the Taylor-rule policy
        update feeding the credit market's borrowing base.
        """
        venues = self.venues
        primary = venues[0]
        credit = self.credit_market
        print(f"Starting ESG Multi-Asset Simulation: {len(venues)} assets, "
              f"{self.days} days...")

        for day in range(1, self.days + 1):
            last_price = {v.symbol: v.asset.get_last_price() for v in venues}

            # Weekends: interest accrues, no trading.
            if self.is_weekend(day):
                self.accrue_interest()
                for venue in venues:
                    close = last_price[venue.symbol]
                    venue.asset.record_close(close)
                    venue.log_price.append(close)
                    venue.log_balance.append(venue.asset.balance)
                    venue.log_green_score.append(venue.asset.green_score)  # Record weekend score
                self.log_price.append(last_price[primary.symbol])
                self.log_balance.append(primary.asset.balance)
                self.log_daily_metrics(last_price[primary.symbol])
                continue

            # 1. OU information arrival per listing; on epoch days the
            #    corporates decide green transitions (CAPEX first), then
            #    dividends are paid and the State disburses subsidies.
            for venue in venues:
                venue.asset.update_daily_fundamental()
            if day % EVOLUTION_EPOCH_DAYS == 0:
                self._corporate_transitions(day)
                self._pay_dividends_multi()
                self.total_subsidies_paid += self.state.pay_subsidies(
                    venues, day)

            # 2. Fluid friction and probabilistic order decay, per venue.
            rel_vol = {}
            for venue in venues:
                self._venue_update_friction(venue)
                self._venue_decay_orders(venue, day)
                rel_vol[venue.symbol] = self._venue_volatility(venue)

            # 3. Market makers re-quote their own listings.
            for venue in venues:
                mid = venue.order_book.get_midpoint(last_price[venue.symbol])
                venue.market_maker.place_quotes(
                    mid, rel_vol[venue.symbol], venue.order_book,
                    venue.trader_map, day)
                venue.market_maker.provide_structural_depth(
                    mid, venue.order_book, venue.trader_map, day)

            # 4. The sovereign green fund crosses the spread on qualifying
            #    listings, then the greenwashing manipulators pick their
            #    narrative targets.
            self.state.invest_green(venues, day)
            for manip in self.manipulators:
                manip.act_green(venues, day)
            if credit is not None:
                credit.poll_intraday(primary.trader_map, day)

            # 5. Evolutionary traders sweep every listing in randomised
            #    order; per-venue fundamentals are loop invariants.
            venue_ctx = []
            for venue in venues:
                venue_ctx.append((
                    venue,
                    self._venue_fundamental(venue),
                    venue.ema_fast.value, venue.ema_slow.value,
                    venue.ema_slow.count >= 15,
                    rel_vol[venue.symbol],
                    venue.asset.green_score,
                ))
            active_traders = list(self.traders)
            random.shuffle(active_traders)
            day_trades = {venue.symbol: [] for venue in venues}

            for trader in active_traders:
                for (venue, v_fund, ef, es, ema_ready,
                        vol, green) in venue_ctx:
                    book = venue.order_book
                    position = trader.positions[venue.symbol]
                    ref_price = book.get_midpoint(last_price[venue.symbol])
                    imbalance = book.get_imbalance(ref_price)

                    decision = trader.decide_order(
                        ref_price, v_fund, ef, es, ema_ready, imbalance,
                        vol, green)
                    if decision is None:
                        continue

                    order_type, side, price, quantity = decision
                    trades = day_trades[venue.symbol]
                    if order_type == 'LIMIT':
                        if side == 'BUY':
                            cost = price * quantity \
                                * (1.0 + book.commission_rate)
                            if trader.cash >= cost:
                                oid = book.get_next_order_id()
                                trades.extend(book.add_limit_order(
                                    LimitOrder(oid, trader.trader_id, side,
                                               price, quantity, day),
                                    venue.trader_map, day))
                        elif position.shares >= quantity:
                            oid = book.get_next_order_id()
                            trades.extend(book.add_limit_order(
                                LimitOrder(oid, trader.trader_id, side,
                                           price, quantity, day),
                                venue.trader_map, day))
                    else:  # MARKET
                        if side == 'BUY':
                            trades.extend(book.execute_market_order(
                                MarketOrder(trader.trader_id, side, quantity),
                                venue.trader_map, day))
                        elif position.shares > 0:
                            qty = min(quantity, position.shares)
                            trades.extend(book.execute_market_order(
                                MarketOrder(trader.trader_id, side, qty),
                                venue.trader_map, day))

                if credit is not None:
                    credit.poll_intraday(primary.trader_map, day)

            # 6. Daily interest on every wallet.
            self.accrue_interest()

            # 7 + 8. Per-venue VWAP closes, histories, and regime updates.
            total_volume = 0.0
            for venue in venues:
                traded_value = 0.0
                traded_qty = 0
                for _, p, q in day_trades[venue.symbol]:
                    traded_value += p * q
                    traded_qty += q
                if traded_qty > 0:
                    closing = traded_value / traded_qty
                else:
                    closing = last_price[venue.symbol]
                venue.asset.record_close(closing)
                venue.log_price.append(closing)
                venue.log_balance.append(venue.asset.balance)
                venue.log_green_score.append(venue.asset.green_score)  # Record trading day score
                venue.ema_fast.update(closing)
                venue.ema_slow.update(closing)
                venue.recent_closes.append(closing)
                volume = float(traded_qty)
                venue.recent_volumes.append(volume)
                venue.volume_baseline.update(volume)
                total_volume += volume
            primary_close = primary.asset.get_last_price()
            self.log_price.append(primary_close)
            self.log_balance.append(primary.asset.balance)

            # 8.5 Monetary policy: Taylor rule with Gaussian surprise,
            #     then the daily credit cycle at the new borrowing base.
            if self.central_bank is not None:
                self._update_policy_rate(total_volume)
            if credit is not None:
                credit.daily_cycle(
                    day, primary_close, rel_vol[primary.symbol],
                    self.strategy_attractiveness, primary.trader_map,
                    [t.positions[primary.symbol] for t in self.traders],
                    primary.market_maker)

            # 9. Bankruptcies and (capped, logit-driven) evolution.
            self.handle_bankruptcies(day)
            epoch_wealth_cache = None
            if day % EVOLUTION_EPOCH_DAYS == 0:
                switched = self.evolutionary_review(day, primary_close)
                epoch_wealth_cache = self._epoch_wealth_cache
                if switched > 0:
                    for venue in venues:
                        venue.market_maker.provide_structural_depth(
                            venue.order_book.get_midpoint(
                                venue.asset.get_last_price()),
                            venue.order_book, venue.trader_map, day)

            # 10. Log (legacy series follow the primary listing).
            self.log_daily_metrics(primary_close, epoch_wealth_cache)

        print("Simulation complete.")

    # -- plotting ----------------------------------------------------------- #
    def plot_dashboard(self, output_path: str = "market_simulation_dashboard.png"):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plt.style.use('default')
        fig, axes = plt.subplots(5, 1, figsize=(12, 26))
        ax1, ax2, ax3, ax4, ax5 = axes
        days_range = list(range(self.days + 1))
        active_days = list(range(1, self.days + 1))
        colors = {'noise': '#d62728', 'fundamentalist': '#2ca02c',
                  'chartist': '#9467bd', 'mm': '#1f77b4', 'manip': '#8c564b'}

        # Subplot 1: Prezzo di tutti i 10 Asset
        if self.venues is not None:
            for venue in self.venues:
                alpha_val = 0.8
                ax1.plot(range(self.days + 1), venue.log_price, label=venue.symbol, alpha=alpha_val, linewidth=1.2)
            ax1.set_title('Multi-Asset Closing Prices Across the ESG Spectrum', fontsize=13, fontweight='bold', pad=15)
            ax1.legend(loc='upper left', ncol=5, frameon=True, fontsize=9)
        else:
            ax1.plot(days_range, self.log_price, color='#1f77b4', linewidth=1.6, label='Asset Price ($)')
            ax1.set_title('Asset Closing Price History', fontsize=13, fontweight='bold', pad=15)
        ax1.set_ylabel('Market Price ($)', fontsize=11, fontweight='bold')
        ax1.grid(True, linestyle=':', alpha=0.6)

        # Subplot 2: Real Historical Evolution of Green Scores
        if self.venues is not None:
            for venue in self.venues:
                ax2.plot(days_range, venue.log_green_score, label=f'{venue.symbol}', alpha=0.7, linewidth=1.2)
            ax2.set_title('Corporate Sustainability Evolution (Green Transition Trajectories)', fontsize=13, fontweight='bold', pad=15)
            ax2.set_ylabel('Green Score', fontsize=11, fontweight='bold')
            ax2.set_ylim(-0.05, 1.05)
            ax2.grid(True, linestyle=':', alpha=0.6)
            ax2.legend(loc='upper left', ncol=5, frameon=True, fontsize=9)
        else:
            ax2.plot(days_range, self.log_balance, color='#ff7f0e', linewidth=2, label='Corporate Balance ($)')
            ax2.set_title('Corporate Balance History', fontsize=13, fontweight='bold', pad=15)

        # Subplot 3: Ricchezza delle strategie
        for s in self.STRATEGIES:
            ax3.plot(active_days, self.log_avg_wealth[s], color=colors[s], linewidth=1.8, label=f'{s.capitalize()} Wealth')
        ax3.set_title('Time-Series Evolution of Average Strategy Wealth', fontsize=13, fontweight='bold', pad=15)
        ax3.set_ylabel('Average Trader Wealth ($)', fontsize=11, fontweight='bold')
        ax3.grid(True, linestyle=':', alpha=0.6)
        ax3.legend(loc='upper left', frameon=True)

        # Subplot 4: Tassi Centrale e di Mercato
        ax4.plot(active_days, self.log_policy_rate, color='#e377c2', linewidth=1.8, label='Taylor Policy Rate (Central Bank)')
        if self.credit_market is not None:
            ax4.plot(active_days, self.log_credit_rate, color='#7f7f7f', linestyle='--', linewidth=1.4, label='Commercial Borrowing Rate')
        ax4.set_title('Monetary Policy and Credit Market Interest Rates', fontsize=13, fontweight='bold', pad=15)
        ax4.set_ylabel('Annual Interest Rate', fontsize=11, fontweight='bold')
        ax4.grid(True, linestyle=':', alpha=0.6)
        ax4.legend(loc='upper left', frameon=True)

        # Subplot 5: Demografia
        for s in self.STRATEGIES:
            ax5.plot(active_days, self.log_demographics[s], color=colors[s], linewidth=1.8, label=f'{s.capitalize()} Count')
        ax5.set_title('Trader Population Demographics Over Time', fontsize=13, fontweight='bold', pad=15)
        ax5.set_xlabel('Calendar Days', fontsize=11, fontweight='bold')
        ax5.set_ylabel('Number of Active Agents', fontsize=11, fontweight='bold')
        ax5.grid(True, linestyle=':', alpha=0.6)
        ax5.legend(loc='upper left', frameon=True)

        plt.tight_layout()
        plt.savefig(output_path, dpi=300)
        print(f"Comprehensive ESG Dashboard figure saved safely as '{output_path}'.")
        plt.close(fig)


def export_simulation_metrics(sim: Simulation,
                              csv_path: str = "simulation_results.csv") -> None:
    """Exports daily metrics to CSV."""
    with open(csv_path, mode='w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'day', 'asset_price', 'corporate_balance',
            'noise_count', 'fundamentalist_count', 'chartist_count',
            'noise_wealth', 'fundamentalist_wealth', 'chartist_wealth',
            'market_maker_wealth', 'manipulator_wealth',
        ])
        for d in range(sim.days + 1):
            if d == 0:
                writer.writerow([0, sim.log_price[0], sim.log_balance[0],
                                 "", "", "", "", "", "", "", ""])
            else:
                i = d - 1
                writer.writerow([
                    d, sim.log_price[d], sim.log_balance[d],
                    sim.log_demographics['noise'][i],
                    sim.log_demographics['fundamentalist'][i],
                    sim.log_demographics['chartist'][i],
                    sim.log_avg_wealth['noise'][i],
                    sim.log_avg_wealth['fundamentalist'][i],
                    sim.log_avg_wealth['chartist'][i],
                    sim.log_mm_wealth[i],
                    sim.log_manip_wealth[i],
                ])
    print(f"Simulation metrics exported to '{csv_path}'.")
