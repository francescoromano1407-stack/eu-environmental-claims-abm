"""Dry-run-first, seed-resumable financial-market validation campaign.

This module is intentionally separate from the policy LHS campaign.  It
uses fixed parameters and independent seeds to export post-burn-in market
paths and passive order-book observations.  Importing it never runs a model.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import inspect
import json
import math
import os
import random
import shutil
import subprocess
import time
import traceback
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


SEED_MANIFEST_SCHEMA = "financial-validation-seed/v1"
AGGREGATE_MANIFEST_SCHEMA = "financial-validation-campaign/v1"
DAILY_SCHEMA = "daily-market/v1"
ORDER_EVENT_SCHEMA = "order-book-events/v1"
NOTICE = (
    "Simulation-based stylized-facts validation; not empirical calibration, "
    "empirical validation, causal estimation, or a real-world forecast."
)

DAILY_COLUMNS = (
    "day", "symbol", "asset_price", "log_return", "volume",
    "realized_volatility",
)
ORDER_EVENT_COLUMNS = (
    "timestamp", "day", "symbol", "trader_id", "event_type", "order_id",
    "counterparty_order_id", "side", "order_type", "limit_price",
    "quantity", "executed_quantity", "execution_price", "best_bid",
    "best_ask", "spread", "bid_depth", "ask_depth", "mid_price",
    "mid_price_before", "trade_volume", "trade_sign",
)
SUPPORTED_EVENTS = {
    "order_submission", "cancellation", "partial_execution",
    "full_execution", "trade",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat() \
        .replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def canonical_json(value: Any) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(_jsonable(value), indent=2,
                                    sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


@lru_cache(maxsize=4)
def model_source_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if "results" in relative.parts or "__pycache__" in relative.parts:
            continue
        if (not relative.parts or relative.parts[0] != "market_sim") \
                and relative.name != "run_financial_validation_campaign.py":
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def code_provenance(root: Path) -> dict[str, Any]:
    def git(*arguments: str) -> str | None:
        try:
            completed = subprocess.run(
                ["git", *arguments], cwd=root, capture_output=True,
                text=True, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return completed.stdout.strip() if completed.returncode == 0 else None

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain", "--untracked-files=normal")
    return {
        "git_commit": commit or "unavailable",
        "working_tree_dirty": bool(status) if status is not None else None,
        "working_tree_status_sha256": sha256_bytes(
            (status or "unavailable").encode("utf-8")),
        "python_source_tree_sha256": model_source_sha256(root),
    }


@dataclass(frozen=True)
class SeedPlan:
    identifier: str
    ordinal: int
    market_seed: int
    supervision_seed: int


@dataclass(frozen=True)
class ValidationConfig:
    output_root: Path
    seeds: int = 5
    seed_list: tuple[int, ...] | None = None
    horizon: int = 10_000
    burn_in: int = 2_000
    regime: str = "current_eu_supervision"
    num_traders: int = 30
    market_seed_base: int = 20_260_716
    supervision_seed_base: int = 104_729
    write_order_book_events: bool = False
    safety_factor: float = 1.25

    def validate(self) -> None:
        if self.seeds < 1:
            raise ValueError("--seeds must be positive")
        if self.horizon < 50:
            raise ValueError("--horizon must be at least 50 days")
        if self.burn_in < 0 or self.burn_in >= self.horizon:
            raise ValueError("--burn-in must be nonnegative and below horizon")
        if self.num_traders < 3:
            raise ValueError("--num-traders must be at least three")
        if not 1.25 <= self.safety_factor <= 1.30:
            raise ValueError("--safety-factor must lie from 1.25 to 1.30")
        if self.regime != "current_eu_supervision":
            raise ValueError(
                "financial validation is baseline-only by default; the only "
                "currently permitted regime is current_eu_supervision")
        if self.seed_list is not None and len(self.seed_list) != self.seeds:
            raise ValueError("--seed-list length must equal --seeds")

    def plans(self) -> list[SeedPlan]:
        self.validate()
        markets = (list(self.seed_list) if self.seed_list is not None else [
            self.market_seed_base + 1_000_003 * index
            for index in range(self.seeds)
        ])
        if len(set(markets)) != len(markets):
            raise ValueError("market seeds must be unique")
        return [
            SeedPlan(
                identifier=f"seed_{index + 1:03d}", ordinal=index + 1,
                market_seed=int(market_seed),
                supervision_seed=(self.supervision_seed_base
                                  + 104_729 * index),
            )
            for index, market_seed in enumerate(markets)
        ]


def complete_simulation_parameters(config: ValidationConfig,
                                   plan: SeedPlan) -> dict[str, Any]:
    """Serialize every Simulation constructor parameter, including defaults."""
    from market_sim.policy_regimes import GreenwashingPolicyRegime
    from market_sim.simulation import DEFAULT_ESG_PROFILES, Simulation

    overrides = {
        "num_traders": config.num_traders,
        "days": config.horizon,
        "num_manipulators": 0,
        "enable_credit": False,
        "enable_esg": True,
        "enable_regulation": True,
        "enable_greenwashing_supervision": True,
        "supervision_seed": plan.supervision_seed,
        "greenwashing_policy_regime":
            GreenwashingPolicyRegime.CURRENT_EU_SUPERVISION,
    }
    parameters: dict[str, Any] = {}
    signature = inspect.signature(Simulation.__init__)
    for name, parameter in signature.parameters.items():
        if name == "self":
            continue
        value = overrides.get(name, parameter.default)
        if value is inspect.Parameter.empty:
            raise ValueError(f"unresolved Simulation parameter: {name}")
        parameters[name] = _jsonable(value)
    if parameters.get("asset_profiles") is None:
        parameters["effective_asset_profiles"] = _jsonable(
            DEFAULT_ESG_PROFILES)
    return parameters


def simulation_arguments(config: ValidationConfig,
                         plan: SeedPlan) -> dict[str, Any]:
    """Runtime overrides; unlisted constructor values keep native defaults."""
    return {
        "num_traders": config.num_traders,
        "days": config.horizon,
        "num_manipulators": 0,
        "enable_credit": False,
        "enable_esg": True,
        "enable_regulation": True,
        "enable_greenwashing_supervision": True,
        "supervision_seed": plan.supervision_seed,
        "greenwashing_policy_regime": config.regime,
    }


def expected_identity(config: ValidationConfig,
                      plan: SeedPlan) -> dict[str, Any]:
    identity = {
        "manifest_schema": SEED_MANIFEST_SCHEMA,
        "daily_schema": DAILY_SCHEMA,
        "order_event_schema": ORDER_EVENT_SCHEMA,
        "seed_identifier": plan.identifier,
        "market_seed": plan.market_seed,
        "supervision_seed": plan.supervision_seed,
        "regime": config.regime,
        "horizon": config.horizon,
        "burn_in": config.burn_in,
        "burn_in_policy": "export days strictly greater than burn_in",
        "num_traders": config.num_traders,
        "write_order_book_events": config.write_order_book_events,
        "model_source_sha256": model_source_sha256(
            Path(__file__).resolve().parents[1]),
        "simulation_parameters": complete_simulation_parameters(config, plan),
    }
    identity["design_identity_sha256"] = sha256_bytes(
        canonical_json(identity).encode("utf-8"))
    return identity


def csv_metadata(path: Path) -> dict[str, Any]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        records = sum(1 for _ in reader)
    return {
        "filename": path.name,
        "schema_columns": header,
        "records": records,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def validate_seed_directory(seed_dir: Path, identity: Mapping[str, Any]) \
        -> tuple[bool, str, dict[str, Any] | None]:
    manifest_path = seed_dir / "manifest.json"
    if not seed_dir.is_dir():
        return False, "seed directory is missing", None
    if not manifest_path.is_file():
        return False, "manifest.json is missing", None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return False, f"manifest is unreadable: {error}", None
    if manifest.get("status") != "complete":
        return False, "manifest status is not complete", manifest
    for key in (
            "manifest_schema", "daily_schema", "order_event_schema",
            "seed_identifier", "market_seed", "supervision_seed", "regime",
            "horizon", "burn_in", "burn_in_policy", "num_traders",
            "write_order_book_events", "simulation_parameters",
            "model_source_sha256", "design_identity_sha256"):
        if manifest.get(key) != identity.get(key):
            return False, f"incompatible manifest field: {key}", manifest
    exports = manifest.get("exports")
    if not isinstance(exports, dict):
        return False, "manifest exports are missing", manifest
    requirements = [("daily_market", DAILY_COLUMNS)]
    if identity["write_order_book_events"]:
        requirements.append(("order_book_events", ORDER_EVENT_COLUMNS))
    for export_name, required_columns in requirements:
        recorded = exports.get(export_name)
        if not isinstance(recorded, dict) or not recorded.get("enabled", True):
            return False, f"required export is disabled: {export_name}", manifest
        path = seed_dir / str(recorded.get("filename", ""))
        if not path.is_file():
            return False, f"export is missing: {export_name}", manifest
        try:
            observed = csv_metadata(path)
        except (OSError, csv.Error) as error:
            return False, f"cannot inspect {export_name}: {error}", manifest
        if not set(required_columns).issubset(observed["schema_columns"]):
            return False, f"required columns missing from {export_name}", manifest
        for key in ("records", "bytes", "sha256"):
            if recorded.get(key) != observed[key]:
                return False, f"{export_name} {key} mismatch", manifest
    expected_daily = int(identity["horizon"]) - int(identity["burn_in"])
    if exports["daily_market"].get("records") != expected_daily:
        return False, "daily_market record count is inconsistent", manifest
    return True, "valid", manifest


def inspect_campaign(config: ValidationConfig) -> dict[str, Any]:
    valid, missing, rejected = [], [], []
    details = []
    for plan in config.plans():
        identity = expected_identity(config, plan)
        seed_dir = config.output_root / plan.identifier
        ok, reason, manifest = validate_seed_directory(seed_dir, identity)
        item = {
            "identifier": plan.identifier,
            "market_seed": plan.market_seed,
            "supervision_seed": plan.supervision_seed,
            "path": str(seed_dir.resolve()),
            "reason": reason,
        }
        details.append(item)
        if ok:
            valid.append(plan.identifier)
        elif not seed_dir.exists():
            missing.append(plan.identifier)
        else:
            rejected.append({**item, "manifest_status":
                             manifest.get("status") if manifest else None})
    pending = [plan.identifier for plan in config.plans()
               if plan.identifier not in valid]
    return {
        "valid": valid, "missing": missing, "rejected": rejected,
        "pending": pending, "details": details,
    }


class OrderEventRecorder:
    """Stream passive post-burn-in events and retain daily traded volume."""

    def __init__(self, symbol: str, burn_in: int,
                 path: Path | None = None):
        self.symbol = symbol
        self.burn_in = burn_in
        self.path = path
        self.sequence = 0
        self.records = 0
        self.daily_volume: dict[int, float] = defaultdict(float)
        self._handle = None
        self._writer = None

    def __enter__(self) -> "OrderEventRecorder":
        if self.path is not None:
            self._handle = self.path.open("w", newline="", encoding="utf-8")
            self._writer = csv.DictWriter(
                self._handle, fieldnames=ORDER_EVENT_COLUMNS,
                extrasaction="ignore")
            self._writer.writeheader()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._handle is not None:
            self._handle.close()

    def __call__(self, event: Mapping[str, Any]) -> None:
        self.sequence += 1
        day = event.get("day")
        if day is None or int(day) <= self.burn_in:
            return
        if event.get("event_type") == "trade":
            self.daily_volume[int(day)] += float(event.get("trade_volume") or 0)
        if self._writer is None:
            return
        row = {column: event.get(column) for column in ORDER_EVENT_COLUMNS}
        row["timestamp"] = self.sequence
        row["symbol"] = self.symbol
        self._writer.writerow({key: "" if value is None else value
                               for key, value in row.items()})
        self.records += 1


def _rolling_volatility(returns: Sequence[float], index: int,
                        window: int = 20) -> float:
    sample = returns[max(0, index - window + 1):index + 1]
    if len(sample) < 2:
        return 0.0
    mean = sum(sample) / len(sample)
    return math.sqrt(sum((value - mean) ** 2 for value in sample)
                     / (len(sample) - 1))


def write_daily_market(path: Path, prices: Sequence[float], symbol: str,
                       burn_in: int,
                       daily_volume: Mapping[int, float]) -> int:
    if len(prices) < 2:
        raise ValueError("simulation did not produce a usable price path")
    returns = [0.0] + [math.log(prices[index] / prices[index - 1])
                       for index in range(1, len(prices))]
    records = 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DAILY_COLUMNS)
        writer.writeheader()
        for day in range(burn_in + 1, len(prices)):
            writer.writerow({
                "day": day,
                "symbol": symbol,
                "asset_price": prices[day],
                "log_return": returns[day],
                "volume": daily_volume.get(day, 0.0),
                "realized_volatility": _rolling_volatility(returns, day),
            })
            records += 1
    return records


def _primary_market(simulation: Any) -> tuple[str, Any, Sequence[float]]:
    venues = getattr(simulation, "venues", None)
    if venues:
        primary = venues[0]
        return primary.symbol, primary.order_book, simulation.log_price
    return "XYZ", simulation.order_book, simulation.log_price


def run_seed(config: ValidationConfig, plan: SeedPlan, root: Path,
             provenance: Mapping[str, Any],
             simulation_factory: Callable[..., Any] | None = None) \
        -> dict[str, Any]:
    """Run one seed into a temporary directory and publish atomically."""
    from market_sim.simulation import Simulation

    factory = simulation_factory or Simulation
    identity = expected_identity(config, plan)
    target = root / plan.identifier
    temporary = root / f".{plan.identifier}.{uuid.uuid4().hex}.tmp"
    temporary.mkdir(parents=True, exist_ok=False)
    started_utc = utc_now()
    started = time.perf_counter()
    try:
        random.seed(plan.market_seed)
        simulation = factory(**simulation_arguments(config, plan))
        symbol, book, _ = _primary_market(simulation)
        event_path = (temporary / "order_book_events.csv"
                      if config.write_order_book_events else None)
        with OrderEventRecorder(symbol, config.burn_in, event_path) as recorder:
            book.set_event_sink(recorder)
            simulation.run()
            book.set_event_sink(None)
        _, _, prices = _primary_market(simulation)
        daily_path = temporary / "daily_market.csv"
        write_daily_market(daily_path, prices, symbol, config.burn_in,
                           recorder.daily_volume)
        exports: dict[str, Any] = {
            "daily_market": {"enabled": True, **csv_metadata(daily_path)},
            "order_book_events": {
                "enabled": config.write_order_book_events,
                **(csv_metadata(event_path) if event_path is not None else {
                    "filename": "order_book_events.csv", "records": 0,
                    "bytes": 0, "sha256": None,
                    "schema_columns": list(ORDER_EVENT_COLUMNS),
                }),
            },
        }
        elapsed = time.perf_counter() - started
        manifest = {
            **identity,
            "status": "complete",
            "notice": NOTICE,
            "code_provenance": dict(provenance),
            "started_utc": started_utc,
            "completed_utc": utc_now(),
            "elapsed_seconds": elapsed,
            "primary_symbol": symbol,
            "event_timestamp_semantics":
                "deterministic monotonic model-event sequence; day is separate",
            "depth_semantics":
                "total active resting quantity at emission: submissions are observed before matching; trades, executions, and cancellations after their state update",
            "missing_value_convention": "empty CSV field means not applicable",
            "available_event_types": sorted(SUPPORTED_EVENTS),
            "unavailable_or_approximated": [
                "Order amendment is not implemented by the model and is not fabricated.",
                "Intraday wall-clock time is unavailable; timestamp is event sequence.",
                "The event stream covers the primary listing only.",
            ],
            "exports": exports,
            "failure": None,
        }
        atomic_json(temporary / "manifest.json", manifest)
        if target.exists():
            raise FileExistsError(f"refusing to overwrite existing {target}")
        os.replace(temporary, target)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _quarantine_invalid(root: Path, identifier: str) -> Path | None:
    source = root / identifier
    if not source.exists():
        return None
    rejected = root / "rejected"
    rejected.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = rejected / f"{identifier}_{timestamp}_{uuid.uuid4().hex[:8]}"
    os.replace(source, destination)
    return destination


def projection_from_pilot(manifests: Sequence[Mapping[str, Any]],
                          safety_factor: float) -> dict[str, Any]:
    if not 1.25 <= safety_factor <= 1.30:
        raise ValueError("safety factor must lie from 1.25 to 1.30")
    complete = [item for item in manifests if item.get("status") == "complete"]
    if len(complete) != 5:
        return {
            "available": False,
            "label": "planning estimate unavailable until exactly five valid pilot seeds complete",
        }
    elapsed = sum(float(item["elapsed_seconds"]) for item in complete)
    storage = sum(sum(int(export.get("bytes", 0))
                      for export in item["exports"].values()
                      if export.get("enabled")) for item in complete)
    return {
        "available": True,
        "label": "conservative planning estimate derived from completed five-seed pilot",
        "safety_factor": safety_factor,
        "pilot_elapsed_seconds": elapsed,
        "pilot_output_bytes": storage,
        "projected_30_seed_elapsed_seconds": elapsed * 6 * safety_factor,
        "projected_30_seed_output_bytes": storage * 6 * safety_factor,
    }


def build_aggregate_manifest(config: ValidationConfig, audit: Mapping[str, Any],
                             reused: Sequence[str], newly_run: Sequence[str],
                             quarantined: Sequence[Mapping[str, Any]],
                             failures: Sequence[Mapping[str, Any]],
                             provenance: Mapping[str, Any]) -> dict[str, Any]:
    manifests = []
    per_seed_runtime = {}
    bytes_per_seed = {}
    for plan in config.plans():
        path = config.output_root / plan.identifier / "manifest.json"
        if not path.is_file():
            continue
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifests.append(manifest)
        per_seed_runtime[plan.identifier] = manifest.get("elapsed_seconds")
        bytes_per_seed[plan.identifier] = sum(
            int(item.get("bytes", 0)) for item in manifest["exports"].values()
            if item.get("enabled"))
    runtimes = [float(value) for value in per_seed_runtime.values()
                if value is not None]
    sizes = list(bytes_per_seed.values())
    anomalous = []
    if runtimes:
        mean_runtime = sum(runtimes) / len(runtimes)
        anomalous.extend(identifier for identifier, value
                         in per_seed_runtime.items()
                         if float(value) > 2 * mean_runtime)
    if sizes:
        mean_size = sum(sizes) / len(sizes)
        anomalous.extend(identifier for identifier, value
                         in bytes_per_seed.items()
                         if value > 2 * mean_size)
    return {
        "manifest_schema": AGGREGATE_MANIFEST_SCHEMA,
        "updated_utc": utc_now(),
        "notice": NOTICE,
        "code_provenance": dict(provenance),
        "campaign_configuration": _jsonable(config),
        "seed_schedule": [_jsonable(plan) for plan in config.plans()],
        "reused": list(reused),
        "rejected": list(audit["rejected"]),
        "quarantined": list(quarantined),
        "missing": list(audit["missing"]),
        "pending": list(audit["pending"]),
        "newly_run": list(newly_run),
        "failures": list(failures),
        "valid": list(audit["valid"]),
        "total_elapsed_seconds": sum(runtimes),
        "per_seed_elapsed_seconds": per_seed_runtime,
        "total_output_bytes": sum(sizes),
        "bytes_per_seed": bytes_per_seed,
        "anomalous_seed_outputs": sorted(set(anomalous)),
        "unavailable_or_approximated": [
            "Order amendment is unavailable in the current model.",
            "Intraday wall-clock timestamps are unavailable.",
            "Order-book event output covers the primary listing only.",
        ],
        "projection_to_30_seeds": projection_from_pilot(
            manifests, config.safety_factor),
    }


def print_preflight(config: ValidationConfig, audit: Mapping[str, Any]) -> None:
    print("FINANCIAL VALIDATION PREFLIGHT (fixed parameters; not LHS)")
    print(f"output root: {config.output_root.resolve()}")
    print(f"configuration: horizon={config.horizon}, burn_in={config.burn_in}, "
          f"regime={config.regime}, traders={config.num_traders}, "
          f"order_events={config.write_order_book_events}")
    print("intended independent seeds:")
    for plan in config.plans():
        print(f"  {plan.identifier}: market={plan.market_seed}, "
              f"supervision={plan.supervision_seed}, "
              f"path={(config.output_root / plan.identifier).resolve()}")
    print(f"valid existing seeds: {len(audit['valid'])}/{config.seeds}: "
          f"{audit['valid'] or 'none'}")
    print(f"estimated model runs required: {len(audit['pending'])}")
    for item in audit["details"]:
        if item["identifier"] in audit["valid"]:
            continue
        print(f"  {item['identifier']}: {item['reason']} ({item['path']})")
    print("No wall-clock estimate is printed without completed manifests.")


def execute_campaign(config: ValidationConfig,
                     simulation_factory: Callable[..., Any] | None = None) \
        -> dict[str, Any]:
    """Execute only pending seeds. Caller must enforce explicit permission."""
    config.output_root.mkdir(parents=True, exist_ok=True)
    provenance = code_provenance(Path(__file__).resolve().parents[1])
    initial = inspect_campaign(config)
    reused = list(initial["valid"])
    quarantined, failures, newly_run = [], [], []
    rejected_ids = {item["identifier"] for item in initial["rejected"]}
    failure_path = config.output_root / "failures.json"
    for plan in config.plans():
        if plan.identifier in reused:
            continue
        seed_started_utc = utc_now()
        seed_started = time.perf_counter()
        try:
            if plan.identifier in rejected_ids:
                destination = _quarantine_invalid(
                    config.output_root, plan.identifier)
                quarantined.append({
                    "identifier": plan.identifier,
                    "destination": str(destination.resolve())
                    if destination else None,
                })
            run_seed(config, plan, config.output_root, provenance,
                     simulation_factory=simulation_factory)
            newly_run.append(plan.identifier)
        except Exception as error:
            failure = {
                **expected_identity(config, plan),
                "identifier": plan.identifier,
                "status": "failed",
                "notice": NOTICE,
                "code_provenance": dict(provenance),
                "started_utc": seed_started_utc,
                "failed_utc": utc_now(),
                "elapsed_seconds": time.perf_counter() - seed_started,
                "error": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc(),
            }
            failures.append(failure)
            atomic_json(config.output_root / "failures" /
                        f"{plan.identifier}.json", failure)
            atomic_json(failure_path, {
                "updated_utc": utc_now(), "failures": failures})
    final = inspect_campaign(config)
    aggregate = build_aggregate_manifest(
        config, final, reused, newly_run, quarantined, failures, provenance)
    # Preserve the pre-execution rejection reasons even after invalid
    # directories have been quarantined and replaced by valid outputs.
    aggregate["rejected"] = list(initial["rejected"])
    atomic_json(config.output_root / "aggregate_manifest.json", aggregate)
    if final["valid"] and config.horizon - config.burn_in >= 50:
        from market_sim.financial_validation import (
            diagnose_campaign, write_campaign_artifacts,
        )
        diagnostics = diagnose_campaign(config.output_root)
        write_campaign_artifacts(
            diagnostics, config.output_root / "diagnostics")
    return aggregate


def parse_seed_list(value: str | None) -> tuple[int, ...] | None:
    if value is None:
        return None
    seeds = tuple(int(item.strip()) for item in value.split(",")
                  if item.strip())
    if not seeds:
        raise argparse.ArgumentTypeError("--seed-list cannot be empty")
    return seeds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root",
                        default="results/financial_validation/pilot_5seeds")
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--seed-list")
    parser.add_argument("--horizon", type=int, default=10_000)
    parser.add_argument("--burn-in", type=int, default=2_000)
    parser.add_argument("--regime", default="current_eu_supervision")
    parser.add_argument("--num-traders", type=int, default=30)
    parser.add_argument("--market-seed-base", type=int, default=20_260_716)
    parser.add_argument("--supervision-seed-base", type=int, default=104_729)
    parser.add_argument("--write-order-book-events", action="store_true")
    parser.add_argument("--safety-factor", type=float, default=1.25)
    parser.add_argument(
        "--execute-missing", action="store_true",
        help="Explicitly permit only the missing/invalid seeds in preflight")
    return parser


def config_from_args(args: argparse.Namespace) -> ValidationConfig:
    explicit_seeds = parse_seed_list(args.seed_list)
    return ValidationConfig(
        output_root=Path(args.output_root).resolve(),
        seeds=len(explicit_seeds) if explicit_seeds is not None else args.seeds,
        seed_list=explicit_seeds, horizon=args.horizon,
        burn_in=args.burn_in, regime=args.regime,
        num_traders=args.num_traders,
        market_seed_base=args.market_seed_base,
        supervision_seed_base=args.supervision_seed_base,
        write_order_book_events=args.write_order_book_events,
        safety_factor=args.safety_factor)


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = config_from_args(args)
    config.validate()
    audit = inspect_campaign(config)
    print_preflight(config, audit)
    if not args.execute_missing:
        print("EXECUTION BLOCKED: dry run only; no directory or simulation "
              "was created. Review the list, then add --execute-missing.")
        return
    aggregate = execute_campaign(config)
    print(f"execution complete: {len(aggregate['valid'])}/{config.seeds} "
          "valid seed outputs; pending="
          f"{aggregate['pending'] or 'none'}")
