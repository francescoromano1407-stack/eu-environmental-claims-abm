"""
Financial Market Simulation with a Peer-to-Peer Limit Order Book (LOB) Engine.

This script implements an agent-based simulation of a financial market running
for 1,000 calendar days. It features:
1. A P2P Limit Order Book with price-time priority.
2. Evolutionary agent dynamics with survival and strategy switching.
3. Macroeconomic factors: quarterly dividends and risk-free interest on cash.
4. Market frictions: transaction commissions and a holding-period Tobin tax (FIFO).
5. Comprehensive data logging and a multi-panel Matplotlib dashboard.

Author: Antigravity (Advanced Agentic Coding Agent)
Date: June 2026
"""

import random
import collections
import statistics
import matplotlib.pyplot as plt


class LimitOrder:
    """Represents a limit order placed in the order book."""

    def __init__(self, order_id: int, trader_id: str, side: str, price: float, quantity: int, timestamp: int):
        """
        Initializes a LimitOrder.

        Args:
            order_id: Unique identifier for the order.
            trader_id: Identifier of the trader who placed the order.
            side: Either 'BUY' or 'SELL'.
            price: The limit price of the order.
            quantity: The quantity of shares ordered.
            timestamp: Logical timestamp indicating price-time priority.
        """
        self.order_id = order_id
        self.trader_id = trader_id
        self.side = side.upper()  # 'BUY' or 'SELL'
        self.type = self.side     # For compatibility with prompt requirements
        self.price = float(price)
        self.quantity = int(quantity)
        self.timestamp = timestamp

    def __repr__(self):
        return f"LimitOrder(id={self.order_id}, trader={self.trader_id}, side={self.side}, price={self.price:.2f}, qty={self.quantity}, ts={self.timestamp})"


class MarketOrder:
    """Represents a market order to be matched immediately against the book."""

    def __init__(self, trader_id: str, side: str, quantity: int):
        """
        Initializes a MarketOrder.

        Args:
            trader_id: Identifier of the trader who placed the order.
            side: Either 'BUY' or 'SELL'.
            quantity: The quantity of shares ordered.
        """
        self.trader_id = trader_id
        self.side = side.upper()  # 'BUY' or 'SELL'
        self.type = self.side     # For compatibility
        self.quantity = int(quantity)

    def __repr__(self):
        return f"MarketOrder(trader={self.trader_id}, side={self.side}, qty={self.quantity})"


class Asset:
    """Represents the traded asset with corporate balance sheet tracking."""

    def __init__(self, symbol: str, initial_price: float = 100.0, initial_balance: float = 300000.0):
        """
        Initializes the Asset.

        Args:
            symbol: Ticker symbol of the asset.
            initial_price: Starting market price.
            initial_balance: Starting corporate balance.
        """
        self.symbol = symbol
        self.price_history = [initial_price]
        self.balance_history = [initial_balance]
        self.balance = initial_balance

    def update_quarterly_balance(self):
        """Updates the corporate balance sheet using a random walk performance shock."""
        shock = random.uniform(-0.10, 0.12)
        # Apply performance shock
        self.balance = max(self.balance * (1.0 + shock), 50000.0)  # floor to prevent corporate bankruptcy
        self.balance_history.append(self.balance)

    def get_last_price(self) -> float:
        """Returns the last recorded price of the asset."""
        return self.price_history[-1]


