"""Stylized-facts diagnostics for saved financial-market paths.

This module never runs the agent-based model.  It reads a previously saved
CSV path, records its content hash, and evaluates transparent diagnostics for
fat tails, linear return autocorrelation, and volatility clustering.  The CLI
prints results by default and writes artifacts only with ``--write``.

The classifications are diagnostic rules, not hypothesis-free proof that the
model is empirically validated.  A single detached path is explicitly labelled
illustrative.  A completed validation-campaign directory can also be consumed;
cross-path summaries then use independent seeds rather than pooled returns.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_LAGS = (1, 2, 5, 10, 20)


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _acf(values: Sequence[float], lag: int) -> float:
    if lag <= 0 or lag >= len(values):
        raise ValueError("lag must lie between one and n-1")
    centre = _mean(values)
    denominator = sum((value - centre) ** 2 for value in values)
    if denominator == 0:
        return 0.0
    return sum(
        (values[index] - centre) * (values[index - lag] - centre)
        for index in range(lag, len(values))
    ) / denominator


def _regularized_gamma_q(shape: float, value: float) -> float:
    """Regularized upper incomplete gamma for chi-square survival values."""
    if shape <= 0 or value < 0:
        raise ValueError("invalid gamma arguments")
    if value == 0:
        return 1.0
    epsilon, tiny, maximum_iterations = 3e-14, 1e-300, 1000
    log_term = -value + shape * math.log(value) - math.lgamma(shape)
    if value < shape + 1.0:
        term = total = 1.0 / shape
        current = shape
        for _ in range(maximum_iterations):
            current += 1.0
            term *= value / current
            total += term
            if abs(term) < abs(total) * epsilon:
                break
        lower = total * math.exp(log_term)
        return min(1.0, max(0.0, 1.0 - lower))
    b = value + 1.0 - shape
    c = 1.0 / tiny
    d = 1.0 / b
    fraction = d
    for iteration in range(1, maximum_iterations + 1):
        coefficient = -iteration * (iteration - shape)
        b += 2.0
        d = coefficient * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + coefficient / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        fraction *= delta
        if abs(delta - 1.0) < epsilon:
            break
    return min(1.0, max(0.0, math.exp(log_term) * fraction))


def _ljung_box(values: Sequence[float], maximum_lag: int) -> dict[str, float]:
    n = len(values)
    maximum_lag = min(maximum_lag, n - 1)
    statistic = n * (n + 2.0) * sum(
        _acf(values, lag) ** 2 / (n - lag)
        for lag in range(1, maximum_lag + 1)
    )
    p_value = _regularized_gamma_q(maximum_lag / 2.0, statistic / 2.0)
    return {"lag": maximum_lag, "statistic": statistic, "p_value": p_value}


def _hill_tail_index(values: Iterable[float]) -> dict[str, float | int | None]:
    ordered = sorted(abs(value) for value in values if value != 0.0)
    if len(ordered) < 25:
        return {"k": 0, "threshold": None, "alpha": None}
    k = max(10, int(math.sqrt(len(ordered))))
    k = min(k, len(ordered) - 1)
    threshold = ordered[-k - 1]
    denominator = sum(math.log(value / threshold) for value in ordered[-k:]
                      if value > threshold)
    alpha = k / denominator if denominator > 0 else None
    return {"k": k, "threshold": threshold, "alpha": alpha}


def _moments(values: Sequence[float]) -> dict[str, float]:
    n = len(values)
    centre = _mean(values)
    second = sum((value - centre) ** 2 for value in values) / n
    third = sum((value - centre) ** 3 for value in values) / n
    fourth = sum((value - centre) ** 4 for value in values) / n
    standard_deviation = math.sqrt(second)
    skewness = third / second ** 1.5 if second else 0.0
    excess_kurtosis = fourth / second ** 2 - 3.0 if second else 0.0
    jarque_bera = n / 6.0 * (skewness ** 2 + excess_kurtosis ** 2 / 4.0)
    # A chi-square with two degrees of freedom has survival exp(-x/2).
    return {
        "mean": centre,
        "standard_deviation": standard_deviation,
        "skewness": skewness,
        "excess_kurtosis": excess_kurtosis,
        "jarque_bera": jarque_bera,
        "jarque_bera_p_value": math.exp(-jarque_bera / 2.0),
    }


def _status(condition: bool, partial: bool = False) -> str:
    return "reproduced" if condition else ("partially reproduced" if partial
                                            else "not reproduced")


def diagnose_prices(prices: Sequence[float], source: str = "in-memory") -> dict[str, Any]:
    if len(prices) < 50 or any(price <= 0 for price in prices):
        raise ValueError("at least 50 strictly positive prices are required")
    calendar_returns = [
        math.log(prices[index] / prices[index - 1])
        for index in range(1, len(prices))
    ]
    active_returns = [value for value in calendar_returns if value != 0.0]
    if len(active_returns) < 40:
        raise ValueError("too few non-zero price changes for diagnostics")
    moments = _moments(active_returns)
    tail = _hill_tail_index(active_returns)
    band = 1.96 / math.sqrt(len(active_returns))
    usable_lags = [lag for lag in DEFAULT_LAGS if lag < len(active_returns)]
    return_acf = {str(lag): _acf(active_returns, lag) for lag in usable_lags}
    absolute = [abs(value) for value in active_returns]
    squared = [value * value for value in active_returns]
    absolute_acf = {str(lag): _acf(absolute, lag) for lag in usable_lags}
    squared_acf = {str(lag): _acf(squared, lag) for lag in usable_lags}
    fat_tail_full = (
        moments["excess_kurtosis"] > 3.0
        and moments["jarque_bera_p_value"] < 0.05
        and tail["alpha"] is not None
        and 2.0 <= float(tail["alpha"]) <= 5.0
    )
    fat_tail_partial = (
        moments["excess_kurtosis"] > 0.0
        and moments["jarque_bera_p_value"] < 0.05
    )
    maximum_linear = max(abs(value) for value in return_acf.values())
    linear_full = maximum_linear <= band
    linear_partial = not linear_full and maximum_linear < 0.15
    clustering_significant = sum(
        absolute_acf[str(lag)] > band or squared_acf[str(lag)] > band
        for lag in (1, 5, 10, 20) if str(lag) in absolute_acf
    )
    clustering_full = clustering_significant >= 3
    clustering_partial = clustering_significant >= 1
    classifications = {
        "fat_tailed_returns": {
            "status": _status(fat_tail_full, fat_tail_partial),
            "rule": ("reproduced when excess kurtosis > 3, Jarque-Bera "
                     "p < 0.05, and absolute-return Hill alpha is 2-5"),
        },
        "weak_linear_return_autocorrelation": {
            "status": _status(linear_full, linear_partial),
            "rule": ("reproduced when all reported return ACF magnitudes "
                     "are within the approximate 95% white-noise band; "
                     "partial when the maximum is below 0.15"),
        },
        "volatility_clustering": {
            "status": _status(clustering_full, clustering_partial),
            "rule": ("reproduced when absolute or squared-return ACF is "
                     "positive beyond the 95% band at >=3 of lags 1,5,10,20; "
                     "partial at >=1 lag"),
        },
    }
    return {
        "source": source,
        "price_observations": len(prices),
        "calendar_log_returns": len(calendar_returns),
        "active_price_change_returns": len(active_returns),
        "zero_calendar_return_fraction":
            sum(value == 0.0 for value in calendar_returns)
            / len(calendar_returns),
        "return_filter": (
            "Primary diagnostics omit exactly zero calendar-day changes to "
            "avoid treating inactive/weekend rows as trading observations."
        ),
        "approximate_acf_95_band": band,
        "moments": moments,
        "absolute_return_hill_tail": tail,
        "return_acf": return_acf,
        "absolute_return_acf": absolute_acf,
        "squared_return_acf": squared_acf,
        "ljung_box_returns_lag20": _ljung_box(active_returns, 20),
        "ljung_box_squared_returns_lag20": _ljung_box(squared, 20),
        "classifications": classifications,
        "limitations": [
            "This is one saved path, not a distribution across independent seeds.",
            "The CSV has no attached simulation manifest, so configuration and seed provenance are unverified.",
            "The file contains daily price but no order-level spread, depth, cancellation, or volume series; those microstructure facts are pending.",
            "Diagnostic thresholds are transparent decision rules, not empirical calibration targets.",
        ],
    }


def diagnose_csv(path: Path, price_column: str = "asset_price") -> tuple[dict[str, Any], list[float]]:
    raw = path.read_bytes()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    try:
        prices = [float(row[price_column]) for row in rows]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid price column {price_column!r}") from error
    result = diagnose_prices(prices, source=str(path.resolve()))
    result["source_sha256"] = hashlib.sha256(raw).hexdigest()
    result["source_bytes"] = len(raw)
    result["price_column"] = price_column
    result["provenance_status"] = "detached: no matching seed/config manifest supplied"
    return result, prices


def _optional_float(row: dict[str, str], key: str) -> float | None:
    value = row.get(key, "")
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _correlation(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 3:
        return None
    mean_left, mean_right = _mean(left), _mean(right)
    numerator = sum((x - mean_left) * (y - mean_right)
                    for x, y in zip(left, right))
    denominator = math.sqrt(
        sum((x - mean_left) ** 2 for x in left)
        * sum((y - mean_right) ** 2 for y in right))
    return numerator / denominator if denominator else None


def _micro_status(full: bool, partial: bool, available: bool = True) -> str:
    if not available:
        return "pending"
    return _status(full, partial)


def diagnose_microstructure(events_path: Path | None,
                            daily_path: Path) -> dict[str, Any]:
    """Transparent seed-level diagnostics; unavailable fields stay pending."""
    with daily_path.open(newline="", encoding="utf-8-sig") as handle:
        daily_rows = list(csv.DictReader(handle))
    volumes, volatilities = [], []
    for row in daily_rows:
        volume = _optional_float(row, "volume")
        volatility = _optional_float(row, "realized_volatility")
        if volume is not None and volatility is not None:
            volumes.append(volume)
            volatilities.append(volatility)
    volume_volatility = _correlation(volumes, volatilities)
    if events_path is None or not events_path.is_file():
        pending = {
            name: {
                "status": "pending",
                "rule": "pending because order-book event output is unavailable",
            }
            for name in (
                "positive_spread_and_depth", "cancellation_activity",
                "trade_sign_persistence", "positive_price_impact",
            )
        }
        pending["positive_volume_volatility_relation"] = {
            "status": _micro_status(
                volume_volatility is not None and volume_volatility > .10,
                volume_volatility is not None and volume_volatility > 0,
                volume_volatility is not None),
            "rule": "reproduced when daily volume-volatility correlation > 0.10; partial when positive",
        }
        return {
            "event_records": 0,
            "metrics": {"volume_volatility_correlation": volume_volatility},
            "classifications": pending,
            "limitations": ["Order-book event output was disabled or missing."],
        }
    with events_path.open(newline="", encoding="utf-8-sig") as handle:
        event_rows = list(csv.DictReader(handle))
    submissions = sum(row.get("event_type") == "order_submission"
                      for row in event_rows)
    cancellations = sum(row.get("event_type") == "cancellation"
                        for row in event_rows)
    trades = [row for row in event_rows if row.get("event_type") == "trade"]
    state_rows = [row for row in event_rows
                  if row.get("event_type") in ("trade", "cancellation")]
    spreads = [value for row in state_rows
               if (value := _optional_float(row, "spread")) is not None]
    bid_depth = [value for row in state_rows
                 if (value := _optional_float(row, "bid_depth")) is not None]
    ask_depth = [value for row in state_rows
                 if (value := _optional_float(row, "ask_depth")) is not None]
    signs = [value for row in trades
             if (value := _optional_float(row, "trade_sign")) is not None]
    sign_acf = _acf(signs, 1) if len(signs) >= 3 else None
    impacts, impact_volumes = [], []
    for row in trades:
        before = _optional_float(row, "mid_price_before")
        after = _optional_float(row, "mid_price")
        volume = _optional_float(row, "trade_volume")
        if before and after is not None and volume is not None:
            impacts.append(abs(after - before) / before)
            impact_volumes.append(math.log1p(max(0.0, volume)))
    impact_correlation = _correlation(impact_volumes, impacts)
    positive_spread_fraction = (
        sum(value > 0 for value in spreads) / len(spreads) if spreads else None)
    positive_depth_fraction = (
        sum(b > 0 and a > 0 for b, a in zip(bid_depth, ask_depth))
        / min(len(bid_depth), len(ask_depth))
        if bid_depth and ask_depth else None)
    sign_band = 1.96 / math.sqrt(len(signs)) if signs else None
    classifications = {
        "positive_spread_and_depth": {
            "status": _micro_status(
                positive_spread_fraction is not None
                and positive_depth_fraction is not None
                and positive_spread_fraction >= .95
                and positive_depth_fraction >= .95,
                positive_spread_fraction is not None
                and positive_depth_fraction is not None
                and positive_spread_fraction >= .50
                and positive_depth_fraction >= .50,
                bool(spreads and bid_depth and ask_depth)),
            "rule": "reproduced when >=95% of observed snapshots have positive spread and two-sided depth; partial at >=50%",
        },
        "cancellation_activity": {
            "status": _micro_status(cancellations > 0 and submissions > 0,
                                    submissions > 0, submissions > 0),
            "rule": "reproduced when submissions and cancellations are both observed; partial when only submissions are observed",
        },
        "trade_sign_persistence": {
            "status": _micro_status(
                sign_acf is not None and sign_band is not None
                and sign_acf > sign_band,
                sign_acf is not None and sign_acf > 0,
                sign_acf is not None),
            "rule": "reproduced when lag-1 trade-sign ACF exceeds the approximate 95% white-noise band; partial when positive",
        },
        "positive_price_impact": {
            "status": _micro_status(
                impact_correlation is not None and impact_correlation > .10,
                impact_correlation is not None and impact_correlation > 0,
                impact_correlation is not None),
            "rule": "reproduced when log-volume and absolute immediate mid-price movement correlation >0.10; partial when positive",
        },
        "positive_volume_volatility_relation": {
            "status": _micro_status(
                volume_volatility is not None and volume_volatility > .10,
                volume_volatility is not None and volume_volatility > 0,
                volume_volatility is not None),
            "rule": "reproduced when daily volume-volatility correlation >0.10; partial when positive",
        },
    }
    return {
        "event_records": len(event_rows),
        "metrics": {
            "submissions": submissions,
            "cancellations": cancellations,
            "trades": len(trades),
            "cancellation_submission_ratio":
                cancellations / submissions if submissions else None,
            "mean_spread": _mean(spreads) if spreads else None,
            "median_spread": statistics.median(spreads) if spreads else None,
            "mean_bid_depth": _mean(bid_depth) if bid_depth else None,
            "mean_ask_depth": _mean(ask_depth) if ask_depth else None,
            "trade_sign_acf_lag1": sign_acf,
            "approximate_trade_sign_acf_95_band": sign_band,
            "log_volume_immediate_price_impact_correlation":
                impact_correlation,
            "volume_volatility_correlation": volume_volatility,
        },
        "classifications": classifications,
        "limitations": [
            "Price impact is immediate mid-price movement, not a long-horizon causal response.",
            "Thresholds are transparent diagnostic rules, not empirical calibration targets.",
        ],
    }


def _valid_manifest_seed(seed_dir: Path) -> tuple[bool, str, dict[str, Any] | None]:
    manifest_path = seed_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return False, f"invalid manifest: {error}", None
    if manifest.get("status") != "complete":
        return False, "seed is not complete", manifest
    if manifest.get("manifest_schema") != "financial-validation-seed/v1":
        return False, "unsupported seed manifest schema", manifest
    exports = manifest.get("exports", {})
    for name, required, columns in (
            ("daily_market", True,
             {"day", "asset_price", "log_return", "volume",
              "realized_volatility"}),
            ("order_book_events", False,
             {"timestamp", "day", "event_type", "spread", "bid_depth",
              "ask_depth", "trade_volume", "trade_sign"})):
        metadata = exports.get(name, {})
        if not metadata.get("enabled"):
            if required:
                return False, f"required export disabled: {name}", manifest
            continue
        path = seed_dir / str(metadata.get("filename", ""))
        if (not path.is_file() or path.stat().st_size != metadata.get("bytes")
                or _sha256_file(path) != metadata.get("sha256")):
            return False, f"export integrity failure: {name}", manifest
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle)
            header = next(reader, [])
            records = sum(1 for _ in reader)
        if not columns.issubset(header):
            return False, f"required columns missing: {name}", manifest
        if records != metadata.get("records"):
            return False, f"record count mismatch: {name}", manifest
    return True, "valid", manifest


def _aggregate_status(statuses: Sequence[str]) -> str:
    available = [status for status in statuses if status != "pending"]
    if not available:
        return "pending"
    reproduced = sum(status == "reproduced" for status in available)
    supportive = sum(status in ("reproduced", "partially reproduced")
                     for status in available)
    if reproduced / len(available) >= .80:
        return "reproduced"
    if supportive / len(available) >= .50:
        return "partially reproduced"
    return "not reproduced"


def _seed_metric_summary(values: Sequence[float]) -> dict[str, float | int]:
    n = len(values)
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if n > 1 else 0.0
    return {
        "n_seeds": n,
        "mean": mean,
        "sd_across_seeds": sd,
        "ci95_halfwidth_across_seeds": 1.96 * sd / math.sqrt(n)
        if n > 1 else 0.0,
    }


def diagnose_campaign(campaign_root: Path) -> dict[str, Any]:
    """Aggregate valid seed diagnostics without pooling return observations."""
    per_seed, rejected = {}, []
    for seed_dir in sorted(campaign_root.glob("seed_*")):
        valid, reason, manifest = _valid_manifest_seed(seed_dir)
        if not valid:
            rejected.append({"seed": seed_dir.name, "reason": reason})
            continue
        daily = seed_dir / manifest["exports"]["daily_market"]["filename"]
        event_meta = manifest["exports"].get("order_book_events", {})
        events = (seed_dir / event_meta["filename"]
                  if event_meta.get("enabled") else None)
        price_result, _ = diagnose_csv(daily)
        price_result["provenance_status"] = "attached and hash-verified seed manifest"
        micro = diagnose_microstructure(events, daily)
        classifications = {
            **price_result["classifications"],
            **micro["classifications"],
        }
        per_seed[seed_dir.name] = {
            "market_seed": manifest.get("market_seed"),
            "supervision_seed": manifest.get("supervision_seed"),
            "financial_path": price_result,
            "microstructure": micro,
            "classifications": classifications,
        }
    names = sorted({name for seed in per_seed.values()
                    for name in seed["classifications"]})
    aggregate_classifications = {}
    for name in names:
        statuses = [seed["classifications"][name]["status"]
                    for seed in per_seed.values()
                    if name in seed["classifications"]]
        aggregate_classifications[name] = {
            "status": _aggregate_status(statuses),
            "seed_status_counts": {
                status: statuses.count(status) for status in (
                    "reproduced", "partially reproduced", "not reproduced",
                    "pending")
            },
            "unit_of_inference": "independent seed",
        }
    metric_values: dict[str, list[float]] = {}
    for seed in per_seed.values():
        path = seed["financial_path"]
        micro = seed["microstructure"]["metrics"]
        candidates = {
            "excess_kurtosis": path["moments"].get("excess_kurtosis"),
            "hill_tail_alpha":
                path["absolute_return_hill_tail"].get("alpha"),
            "return_acf_lag1": path["return_acf"].get("1"),
            "absolute_return_acf_lag1":
                path["absolute_return_acf"].get("1"),
            "squared_return_acf_lag1":
                path["squared_return_acf"].get("1"),
            **micro,
        }
        for name, value in candidates.items():
            if isinstance(value, (int, float)) and math.isfinite(value):
                metric_values.setdefault(name, []).append(float(value))
    aggregate_seed_metrics = {
        name: _seed_metric_summary(values)
        for name, values in sorted(metric_values.items()) if values
    }
    return {
        "notice": "Simulation-based stylized-facts diagnostics; not empirical calibration or forecasting.",
        "campaign_root": str(campaign_root.resolve()),
        "valid_seed_count": len(per_seed),
        "rejected_seeds": rejected,
        "unit_of_cross_seed_inference": "seed; returns are never pooled across paths",
        "aggregate_classifications": aggregate_classifications,
        "aggregate_seed_metrics": aggregate_seed_metrics,
        "per_seed": per_seed,
        "limitations": [
            "Seed-level support frequencies are descriptive, not empirical confidence levels.",
            "Diagnostic thresholds are predeclared rules rather than calibrated targets.",
        ],
    }


def write_campaign_artifacts(result: dict[str, Any], output_dir: Path) -> None:
    _atomic_text(output_dir / "multi_seed_financial_validation.json",
                 json.dumps(result, indent=2, sort_keys=True))
    temporary = output_dir / "multi_seed_financial_validation.csv.tmp"
    output_dir.mkdir(parents=True, exist_ok=True)
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=("diagnostic", "status", "valid_seeds",
                                "seed_status_counts"))
        writer.writeheader()
        for name, detail in result["aggregate_classifications"].items():
            writer.writerow({
                "diagnostic": name, "status": detail["status"],
                "valid_seeds": result["valid_seed_count"],
                "seed_status_counts": json.dumps(
                    detail["seed_status_counts"], sort_keys=True),
            })
    os.replace(temporary, output_dir / "multi_seed_financial_validation.csv")


def _svg_frame(title: str, body: str, width: int = 900,
               height: int = 520) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}">'
            '<rect width="100%" height="100%" fill="white"/>'
            f'<text x="55" y="35" font-family="sans-serif" font-size="20" '
            f'font-weight="bold">{title}</text>{body}'
            '<text x="55" y="505" font-family="sans-serif" font-size="11" '
            'fill="#555">Existing saved path; simulation result, not empirical data.</text>'
            '</svg>')


def _histogram_svg(returns: Sequence[float]) -> str:
    values = sorted(returns)
    low, high = values[max(0, int(.005 * len(values)))], values[min(
        len(values) - 1, int(.995 * len(values)))]
    bins = 40
    width = (high - low) / bins or 1.0
    counts = [0] * bins
    for value in values:
        if low <= value <= high:
            index = min(bins - 1, int((value - low) / width))
            counts[index] += 1
    maximum = max(counts) or 1
    parts = ['<line x1="70" y1="450" x2="850" y2="450" stroke="#333"/>']
    for index, count in enumerate(counts):
        x = 70 + index * 780 / bins
        bar_height = 360 * count / maximum
        parts.append(f'<rect x="{x:.2f}" y="{450-bar_height:.2f}" '
                     f'width="{780/bins-1:.2f}" height="{bar_height:.2f}" '
                     'fill="#4c78a8" opacity="0.85"/>')
    parts.append(f'<text x="70" y="475" font-family="sans-serif" font-size="12">{low:.3f}</text>')
    parts.append(f'<text x="810" y="475" font-family="sans-serif" font-size="12">{high:.3f}</text>')
    return _svg_frame("Active-change log-return distribution", "".join(parts))


def _acf_svg(result: dict[str, Any], volatility: bool) -> str:
    series = ([('absolute returns', result['absolute_return_acf'], '#f58518'),
               ('squared returns', result['squared_return_acf'], '#54a24b')]
              if volatility else
              [('returns', result['return_acf'], '#4c78a8')])
    lags = [int(key) for key in next(iter(series))[1]]
    maximum = max(.1, max(abs(value) for _, values, _ in series
                           for value in values.values()))
    parts = ['<line x1="70" y1="270" x2="850" y2="270" stroke="#333"/>']
    band = result['approximate_acf_95_band']
    for sign in (-1, 1):
        y = 270 - sign * band / maximum * 190
        parts.append(f'<line x1="70" y1="{y:.2f}" x2="850" y2="{y:.2f}" '
                     'stroke="#999" stroke-dasharray="5,4"/>')
    group_width = 700 / len(lags)
    bar_width = min(35, group_width / (len(series) + 1))
    for series_index, (label, values, color) in enumerate(series):
        for index, lag in enumerate(lags):
            value = values[str(lag)]
            height = value / maximum * 190
            x = 105 + index * group_width + series_index * bar_width
            y = 270 - max(height, 0)
            parts.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width-2:.2f}" '
                         f'height="{abs(height):.2f}" fill="{color}"/>')
            if series_index == 0:
                parts.append(f'<text x="{x:.2f}" y="475" font-family="sans-serif" '
                             f'font-size="12">{lag}</text>')
        parts.append(f'<text x="{630+series_index*120}" y="65" '
                     f'font-family="sans-serif" font-size="12" fill="{color}">{label}</text>')
    title = "Volatility-proxy autocorrelation" if volatility else "Linear return autocorrelation"
    return _svg_frame(title, "".join(parts))


def write_artifacts(result: dict[str, Any], prices: Sequence[float],
                    output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_text(output_dir / "financial_stylized_facts.json",
                 json.dumps(result, indent=2, sort_keys=True))
    rows = [
        {"diagnostic": name, "status": value["status"], "rule": value["rule"]}
        for name, value in result["classifications"].items()
    ]
    temporary = output_dir / "financial_stylized_facts.csv.tmp"
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("diagnostic", "status", "rule"))
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, output_dir / "financial_stylized_facts.csv")
    calendar_returns = [math.log(prices[i] / prices[i - 1])
                        for i in range(1, len(prices))]
    active_returns = [value for value in calendar_returns if value != 0.0]
    _atomic_text(output_dir / "fig_financial_return_distribution.svg",
                 _histogram_svg(active_returns))
    _atomic_text(output_dir / "fig_financial_return_acf.svg",
                 _acf_svg(result, volatility=False))
    _atomic_text(output_dir / "fig_financial_volatility_acf.svg",
                 _acf_svg(result, volatility=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="simulation_results.csv")
    parser.add_argument("--price-column", default="asset_price")
    parser.add_argument("--output-dir", default="results/validation")
    parser.add_argument("--campaign-root",
                        help="Aggregate a completed seed campaign instead of one CSV")
    parser.add_argument("--write", action="store_true",
                        help="Write JSON, CSV, and SVG diagnostics")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.campaign_root:
        result = diagnose_campaign(Path(args.campaign_root))
        for name, detail in result["aggregate_classifications"].items():
            print(f"{name}: {detail['status']}")
        print(f"valid independent seeds: {result['valid_seed_count']}")
        print("No simulation was executed; diagnostics use completed seed outputs only.")
        if args.write:
            write_campaign_artifacts(result, Path(args.output_dir))
        return
    result, prices = diagnose_csv(Path(args.input), args.price_column)
    for name, detail in result["classifications"].items():
        print(f"{name}: {detail['status']}")
    print("No simulation was executed; diagnostics use the existing CSV only.")
    if args.write:
        write_artifacts(result, prices, Path(args.output_dir))


if __name__ == "__main__":
    main()
