"""
Macro-orchestrator of the agent-based financial market simulation.

`Simulation` wires the full daily cycle: OU fundamental updates (Part B),
volume-regime friction and probabilistic LOB decay (Part D), adaptive MM
quoting and backstop depth (Part C), manipulator activity, randomized
trader participation, solvency-constrained dividends, interest accrual,
bankruptcy reseeding, and the capped logit-driven evolutionary review
(Part A). `export_simulation_metrics` provides the CSV export pipeline.

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
import statistics
from typing import Optional

from market_sim.constants import (
    BASE_COMMISSION_RATE,
    BASE_DIVIDEND_PER_SHARE,
    CORPORATE_BALANCE_FLOOR,
    EVOLUTION_EPOCH_DAYS,
    INTENSITY_OF_CHOICE,
    MAX_SWITCH_FRACTION,
    MIN_COMMISSION_RATE,
    MIN_TOBIN_RATE,
    ORDER_DECAY_AGE_SCALE,
    ORDER_DECAY_BASE_HAZARD,
    ORDER_DECAY_MAX_HAZARD,
    STRATEGY_MEMORY,
    SWITCH_CONSIDERATION_RATE,
    TOBIN_TAX_RATE,
)
from market_sim.models import Asset, IncrementalEMA, LimitOrder, MarketOrder
from market_sim.order_book import OrderBook
from market_sim.traders import Manipulator, MarketMaker, Trader


class Simulation:
    """Main executor of the agent-based financial market simulation."""

    STRATEGIES = ('noise', 'fundamentalist', 'chartist')

    def __init__(self, num_traders: int = 60, initial_cash: float = 10_000.0,
                 initial_shares: int = 50, initial_price: float = 100.0,
                 rf_rate: float = 0.02, days: int = 1000,
                 num_manipulators: int = 2):
        self.days = days
        self.rf_rate = rf_rate
        self.initial_cash = initial_cash
        self.initial_shares = initial_shares
        self.initial_price = initial_price

        self.traders: list[Trader] = []          # Evolutionary population only
        self.trader_map: dict[str, Trader] = {}  # ALL participants (incl. MM)
        self.next_trader_id_counter = 0

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

        # Manipulators -- also full macro participants.
        self.manipulators: list[Manipulator] = []
        for i in range(num_manipulators):
            manip = Manipulator(
                trader_id=f"T_MANIP_{i + 1}", cash=500_000.0, shares=2_000,
                spoof_size=400, attack_size=40)
            self.manipulators.append(manip)
            self.trader_map[manip.trader_id] = manip

        # Asset and book. Part B, fix 3: the corporate balance is seeded
        # from the TRUE float (all holders, incl. MM and Manipulators) so
        # fundamental value == initial price at t=0 instead of starting the
        # market structurally ~58% overvalued.
        initial_balance = self.total_shares_outstanding() * initial_price
        self.asset = Asset("XYZ", initial_price, initial_balance)
        self.order_book = OrderBook()

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

        # Logging. All strategy series (incl. the two specialist agents).
        self.log_price = [initial_price]
        self.log_balance = [initial_balance]
        self.log_demographics = {s: [] for s in self.STRATEGIES}
        self.log_avg_wealth = {s: [] for s in self.STRATEGIES}
        self.log_mm_wealth: list[float] = []
        self.log_manip_wealth: list[float] = []

    # -- participant helpers ------------------------------------------------ #
    def macro_participants(self):
        """Every entity that receives dividends and interest."""
        yield from self.traders
        yield self.market_maker
        yield from self.manipulators

    def total_shares_outstanding(self) -> int:
        """True float across ALL holders, computed live."""
        return sum(p.total_shares for p in self.macro_participants())

    def create_and_add_trader(self, trader_type: str,
                              current_day: int = 0) -> Trader:
        self.next_trader_id_counter += 1
        t_id = f"T_{trader_type[0].upper()}_{self.next_trader_id_counter}"
        trader = Trader(t_id, self.initial_cash, self.initial_shares,
                        trader_type, current_day=current_day)
        self.traders.append(trader)
        self.trader_map[t_id] = trader
        return trader

    def get_fundamental_value(self) -> float:
        """Intrinsic value = corporate balance / live shares outstanding."""
        shares = self.total_shares_outstanding()
        if shares <= 0:
            return self.asset.get_last_price()
        return self.asset.balance / shares

    def is_weekend(self, day: int) -> bool:
        return (day % 7) == 6 or (day % 7) == 0

    def current_volatility(self) -> float:
        """Relative realised volatility of recent closes (sigma / mean)."""
        if len(self.recent_closes) < 2:
            return 0.0
        mean = statistics.fmean(self.recent_closes)
        if mean <= 0.0:
            return 0.0
        return statistics.pstdev(self.recent_closes) / mean

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

    def accrue_interest(self) -> None:
        """Risk-free daily interest on available cash for every holder."""
        daily = self.rf_rate / 365.0
        for participant in self.macro_participants():
            participant.cash += participant.cash * daily

    # -- fluid friction and LOB decay (Part D) ------------------------------- #
    def update_friction(self) -> None:
        """
        Scales commission and Tobin tax with the current volume regime:
        activity = short-run average volume / long-run EMA baseline. In
        quiet markets the friction relaxes toward its floor so transaction
        costs can no longer paralyse non-speculative flow; in active
        markets it returns to the full statutory level.
        """
        if self.recent_volumes:
            short_run = statistics.fmean(self.recent_volumes)
        else:
            short_run = 0.0
        baseline = self.volume_baseline.value
        if baseline is None or baseline <= 1e-9:
            activity = 0.0
        else:
            activity = min(short_run / baseline, 1.0)

        commission = MIN_COMMISSION_RATE \
            + (BASE_COMMISSION_RATE - MIN_COMMISSION_RATE) * activity
        tobin = MIN_TOBIN_RATE + (TOBIN_TAX_RATE - MIN_TOBIN_RATE) * activity
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
        for order in list(self.order_book.orders.values()):
            owner = self.trader_map.get(order.trader_id)
            if owner is self.market_maker:
                continue
            age = day - order.timestamp
            hazard = min(ORDER_DECAY_MAX_HAZARD,
                         ORDER_DECAY_BASE_HAZARD
                         * (1.0 + age / ORDER_DECAY_AGE_SCALE))
            if random.random() < hazard:
                self.order_book.cancel_order(order.order_id, self.trader_map)

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

        Returns the number of traders that switched.
        """
        wealth_by_type = {s: [] for s in self.STRATEGIES}
        for trader in self.traders:
            wealth_by_type[trader.type].append(trader.get_wealth(closing_price))
        avg_wealth = {
            s: (sum(v) / len(v) if v else 0.0)
            for s, v in wealth_by_type.items()
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
                + (1.0 - STRATEGY_MEMORY) * epoch_return)
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
        bankrupt = [t for t in self.traders
                    if t.total_cash < 1e-5 and t.total_shares == 0]
        for bt in bankrupt:
            for oid in list(bt.active_orders):
                self.order_book.cancel_order(oid, self.trader_map)
            self.traders.remove(bt)
            del self.trader_map[bt.trader_id]
            self.create_and_add_trader(bt.type, current_day=day)

    # -- logging ------------------------------------------------------------ #
    def log_daily_metrics(self, current_price: float) -> None:
        counts = {s: 0 for s in self.STRATEGIES}
        wealths = {s: [] for s in self.STRATEGIES}
        for trader in self.traders:
            counts[trader.type] += 1
            wealths[trader.type].append(trader.get_wealth(current_price))
        for s in self.STRATEGIES:
            self.log_demographics[s].append(counts[s])
            self.log_avg_wealth[s].append(
                sum(wealths[s]) / len(wealths[s]) if wealths[s] else 0.0)

        self.log_mm_wealth.append(self.market_maker.get_wealth(current_price))
        if self.manipulators:
            self.log_manip_wealth.append(
                sum(m.get_wealth(current_price) for m in self.manipulators)
                / len(self.manipulators))
        else:
            self.log_manip_wealth.append(0.0)

    # -- main loop ---------------------------------------------------------- #
    def run(self) -> None:
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
            for manip in self.manipulators:
                manip.act(self.order_book.get_midpoint(last_price),
                          self.order_book, self.trader_map, day)

            # 5. Evolutionary traders act in randomised order.
            ema_ready = self.ema_slow.count >= 15
            ef, es = self.ema_fast.value, self.ema_slow.value

            active_traders = list(self.traders)
            random.shuffle(active_traders)
            day_trades = []

            for trader in active_traders:
                ref_price = self.order_book.get_midpoint(last_price)
                v_fund = self.get_fundamental_value()
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

            # 6. Daily interest.
            self.accrue_interest()

            # 7. Closing price: VWAP of the day's executions (a single deep
            #    sweep through a thin level can no longer print the close),
            #    persisted to the asset history.
            if day_trades:
                traded_value = sum(p * q for _, p, q in day_trades)
                traded_qty = sum(q for _, _, q in day_trades)
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
            day_volume = float(sum(qty for _, _, qty in day_trades))
            self.recent_volumes.append(day_volume)
            self.volume_baseline.update(day_volume)

            # 9. Bankruptcies and (capped, logit-driven) evolution.
            self.handle_bankruptcies(day)
            if day % EVOLUTION_EPOCH_DAYS == 0:
                switched = self.evolutionary_review(day, closing_price)
                if switched > 0:
                    # Part C, fix 3: the review mass-cancelled the switchers'
                    # resting orders -- backstop any resulting thin spots so
                    # the next market order cannot gap through a void.
                    self.market_maker.provide_structural_depth(
                        self.order_book.get_midpoint(closing_price),
                        self.order_book, self.trader_map, day)

            # 10. Log.
            self.log_daily_metrics(closing_price)

        print("Simulation complete.")

    # -- plotting ----------------------------------------------------------- #
    def plot_dashboard(self,
                       output_path: str = "market_simulation_dashboard.png"):
        # Lazy import (side-effect isolation): backend selection happens
        # only when plotting is actually requested, never at package import.
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plt.style.use('default')
        fig, axes = plt.subplots(4, 1, figsize=(12, 21))
        ax1, ax2, ax3, ax4 = axes
        days_range = list(range(self.days + 1))
        active_days = list(range(1, self.days + 1))
        colors = {'noise': '#d62728', 'fundamentalist': '#2ca02c',
                  'chartist': '#9467bd', 'mm': '#1f77b4',
                  'manip': '#8c564b'}

        # Subplot 1: price vs corporate balance.
        c_price = '#1f77b4'
        ax1.plot(days_range, self.log_price, color=c_price, linewidth=1.6,
                 label='Asset Price ($)')
        ax1.set_xlabel('Calendar Days', fontsize=11, fontweight='bold')
        ax1.set_ylabel('Market Price ($)', color=c_price, fontsize=11,
                       fontweight='bold')
        ax1.tick_params(axis='y', labelcolor=c_price)
        ax1.grid(True, linestyle=':', alpha=0.6)
        ax1_t = ax1.twinx()
        c_bal = '#ff7f0e'
        ax1_t.plot(days_range, self.log_balance, color=c_bal, linewidth=2,
                   linestyle='--', label='Corporate Balance ($)')
        ax1_t.set_ylabel('Corporate Balance ($)', color=c_bal, fontsize=11,
                         fontweight='bold')
        ax1_t.tick_params(axis='y', labelcolor=c_bal)
        l1, lab1 = ax1.get_legend_handles_labels()
        l2, lab2 = ax1_t.get_legend_handles_labels()
        ax1.legend(l1 + l2, lab1 + lab2, loc='upper left', frameon=True,
                   facecolor='white', framealpha=0.9)
        ax1.set_title('Asset Closing Price & Corporate Balance Sheet History',
                      fontsize=13, fontweight='bold', pad=15)

        # Subplot 2: evolutionary strategy wealth.
        for s in self.STRATEGIES:
            ax2.plot(active_days, self.log_avg_wealth[s], color=colors[s],
                     linewidth=1.8, label=f'{s.capitalize()} Wealth')
        ax2.set_title('Time-Series Evolution of Average Strategy Wealth',
                      fontsize=13, fontweight='bold', pad=15)
        ax2.set_xlabel('Calendar Days', fontsize=11, fontweight='bold')
        ax2.set_ylabel('Average Trader Wealth ($)', fontsize=11,
                       fontweight='bold')
        ax2.grid(True, linestyle=':', alpha=0.6)
        ax2.legend(loc='upper left', frameon=True, facecolor='white',
                   framealpha=0.9)

        # Subplot 3: specialist agents' wealth (MM + Manipulators).
        ax3.plot(active_days, self.log_mm_wealth, color=colors['mm'],
                 linewidth=1.8, label='Market Maker Wealth')
        ax3.plot(active_days, self.log_manip_wealth, color=colors['manip'],
                 linewidth=1.8, label='Manipulator Wealth (avg)')
        ax3.set_title('Specialist Agent Wealth: Market Maker & Manipulators',
                      fontsize=13, fontweight='bold', pad=15)
        ax3.set_xlabel('Calendar Days', fontsize=11, fontweight='bold')
        ax3.set_ylabel('Agent Wealth ($)', fontsize=11, fontweight='bold')
        ax3.grid(True, linestyle=':', alpha=0.6)
        ax3.legend(loc='upper left', frameon=True, facecolor='white',
                   framealpha=0.9)

        # Subplot 4: population demographics.
        for s in self.STRATEGIES:
            ax4.plot(active_days, self.log_demographics[s], color=colors[s],
                     linewidth=1.8, label=f'{s.capitalize()} Count')
        ax4.set_title('Trader Population Demographics Over Time',
                      fontsize=13, fontweight='bold', pad=15)
        ax4.set_xlabel('Calendar Days', fontsize=11, fontweight='bold')
        ax4.set_ylabel('Number of Active Agents', fontsize=11,
                       fontweight='bold')
        ax4.grid(True, linestyle=':', alpha=0.6)
        ax4.legend(loc='upper left', frameon=True, facecolor='white',
                   framealpha=0.9)

        plt.tight_layout()
        plt.savefig(output_path, dpi=300)
        print(f"Dashboard figure saved as '{output_path}'.")
        plt.close(fig)


def export_simulation_metrics(sim: Simulation,
                              csv_path: str = "simulation_results.csv") -> None:
    """Exports daily metrics (incl. specialist agents) to CSV."""
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