class Trader:
    """Represents a market participant with cash, shares, and a trading strategy."""

    def __init__(self, trader_id: str, cash: float, shares: int, trader_type: str, current_day: int = 0):
        """
        Initializes a Trader.

        Args:
            trader_id: Unique string identifier.
            cash: Initial available cash balance.
            shares: Initial available shares.
            trader_type: One of 'noise', 'fundamentalist', or 'chartist'.
            current_day: Calendar day when the trader entered the market.
        """
        self.trader_id = trader_id
        self.cash = float(cash)
        self.cash_reserved = 0.0  # Cash locked in active bids
        self.shares = int(shares)
        self.shares_reserved = 0  # Shares locked in active asks
        self.type = trader_type

        # FIFO share ledger: stores tuples of (purchase_day, quantity, purchase_price)
        self.shares_ledger = collections.deque()
        if self.shares > 0:
            self.shares_ledger.append((current_day, self.shares, 100.0))

        # Track active limit order IDs
        self.active_orders = set()

    @property
    def total_cash(self) -> float:
        """Returns total cash (available + reserved)."""
        return self.cash + self.cash_reserved

    @property
    def total_shares(self) -> int:
        """Returns total shares (available + reserved)."""
        return self.shares + self.shares_reserved

    def get_wealth(self, current_price: float) -> float:
        """Calculates total wealth (Cash + Shares valued at the current price)."""
        return self.total_cash + (self.total_shares * current_price)

    def decide_order(self, current_price: float, v_fundamental: float, price_history: list, asks: list) -> tuple:
        """
        Determines the next trading action based on the agent's strategy.

        Args:
            current_price: Midpoint of the LOB or last closing price.
            v_fundamental: Corporate fundamental value per share.
            price_history: History of daily closing prices.
            asks: Current asks in the order book (for market buy size estimation).

        Returns:
            A tuple of (order_type, side, price, quantity) or None.
            order_type: 'LIMIT' or 'MARKET'
            side: 'BUY' or 'SELL'
            price: float limit price (or None for MARKET orders)
            quantity: int quantity
        """
        if self.type == 'noise':
            action = random.choice(['BUY', 'SELL', 'HOLD', 'HOLD'])
            if action == 'HOLD':
                return None

            order_type = 'MARKET' if random.random() < 0.3 else 'LIMIT'
            qty = random.randint(1, 5)

            if action == 'BUY':
                if order_type == 'LIMIT':
                    price = current_price * (1.0 + random.normalvariate(0.0, 0.02))
                    price = max(0.01, round(price, 2))
                    return ('LIMIT', 'BUY', price, qty)
                else:
                    return ('MARKET', 'BUY', None, qty)
            else:  # SELL
                if order_type == 'LIMIT':
                    price = current_price * (1.0 + random.normalvariate(0.0, 0.02))
                    price = max(0.01, round(price, 2))
                    return ('LIMIT', 'SELL', price, qty)
                else:
                    return ('MARKET', 'SELL', None, qty)

        elif self.type == 'fundamentalist':
            if current_price < v_fundamental * 0.95:
                # Undervalued -> BUY
                order_type = 'MARKET' if random.random() < 0.2 else 'LIMIT'
                qty = random.randint(1, 5)
                if order_type == 'LIMIT':
                    price = v_fundamental * (1.0 - random.uniform(0.01, 0.05))
                    price = max(0.01, round(price, 2))
                    return ('LIMIT', 'BUY', price, qty)
                else:
                    return ('MARKET', 'BUY', None, qty)
            elif current_price > v_fundamental * 1.05:
                # Overvalued -> SELL
                order_type = 'MARKET' if random.random() < 0.2 else 'LIMIT'
                qty = random.randint(1, 5)
                if order_type == 'LIMIT':
                    price = v_fundamental * (1.0 + random.uniform(0.01, 0.05))
                    price = max(0.01, round(price, 2))
                    return ('LIMIT', 'SELL', price, qty)
                else:
                    return ('MARKET', 'SELL', None, qty)
            return None

        elif self.type == 'chartist':
            if len(price_history) >= 15:
                # Fast EMA (N=5, alpha = 2/6 ≈ 0.333) and Slow EMA (N=15, alpha = 2/16 = 0.125)
                alpha_fast = 2.0 / (5.0 + 1.0)
                alpha_slow = 2.0 / (15.0 + 1.0)

                # Compute fast EMA over price history
                ema_fast = price_history[0]
                for p in price_history[1:]:
                    ema_fast = (p * alpha_fast) + (ema_fast * (1.0 - alpha_fast))

                # Compute slow EMA over price history
                ema_slow = price_history[0]
                for p in price_history[1:]:
                    ema_slow = (p * alpha_slow) + (ema_slow * (1.0 - alpha_slow))

                if ema_fast > ema_slow:
                    # Bullish -> BUY
                    order_type = 'MARKET' if random.random() < 0.4 else 'LIMIT'
                    qty = random.randint(1, 5)
                    if order_type == 'LIMIT':
                        price = current_price * (1.0 + random.uniform(0.005, 0.02))
                        price = max(0.01, round(price, 2))
                        return ('LIMIT', 'BUY', price, qty)
                    else:
                        return ('MARKET', 'BUY', None, qty)
                elif ema_fast < ema_slow:
                    # Bearish -> SELL
                    order_type = 'MARKET' if random.random() < 0.4 else 'LIMIT'
                    qty = random.randint(1, 5)
                    if order_type == 'LIMIT':
                        price = current_price * (1.0 - random.uniform(0.005, 0.02))
                        price = max(0.01, round(price, 2))
                        return ('LIMIT', 'SELL', price, qty)
                    else:
                        return ('MARKET', 'SELL', None, qty)
            else:
                # Fallback to noise trading in the first 15 days
                action = random.choice(['BUY', 'SELL', 'HOLD'])
                if action == 'HOLD':
                    return None
                qty = random.randint(1, 5)
                price = current_price * (1.0 + random.normalvariate(0.0, 0.02))
                price = max(0.01, round(price, 2))
                return ('LIMIT', action, price, qty)
            return None

    def __repr__(self):
        return f"Trader(id={self.trader_id}, type={self.type}, cash={self.cash:.2f}, reserved_c={self.cash_reserved:.2f}, shares={self.shares}, reserved_s={self.shares_reserved})"


