"""Lightweight contracts for the dry-run-first financial validation runner."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from market_sim.financial_validation_campaign import (
    DAILY_COLUMNS,
    ORDER_EVENT_COLUMNS,
    ValidationConfig,
    atomic_json,
    csv_metadata,
    execute_campaign,
    expected_identity,
    main,
    projection_from_pilot,
    validate_seed_directory,
)
from market_sim.financial_validation import diagnose_campaign
from market_sim.models import LimitOrder
from market_sim.order_book import OrderBook
from market_sim.traders import Trader


class FinancialValidationCampaignTests(unittest.TestCase):
    def test_seed_schedule_is_deterministic_and_independent(self):
        config = ValidationConfig(Path("unused"), seeds=3)
        first = config.plans()
        second = config.plans()
        self.assertEqual(first, second)
        self.assertEqual(len({plan.market_seed for plan in first}), 3)
        self.assertEqual(len({plan.supervision_seed for plan in first}), 3)
        explicit = ValidationConfig(
            Path("unused"), seeds=2, seed_list=(11, 29)).plans()
        self.assertEqual([plan.market_seed for plan in explicit], [11, 29])

    def test_dry_run_never_creates_output_or_calls_executor(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "must_not_exist"
            stream = StringIO()
            with patch(
                    "market_sim.financial_validation_campaign.execute_campaign"
            ) as execute, redirect_stdout(stream):
                main([
                    "--output-root", str(output), "--seeds", "1",
                    "--horizon", "60", "--burn-in", "10",
                ])
            execute.assert_not_called()
            self.assertFalse(output.exists())
            self.assertIn("EXECUTION BLOCKED", stream.getvalue())

    def _write_valid_seed(self, root: Path, write_events: bool = True):
        config = ValidationConfig(
            root, seeds=1, horizon=60, burn_in=10,
            write_order_book_events=write_events)
        plan = config.plans()[0]
        identity = expected_identity(config, plan)
        seed_dir = root / plan.identifier
        seed_dir.mkdir(parents=True)
        daily = seed_dir / "daily_market.csv"
        with daily.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=DAILY_COLUMNS)
            writer.writeheader()
            for day in range(11, 61):
                writer.writerow({
                    "day": day, "symbol": "TST",
                    "asset_price": 100 + day / 10,
                    "log_return": .001, "volume": 10,
                    "realized_volatility": .01,
                })
        events = seed_dir / "order_book_events.csv"
        if write_events:
            with events.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=ORDER_EVENT_COLUMNS)
                writer.writeheader()
                writer.writerow({
                    **{column: "" for column in ORDER_EVENT_COLUMNS},
                    "timestamp": 1, "day": 11, "symbol": "TST",
                    "trader_id": "T1", "event_type": "trade",
                    "side": "BUY", "order_type": "MARKET",
                    "executed_quantity": 1, "execution_price": 101,
                    "trade_volume": 1, "trade_sign": 1,
                })
        exports = {
            "daily_market": {"enabled": True, **csv_metadata(daily)},
            "order_book_events": (
                {"enabled": True, **csv_metadata(events)} if write_events
                else {"enabled": False, "filename": events.name,
                      "records": 0, "bytes": 0, "sha256": None,
                      "schema_columns": list(ORDER_EVENT_COLUMNS)}),
        }
        manifest = {
            **identity, "status": "complete", "elapsed_seconds": 1.0,
            "exports": exports,
        }
        atomic_json(seed_dir / "manifest.json", manifest)
        return config, plan, seed_dir

    def test_resume_validation_checks_hash_schema_and_record_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, plan, seed_dir = self._write_valid_seed(root)
            identity = expected_identity(config, plan)
            valid, reason, _ = validate_seed_directory(seed_dir, identity)
            self.assertTrue(valid, reason)
            with (seed_dir / "daily_market.csv").open(
                    "a", encoding="utf-8") as handle:
                handle.write("corruption\n")
            valid, reason, _ = validate_seed_directory(seed_dir, identity)
            self.assertFalse(valid)
            self.assertIn("mismatch", reason)

    def test_atomic_json_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            atomic_json(path, {"complete": True})
            self.assertEqual(json.loads(path.read_text()), {"complete": True})
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_five_seed_projection_uses_configured_safety_factor(self):
        manifests = [{
            "status": "complete", "elapsed_seconds": 10,
            "exports": {"daily": {"enabled": True, "bytes": 100}},
        } for _ in range(5)]
        projection = projection_from_pilot(manifests, 1.25)
        self.assertTrue(projection["available"])
        self.assertEqual(projection["projected_30_seed_elapsed_seconds"], 375)
        self.assertEqual(projection["projected_30_seed_output_bytes"], 3750)
        unavailable = projection_from_pilot(manifests[:4], 1.25)
        self.assertFalse(unavailable["available"])

    def test_required_export_schemas_are_explicit(self):
        self.assertTrue({"day", "asset_price", "log_return", "volume",
                         "realized_volatility"}.issubset(DAILY_COLUMNS))
        self.assertTrue({"timestamp", "event_type", "best_bid", "best_ask",
                         "spread", "bid_depth", "ask_depth", "trade_sign"}
                        .issubset(ORDER_EVENT_COLUMNS))

    def test_multi_seed_diagnostics_use_seed_as_unit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_valid_seed(root, write_events=False)
            result = diagnose_campaign(root)
            self.assertEqual(result["valid_seed_count"], 1)
            self.assertEqual(result["unit_of_cross_seed_inference"],
                             "seed; returns are never pooled across paths")
            self.assertEqual(
                result["aggregate_classifications"]
                ["positive_spread_and_depth"]["status"], "pending")
            self.assertEqual(
                result["aggregate_seed_metrics"]["excess_kurtosis"]
                ["n_seeds"], 1)

    def test_order_book_observer_is_passive_and_optional(self):
        buyer = Trader("B", 10_000.0, 0, "noise")
        seller = Trader("S", 1_000.0, 20, "noise")
        traders = {"B": buyer, "S": seller}
        book = OrderBook()
        events = []
        book.set_event_sink(events.append)
        book.set_observation_day(3)
        ask = LimitOrder(book.get_next_order_id(), "S", "SELL", 100, 5, 3)
        bid = LimitOrder(book.get_next_order_id(), "B", "BUY", 100, 5, 3)
        book.add_limit_order(ask, traders, 3)
        trades = book.add_limit_order(bid, traders, 3)
        self.assertEqual(trades, [(3, 100.0, 5)])
        self.assertIn("trade", {event["event_type"] for event in events})
        self.assertIn("full_execution",
                      {event["event_type"] for event in events})
        count = len(events)
        book.set_event_sink(None)
        self.assertFalse(book.cancel_order(999, traders))
        self.assertEqual(len(events), count)

    def test_mock_execution_is_atomic_and_resumable(self):
        class FakeBook:
            def __init__(self):
                self.sink = None

            def set_event_sink(self, sink):
                self.sink = sink

        class FakeSimulation:
            calls = 0

            def __init__(self, **kwargs):
                type(self).calls += 1
                self.days = kwargs["days"]
                self.order_book = FakeBook()
                self.venues = None
                self.log_price = [100.0]

            def run(self):
                for day in range(1, self.days + 1):
                    self.log_price.append(self.log_price[-1] * 1.001)
                    if self.order_book.sink is not None:
                        self.order_book.sink({
                            "day": day, "event_type": "trade",
                            "trader_id": "T1", "side": "BUY",
                            "order_type": "MARKET", "quantity": 1,
                            "executed_quantity": 1,
                            "execution_price": self.log_price[-1],
                            "best_bid": self.log_price[-1] - .01,
                            "best_ask": self.log_price[-1] + .01,
                            "spread": .02, "bid_depth": 10,
                            "ask_depth": 10,
                            "mid_price": self.log_price[-1],
                            "mid_price_before": self.log_price[-2],
                            "trade_volume": 1, "trade_sign": 1,
                        })

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "campaign"
            config = ValidationConfig(
                root, seeds=1, horizon=60, burn_in=10,
                write_order_book_events=True)
            first = execute_campaign(config, simulation_factory=FakeSimulation)
            self.assertEqual(first["valid"], ["seed_001"])
            self.assertEqual(FakeSimulation.calls, 1)
            self.assertTrue((root / "seed_001" / "manifest.json").is_file())
            self.assertTrue((root / "aggregate_manifest.json").is_file())
            self.assertTrue((root / "diagnostics" /
                             "multi_seed_financial_validation.json").is_file())
            second = execute_campaign(config, simulation_factory=FakeSimulation)
            self.assertEqual(second["reused"], ["seed_001"])
            self.assertEqual(FakeSimulation.calls, 1)


if __name__ == "__main__":
    unittest.main()