class MarketMaker(Trader):
    """
    Decoupled Market Maker agent that continuously quotes bids and asks
    around the midpoint to anchor liquidity and prevent flash crashes.
    """

    def __init__(self, trader_id: str, cash: float, shares: int,
                 spread_pct: float = 0.015, level_qty: int = 5, num_levels: int = 3):
        """
        Initializes the MarketMaker, inheriting from Trader.
        """
        super().__init__(trader_id, cash, shares, trader_type='market_maker')
        self.spread_pct = spread_pct
        self.level_qty = level_qty
        self.num_levels = num_levels

    def replenish_inventory(self, initial_cash: float, initial_shares: int, current_day: int):
        """Restores cash and shares to baseline to ensure permanent liquidity provision."""
        self.cash = float(initial_cash)
        self.shares = int(initial_shares)
        self.shares_ledger.clear()
        self.shares_ledger.append((current_day, self.shares, 100.0))

    def place_quotes(self, midpoint: float, order_book: OrderBook, trader_map: dict, current_day: int):
        """
        Generates and places layered buy and sell limit orders around the midpoint.
        """
        for i in range(1, self.num_levels + 1):
            # Calculate bid and ask prices at each level
            bid_price = midpoint * (1.0 - (self.spread_pct / 2.0) - (i - 1) * 0.005)
            ask_price = midpoint * (1.0 + (self.spread_pct / 2.0) + (i - 1) * 0.005)

            bid_price = max(0.01, round(bid_price, 2))
            ask_price = max(0.01, round(ask_price, 2))

            # Place Bid (Buy Limit Order)
            bid_cost = bid_price * self.level_qty * 1.001
            if self.cash >= bid_cost:
                order_id = order_book.get_next_order_id()
                order = LimitOrder(order_id, self.trader_id, 'BUY', bid_price, self.level_qty, timestamp=current_day)
                order_book.add_limit_order(order, trader_map, current_day)

            # Place Ask (Sell Limit Order)
            if self.shares >= self.level_qty:
                order_id = order_book.get_next_order_id()
                order = LimitOrder(order_id, self.trader_id, 'SELL', ask_price, self.level_qty, timestamp=current_day)
                order_book.add_limit_order(order, trader_map, current_day)


class OrderBook:
    """P2P Limit Order Book Matching Engine."""

    def __init__(self):
        """Initializes bids and asks priority queues."""
        self.bids = []  # sorted descending by price, then ascending by timestamp
        self.asks = []  # sorted ascending by price, then ascending by timestamp
        self.order_id_counter = 0

    def get_next_order_id(self) -> int:
        """Generates a unique order ID."""
        self.order_id_counter += 1
        return self.order_id_counter

    def get_midpoint(self, default_price: float) -> float:
        """Returns the midpoint of best bid and best ask, or default_price if book is dry."""
        if self.bids and self.asks:
            return (self.bids[0].price + self.asks[0].price) / 2.0
        elif self.bids:
            return self.bids[0].price
        elif self.asks:
            return self.asks[0].price
        else:
            return default_price

    def cancel_order(self, order_id: int, trader_map: dict) -> bool:
        """
        Cancels an active limit order and refunds the escrowed funds/shares.

        Args:
            order_id: The ID of the order to cancel.
            trader_map: Dict mapping trader IDs to Trader objects.

        Returns:
            True if cancelled, False otherwise.
        """
        # Search bids
        for i, order in enumerate(self.bids):
            if order.order_id == order_id:
                trader = trader_map[order.trader_id]
                # Refund reserved cash
                refund_amount = order.price * order.quantity * 1.001
                trader.cash_reserved -= refund_amount
                trader.cash += refund_amount
                if order_id in trader.active_orders:
                    trader.active_orders.remove(order_id)
                self.bids.pop(i)
                return True

        # Search asks
        for i, order in enumerate(self.asks):
            if order.order_id == order_id:
                trader = trader_map[order.trader_id]
                # Refund reserved shares
                trader.shares_reserved -= order.quantity
                trader.shares += order.quantity
                if order_id in trader.active_orders:
                    trader.active_orders.remove(order_id)
                self.asks.pop(i)
                return True

        return False

    def clear_all_orders(self, trader_map: dict):
        """Cancels all active orders in the book (refunds escrow)."""
        # Copy lists to avoid modification during iteration
        for order in list(self.bids):
            self.cancel_order(order.order_id, trader_map)
        for order in list(self.asks):
            self.cancel_order(order.order_id, trader_map)

    def add_limit_order(self, order: LimitOrder, trader_map: dict, current_day: int) -> list:
        """
        Places a Limit Order in the book. Matches immediately if crossing the spread.

        Args:
            order: The LimitOrder object.
            trader_map: Dict mapping trader IDs to Trader objects.
            current_day: The current calendar day of the simulation.

        Returns:
            A list of execution tuples: (day, price, qty).
        """
        trades = []

        if order.side == 'BUY':
            # Match against asks
            while self.asks and order.quantity > 0:
                best_ask = self.asks[0]
                if order.price >= best_ask.price:
                    # Match occurs!
                    trade_price = best_ask.price  # Price-priority maker price
                    trade_qty = min(order.quantity, best_ask.quantity)

                    # Execute the P2P trade
                    self.execute_trade(
                        buyer_id=order.trader_id,
                        seller_id=best_ask.trader_id,
                        price=trade_price,
                        qty=trade_qty,
                        current_day=current_day,
                        trader_map=trader_map,
                        buyer_is_maker=False,
                        seller_is_maker=True
                    )
                    trades.append((current_day, trade_price, trade_qty))

                    # Update order and book quantities
                    order.quantity -= trade_qty
                    best_ask.quantity -= trade_qty

                    if best_ask.quantity == 0:
                        seller = trader_map[best_ask.trader_id]
                        if best_ask.order_id in seller.active_orders:
                            seller.active_orders.remove(best_ask.order_id)
                        self.asks.pop(0)
                else:
                    break

            # If there's still quantity remaining, escrow it and add to bids
            if order.quantity > 0:
                buyer = trader_map[order.trader_id]
                escrow_amount = order.price * order.quantity * 1.001
                buyer.cash -= escrow_amount
                buyer.cash_reserved += escrow_amount

                self.bids.append(order)
                buyer.active_orders.add(order.order_id)
                # Sort: price desc, timestamp asc
                self.bids.sort(key=lambda x: (-x.price, x.timestamp))

        elif order.side == 'SELL':
            # Match against bids
            while self.bids and order.quantity > 0:
                best_bid = self.bids[0]
                if order.price <= best_bid.price:
                    # Match occurs!
                    trade_price = best_bid.price  # Maker price
                    trade_qty = min(order.quantity, best_bid.quantity)

                    # Execute P2P trade
                    self.execute_trade(
                        buyer_id=best_bid.trader_id,
                        seller_id=order.trader_id,
                        price=trade_price,
                        qty=trade_qty,
                        current_day=current_day,
                        trader_map=trader_map,
                        buyer_is_maker=True,
                        seller_is_maker=False
                    )
                    trades.append((current_day, trade_price, trade_qty))

                    # Update quantities
                    order.quantity -= trade_qty
                    best_bid.quantity -= trade_qty

                    if best_bid.quantity == 0:
                        buyer = trader_map[best_bid.trader_id]
                        if best_bid.order_id in buyer.active_orders:
                            buyer.active_orders.remove(best_bid.order_id)
                        self.bids.pop(0)
                else:
                    break

            # If remaining, escrow shares and add to asks
            if order.quantity > 0:
                seller = trader_map[order.trader_id]
                seller.shares -= order.quantity
                seller.shares_reserved += order.quantity

                self.asks.append(order)
                seller.active_orders.add(order.order_id)
                # Sort: price asc, timestamp asc
                self.asks.sort(key=lambda x: (x.price, x.timestamp))

        return trades

    def execute_market_order(self, order: MarketOrder, trader_map: dict, current_day: int) -> list:
        """
        Executes a Market Order against resting liquidity. Unfilled remainder immediately expires.

        Args:
            order: The MarketOrder object.
            trader_map: Dict mapping trader IDs to Trader.
            current_day: The current calendar day.

        Returns:
            A list of execution tuples: (day, price, qty).
        """
        trades = []

        if order.side == 'BUY':
            while self.asks and order.quantity > 0:
                best_ask = self.asks[0]
                trade_price = best_ask.price
                trade_qty = min(order.quantity, best_ask.quantity)

                # Ensure buyer has enough cash to pay for the trade + commission
                buyer = trader_map[order.trader_id]
                cost = trade_price * trade_qty * 1.001
                if buyer.cash < cost:
                    # Adjust quantity to affordable size
                    cost_per_share = trade_price * 1.001
                    trade_qty = int(buyer.cash // cost_per_share)
                    if trade_qty == 0:
                        break
                    cost = trade_price * trade_qty * 1.001

                # Execute P2P trade
                self.execute_trade(
                    buyer_id=order.trader_id,
                    seller_id=best_ask.trader_id,
                    price=trade_price,
                    qty=trade_qty,
                    current_day=current_day,
                    trader_map=trader_map,
                    buyer_is_maker=False,
                    seller_is_maker=True
                )
                trades.append((current_day, trade_price, trade_qty))

                order.quantity -= trade_qty
                best_ask.quantity -= trade_qty

                if best_ask.quantity == 0:
                    seller = trader_map[best_ask.trader_id]
                    if best_ask.order_id in seller.active_orders:
                        seller.active_orders.remove(best_ask.order_id)
                    self.asks.pop(0)

        elif order.side == 'SELL':
            while self.bids and order.quantity > 0:
                best_bid = self.bids[0]
                trade_price = best_bid.price
                trade_qty = min(order.quantity, best_bid.quantity)

                # Execute P2P trade
                self.execute_trade(
                    buyer_id=best_bid.trader_id,
                    seller_id=order.trader_id,
                    price=trade_price,
                    qty=trade_qty,
                    current_day=current_day,
                    trader_map=trader_map,
                    buyer_is_maker=True,
                    seller_is_maker=False
                )
                trades.append((current_day, trade_price, trade_qty))

                order.quantity -= trade_qty
                best_bid.quantity -= trade_qty

                if best_bid.quantity == 0:
                    buyer = trader_map[best_bid.trader_id]
                    if best_bid.order_id in buyer.active_orders:
                        buyer.active_orders.remove(best_bid.order_id)
                    self.bids.pop(0)

        return trades

    def execute_trade(self, buyer_id: str, seller_id: str, price: float, qty: int,
                      current_day: int, trader_map: dict, buyer_is_maker: bool, seller_is_maker: bool):
        """
        Executes double-entry bookkeeping for cash/shares, commissions, and Tobin tax.

        Args:
            buyer_id: Buyer trader ID.
            seller_id: Seller trader ID.
            price: Transaction price.
            qty: Quantity of shares traded.
            current_day: Current calendar day.
            trader_map: Trader lookup directory.
            buyer_is_maker: True if buyer was resting, False if buyer was taker.
            seller_is_maker: True if seller was resting, False if seller was taker.
        """
        buyer = trader_map[buyer_id]
        seller = trader_map[seller_id]

        trade_value = price * qty
        buyer_commission = trade_value * 0.001
        seller_commission = trade_value * 0.001

        # Calculate Tobin Tax for seller (FIFO on shares_ledger)
        tobin_tax = 0.0
        remaining_qty_to_tax = qty

        while remaining_qty_to_tax > 0 and seller.shares_ledger:
            purchase_day, p_qty, p_price = seller.shares_ledger.popleft()
            if remaining_qty_to_tax >= p_qty:
                holding_period = current_day - purchase_day
                if holding_period < 15:
                    tobin_tax += 0.005 * (price * p_qty)
                remaining_qty_to_tax -= p_qty
            else:
                holding_period = current_day - purchase_day
                if holding_period < 15:
                    tobin_tax += 0.005 * (price * remaining_qty_to_tax)
                # Put back the remaining shares in the FIFO queue
                seller.shares_ledger.appendleft((purchase_day, p_qty - remaining_qty_to_tax, p_price))
                remaining_qty_to_tax = 0

        # Adjust buyer accounts
        if buyer_is_maker:
            # Buyer's cash was reserved (at the bid order price, which matches price)
            reserved_to_deduct = price * qty * 1.001
            buyer.cash_reserved -= reserved_to_deduct
        else:
            # Buyer is taker, deduct from available cash
            buyer.cash -= (trade_value + buyer_commission)

        buyer.shares += qty
        buyer.shares_ledger.append((current_day, qty, price))

        # Adjust seller accounts
        if seller_is_maker:
            # Seller's shares were reserved
            seller.shares_reserved -= qty
        else:
            # Seller is taker, deduct from available shares
            seller.shares -= qty

        seller.cash += trade_value
        seller.cash -= (seller_commission + tobin_tax)


class Simulation:
    """Main executor of the financial market simulation."""

    def __init__(self, num_traders: int = 60, initial_cash: float = 10000.0,
                 initial_shares: int = 50, initial_price: float = 100.0,
                 rf_rate: float = 0.02, days: int = 1000):
        """
        Initializes the Simulation.

        Args:
            num_traders: Total number of starting traders.
            initial_cash: Starting cash per trader.
            initial_shares: Starting shares per trader.
            initial_price: Starting asset price.
            rf_rate: Risk-free interest rate (annual).
            days: Length of simulation in calendar days.
        """
        self.days = days
        self.rf_rate = rf_rate
        self.initial_cash = initial_cash
        self.initial_shares = initial_shares

        # Seed populations
        self.traders = []
        self.trader_map = {}
        self.next_trader_id_counter = 0

        # Split 60 traders into three equal groups
        noise_count = num_traders // 3
        fund_count = num_traders // 3
        chart_count = num_traders - (noise_count + fund_count)

        for _ in range(noise_count):
            self.create_and_add_trader('noise')
        for _ in range(fund_count):
            self.create_and_add_trader('fundamentalist')
        for _ in range(chart_count):
            self.create_and_add_trader('chartist')

        # Setup Asset and OrderBook
        total_shares = num_traders * initial_shares
        initial_balance = total_shares * initial_price  # scaled corporate balance sheet
        self.asset = Asset("XYZ", initial_price, initial_balance)
        self.order_book = OrderBook()

        # Initialize Market Maker (non-evolutionary entity)
        self.market_maker = MarketMaker(
            trader_id="T_MM",
            cash=1000000.0,
            shares=10000,
            spread_pct=0.015,
            level_qty=15,
            num_levels=5
        )
        self.trader_map["T_MM"] = self.market_maker

        # Data Logging
        self.log_price = [initial_price]
        self.log_balance = [initial_balance]
        self.log_demographics = {'noise': [], 'fundamentalist': [], 'chartist': []}
        self.log_avg_wealth = {'noise': [], 'fundamentalist': [], 'chartist': []}

    def create_and_add_trader(self, trader_type: str, current_day: int = 0) -> Trader:
        """Creates and indexes a brand new trader."""
        self.next_trader_id_counter += 1
        t_id = f"T_{trader_type[0].upper()}_{self.next_trader_id_counter}"
        trader = Trader(
            trader_id=t_id,
            cash=self.initial_cash,
            shares=self.initial_shares,
            trader_type=trader_type,
            current_day=current_day
        )
        self.traders.append(trader)
        self.trader_map[t_id] = trader
        return trader

    def log_daily_metrics(self, current_price: float):
        """Logs demographics and wealth metrics at the end of the day."""
        # 1. Demographics
        counts = {'noise': 0, 'fundamentalist': 0, 'chartist': 0}
        wealths = {'noise': [], 'fundamentalist': [], 'chartist': []}

        for trader in self.traders:
            counts[trader.type] += 1
            wealths[trader.type].append(trader.get_wealth(current_price))

        for k in ['noise', 'fundamentalist', 'chartist']:
            self.log_demographics[k].append(counts[k])
            avg_w = sum(wealths[k]) / len(wealths[k]) if wealths[k] else 0.0
            self.log_avg_wealth[k].append(avg_w)

    def get_fundamental_value(self) -> float:
        """Returns the intrinsic value based on corporate balance / shares."""
        # Total shares outstanding remains constant at num_traders * initial_shares
        return self.asset.balance / 3000.0  # 3000 shares total in simulation

    def is_weekend(self, day: int) -> bool:
        """Returns True if day index is Saturday (6) or Sunday (0) under day % 7 calendar."""
        return (day % 7) == 6 or (day % 7) == 0

    def run(self):
        """Executes the simulation loop for 1,000 calendar days."""
        print(f"Starting Financial Market Simulation for {self.days} days...")

        for day in range(1, self.days + 1):
            last_price = self.asset.get_last_price()

            # --- WEEKEND RULE ---
            if self.is_weekend(day):
                # Daily risk-free interest still accumulates on available cash
                for trader in self.traders:
                    interest = trader.cash * (self.rf_rate / 365.0)
                    trader.cash += interest

                # Log metrics for weekend day
                self.log_price.append(last_price)
                self.log_balance.append(self.asset.balance)
                self.log_daily_metrics(last_price)
                continue

            # --- WEEKDAY TRADING ---
            # 1. Corporate balance sheet update and dividend payout (every 90 days)
            if day % 90 == 0:
                self.asset.update_quarterly_balance()
                total_payout = 0.0
                for trader in self.traders:
                    payout = trader.total_shares * 2.00
                    trader.cash += payout
                    total_payout += payout

                self.asset.balance -= total_payout
                self.asset.balance = max(self.asset.balance, 50000.0)

            # 2. Clear out existing order book (refund cash/shares from old limit orders)
            self.order_book.clear_all_orders(self.trader_map)

            # Inject market maker quotes to anchor liquidity
            self.market_maker.replenish_inventory(1000000.0, 10000, day)
            self.market_maker.place_quotes(last_price, self.order_book, self.trader_map, day)

            # 3. Trader action loop
            active_traders = list(self.traders)
            random.shuffle(active_traders)

            day_trades = []

            for trader in active_traders:
                # Find current reference price: midpoint of best bid/ask, or last trade price
                ref_price = self.order_book.get_midpoint(last_price)
                v_fund = self.get_fundamental_value()

                decision = trader.decide_order(ref_price, v_fund, self.log_price, self.order_book.asks)
                if decision is None:
                    continue

                order_type, side, price, quantity = decision

                if order_type == 'LIMIT':
                    # Validate budget constraints before placing
                    if side == 'BUY':
                        cost = price * quantity * 1.001
                        if trader.cash >= cost:
                            order_id = self.order_book.get_next_order_id()
                            order = LimitOrder(order_id, trader.trader_id, side, price, quantity, timestamp=day)
                            executed = self.order_book.add_limit_order(order, self.trader_map, day)
                            day_trades.extend(executed)
                    elif side == 'SELL':
                        if trader.shares >= quantity:
                            order_id = self.order_book.get_next_order_id()
                            order = LimitOrder(order_id, trader.trader_id, side, price, quantity, timestamp=day)
                            executed = self.order_book.add_limit_order(order, self.trader_map, day)
                            day_trades.extend(executed)

                elif order_type == 'MARKET':
                    if side == 'BUY':
                        # Execute market order against liquidity
                        order = MarketOrder(trader.trader_id, side, quantity)
                        executed = self.order_book.execute_market_order(order, self.trader_map, day)
                        day_trades.extend(executed)
                    elif side == 'SELL':
                        if trader.shares > 0:
                            qty_to_sell = min(quantity, trader.shares)
                            order = MarketOrder(trader.trader_id, side, qty_to_sell)
                            executed = self.order_book.execute_market_order(order, self.trader_map, day)
                            day_trades.extend(executed)

            # 4. Daily settlement: Risk-free interest rate
            for trader in self.traders:
                interest = trader.cash * (self.rf_rate / 365.0)
                trader.cash += interest

            # 5. Record closing price
            if day_trades:
                closing_price = day_trades[-1][1]
            else:
                closing_price = last_price
            self.log_price.append(closing_price)
            self.log_balance.append(self.asset.balance)

            # 6. Bankruptcy checks and replacements
            bankrupt_traders = []
            for trader in self.traders:
                if trader.total_cash < 1e-5 and trader.total_shares == 0:
                    bankrupt_traders.append(trader)

            for bt in bankrupt_traders:
                # Cancel their orders just in case
                for oid in list(bt.active_orders):
                    self.order_book.cancel_order(oid, self.trader_map)
                # Remove
                self.traders.remove(bt)
                del self.trader_map[bt.trader_id]
                # Replace with a brand new trader of the same type
                self.create_and_add_trader(bt.type, current_day=day)

            # 7. Evolutionary review: Strategy switching (every 90 days)
            if day % 90 == 0:
                # Calculate average wealth per strategy type
                wealth_by_type = {'noise': [], 'fundamentalist': [], 'chartist': []}
                for trader in self.traders:
                    wealth_by_type[trader.type].append(trader.get_wealth(closing_price))

                avg_wealth = {}
                for k in ['noise', 'fundamentalist', 'chartist']:
                    if wealth_by_type[k]:
                        avg_wealth[k] = sum(wealth_by_type[k]) / len(wealth_by_type[k])
                    else:
                        avg_wealth[k] = 0.0

                # Determine best strategy
                best_strategy = max(avg_wealth, key=avg_wealth.get)

                # Individual review process (10% probability of switching to best strategy)
                for trader in self.traders:
                    if random.random() < 0.10:
                        trader.type = best_strategy

            # Log statistics
            self.log_daily_metrics(closing_price)

        print("Simulation complete.")

    def plot_dashboard(self):
        """Generates and displays the clean, professional dashboard using matplotlib."""
        # Use simple default style to avoid package differences
        plt.style.use('default')
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 16))

        # --- SUBPLOT 1: Asset Price vs. Corporate Balance ---
        days_range = list(range(self.days + 1))
        
        color_price = '#1f77b4'
        ax1.plot(days_range, self.log_price, color=color_price, linewidth=2, label='Asset Price ($)')
        ax1.set_xlabel('Calendar Days', fontsize=11, fontweight='bold')
        ax1.set_ylabel('Market Price ($)', color=color_price, fontsize=11, fontweight='bold')
        ax1.tick_params(axis='y', labelcolor=color_price)
        ax1.grid(True, linestyle=':', alpha=0.6)

        # Create secondary y-axis for corporate balance
        ax1_twin = ax1.twinx()
        color_bal = '#ff7f0e'
        ax1_twin.plot(days_range, self.log_balance, color=color_bal, linewidth=2, linestyle='--', label='Corporate Balance ($)')
        ax1_twin.set_ylabel('Corporate Balance ($)', color=color_bal, fontsize=11, fontweight='bold')
        ax1_twin.tick_params(axis='y', labelcolor=color_bal)

        # Combine legends
        lines_1, labels_1 = ax1.get_legend_handles_labels()
        lines_2, labels_2 = ax1_twin.get_legend_handles_labels()
        ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc='upper left', frameon=True, facecolor='white', framealpha=0.9)
        ax1.set_title('Asset Closing Price & Corporate Balance Sheet History', fontsize=13, fontweight='bold', pad=15)

        # --- SUBPLOT 2: Strategy Wealth Evolution ---
        active_days = list(range(1, self.days + 1))
        colors = {'noise': '#d62728', 'fundamentalist': '#2ca02c', 'chartist': '#9467bd'}
        
        for k in ['noise', 'fundamentalist', 'chartist']:
            ax2.plot(active_days, self.log_avg_wealth[k], color=colors[k], linewidth=2.0, label=f'{k.capitalize()} Wealth')
        
        ax2.set_title('Time-Series Evolution of Average Strategy Wealth', fontsize=13, fontweight='bold', pad=15)
        ax2.set_xlabel('Calendar Days', fontsize=11, fontweight='bold')
        ax2.set_ylabel('Average Trader Wealth ($)', fontsize=11, fontweight='bold')
        ax2.grid(True, linestyle=':', alpha=0.6)
        ax2.legend(loc='upper left', frameon=True, facecolor='white', framealpha=0.9)

        # --- SUBPLOT 3: Population Demographics ---
        for k in ['noise', 'fundamentalist', 'chartist']:
            ax3.plot(active_days, self.log_demographics[k], color=colors[k], linewidth=2.0, label=f'{k.capitalize()} Count')

        ax3.set_title('Traders Population Demographics Over Time', fontsize=13, fontweight='bold', pad=15)
        ax3.set_xlabel('Calendar Days', fontsize=11, fontweight='bold')
        ax3.set_ylabel('Number of Active Agents', fontsize=11, fontweight='bold')
        ax3.grid(True, linestyle=':', alpha=0.6)
        ax3.legend(loc='upper left', frameon=True, facecolor='white', framealpha=0.9)

        plt.tight_layout()
        # Save figure to workspace
        plt.savefig('market_simulation_dashboard.png', dpi=300)
        print("Dashboard figure saved as 'market_simulation_dashboard.png'.")
        plt.show()


def export_simulation_metrics(sim, csv_path="simulation_results.csv"):
    """
    Exports the simulation daily metrics to a structured CSV file.
    """
    import csv
    with open(csv_path, mode='w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'day', 'asset_price', 'corporate_balance',
            'noise_count', 'fundamentalist_count', 'chartist_count',
            'noise_wealth', 'fundamentalist_wealth', 'chartist_wealth'
        ])
        
        for d in range(sim.days + 1):
            if d == 0:
                writer.writerow([
                    0,
                    sim.log_price[0],
                    sim.log_balance[0],
                    "", "", "", "", "", ""
                ])
            else:
                idx = d - 1
                writer.writerow([
                    d,
                    sim.log_price[d],
                    sim.log_balance[d],
                    sim.log_demographics['noise'][idx],
                    sim.log_demographics['fundamentalist'][idx],
                    sim.log_demographics['chartist'][idx],
                    sim.log_avg_wealth['noise'][idx],
                    sim.log_avg_wealth['fundamentalist'][idx],
                    sim.log_avg_wealth['chartist'][idx]
                ])
    print(f"Simulation metrics successfully exported to '{csv_path}'.")


if __name__ == '__main__':
    # Set random seed for reproducibility
    random.seed(42)

    # Initialize and execute simulation
    sim = Simulation(num_traders=100, initial_cash=10000.0, initial_shares=100, initial_price=100.0, rf_rate=0.03, days=2000)
    sim.run()

    # Export daily statistics to CSV (decoupled data logging)
    export_simulation_metrics(sim, "simulation_results.csv")
