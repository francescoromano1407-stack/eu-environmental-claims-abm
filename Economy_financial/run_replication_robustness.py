"""Paired-replication robustness extension for selected LHS configurations.

The default invocation is a read-only dry run.  It validates the authoritative
three-replication draws, deterministically selects a representative cross-
horizon subset, and prints every missing extension file.  Only
``--execute-missing`` permits the additional replications to run.

Extension outputs are separate from the global campaign.  Existing three-
replication JSON files are never modified or recomputed.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from market_sim.policy_comparison import (DEFAULT_WEIGHT_SCENARIOS,
                                          composite_scores)
from market_sim.sensitivity_campaign import (
    CampaignConfig, DEFAULT_REGIMES, HEADLINE_HIGHER, HEADLINE_METRICS,
    latin_hypercube_design, run_replication_rows, validate_draw_payload,
)


NOTICE = "Simulation-based robustness extension; not an empirical forecast."
HORIZONS = (
    (120, "horizon_120d"),
    (365, "robustness_365d"),
    (1000, "robustness_1000d"),
    (2000, "robustness_2000d"),
)


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
    os.replace(temporary, path)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def _raw_config(results_root: Path, days: int, label: str) -> CampaignConfig:
    raw_dir = results_root / "raw" / label
    manifest = _load_json(raw_dir / "manifest.json")
    prior = manifest.get("config")
    if not isinstance(prior, dict):
        raise ValueError(f"{raw_dir} has no campaign config")
    config = CampaignConfig(
        outdir=str(raw_dir), draws=int(prior["draws"]),
        replications=int(prior["replications"]), horizon_days=days,
        master_seed=int(prior["master_seed"]),
        supervision_base_seed=int(prior["supervision_base_seed"]),
        regimes=tuple(prior["regimes"]),
        num_traders=int(prior.get("num_traders", 8)),
        num_manipulators=int(prior.get("num_manipulators", 0)),
        enable_credit=bool(prior.get("enable_credit", False)),
        label=label,
    )
    if config.replications != 3:
        raise ValueError(
            f"expected authoritative three-replication base at {raw_dir}")
    if config.regimes != DEFAULT_REGIMES:
        raise ValueError(f"unexpected regime order in {raw_dir}")
    return config


def _load_base_draw(config: CampaignConfig, draw: int,
                    sample: Mapping[str, float]) -> dict[str, Any]:
    path = Path(config.outdir) / f"draw_{draw:04d}.json"
    try:
        payload = _load_json(path)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"invalid base draw {path}: {error}") from error
    valid, reason = validate_draw_payload(payload, config, draw, sample)
    if not valid:
        raise ValueError(f"invalid base draw {path}: {reason}")
    return payload


def _selection_features(results_root: Path) -> dict[int, list[float]]:
    features = {draw: [] for draw in range(200)}
    regime_code = {regime: index for index, regime in enumerate(DEFAULT_REGIMES)}
    for _, label in HORIZONS:
        summary = _load_json(results_root / "summaries" / f"{label}_summary.json")
        if summary.get("draws_summarized") != 200:
            raise ValueError(f"{label} summary does not contain all 200 draws")
        for item in summary["per_draw"]:
            draw = int(item["draw"])
            contrasts = item["contrasts"]
            features[draw].extend([
                contrasts["exposure_weighted_severity"][DEFAULT_REGIMES[1]],
                contrasts["exposure_weighted_severity"][DEFAULT_REGIMES[2]],
                contrasts["mean_greenhushing_gap"][DEFAULT_REGIMES[1]],
                contrasts["mean_greenhushing_gap"][DEFAULT_REGIMES[2]],
                float(regime_code[item["winners"]["default_experiment"]]),
            ])
    return features


def select_representative_draws(results_root: Path,
                                subset_size: int) -> list[int]:
    """Deterministic maximin coverage in standardized result space."""
    if not 3 <= subset_size <= 40:
        raise ValueError("subset size must lie between 3 and 40")
    raw = _selection_features(results_root)
    columns = list(zip(*(raw[draw] for draw in sorted(raw))))
    means = [statistics.fmean(column) for column in columns]
    scales = [statistics.pstdev(column) or 1.0 for column in columns]
    standardized = {
        draw: tuple((value - means[index]) / scales[index]
                    for index, value in enumerate(values))
        for draw, values in raw.items()
    }

    def squared_distance(left: Sequence[float], right: Sequence[float]) -> float:
        return sum((a - b) ** 2 for a, b in zip(left, right))

    origin = (0.0,) * len(means)
    first = max(standardized, key=lambda draw: (
        squared_distance(standardized[draw], origin), -draw))
    selected = [first]
    while len(selected) < subset_size:
        remaining = (draw for draw in standardized if draw not in selected)
        chosen = max(remaining, key=lambda draw: (
            min(squared_distance(standardized[draw], standardized[prior])
                for prior in selected), -draw))
        selected.append(chosen)
    return sorted(selected)


def _extension_reason(payload: Any, config: CampaignConfig, draw: int,
                      sample: Mapping[str, float], base_replications: int,
                      target_replications: int) -> str | None:
    if not isinstance(payload, dict) or payload.get("complete") is not True:
        return "not a completed extension object"
    expected_identity = {
        "draw": draw, "sample": dict(sample),
        "horizon_days": config.horizon_days,
        "base_replications": base_replications,
        "target_replications": target_replications,
        "regimes": list(config.regimes),
        "replication_indices": list(range(base_replications,
                                           target_replications)),
    }
    for key, expected in expected_identity.items():
        if payload.get(key) != expected:
            return f"{key} mismatch"
    rows = payload.get("rows")
    expected_rows = {
        (replication, regime): (
            config.market_seed(draw, replication),
            config.supervision_seed(draw, replication),
        )
        for replication in range(base_replications, target_replications)
        for regime in config.regimes
    }
    if not isinstance(rows, list) or len(rows) != len(expected_rows):
        return f"expected {len(expected_rows)} extension rows"
    observed = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("metrics"), dict):
            return "malformed extension row"
        key = (row.get("replication"), row.get("regime"))
        if key not in expected_rows or key in observed:
            return "unexpected or duplicate regime-replication row"
        if (row.get("market_seed"), row.get("supervision_seed")) \
                != expected_rows[key]:
            return "extension seed mismatch"
        try:
            if not all(math.isfinite(float(value))
                       for value in row["metrics"].values()):
                return "non-finite extension metric"
        except (TypeError, ValueError):
            return "non-numeric extension metric"
        observed.add(key)
    return None


def inspect_extensions(results_root: Path, extension_root: Path,
                       selected: Sequence[int], target_replications: int
                       ) -> dict[str, Any]:
    by_horizon = {}
    for days, label in HORIZONS:
        base = _raw_config(results_root, days, label)
        design = latin_hypercube_design(base.master_seed, base.draws)
        target_config = CampaignConfig(
            **{**base.__dict__, "outdir": str(extension_root / label),
               "replications": target_replications})
        valid, missing, invalid = [], [], []
        for draw in selected:
            _load_base_draw(base, draw, design[draw])
            path = extension_root / label / f"draw_{draw:04d}.json"
            if not path.is_file():
                missing.append({"draw": draw, "path": str(path),
                                "reason": "extension file is missing"})
                continue
            try:
                payload = _load_json(path)
                reason = _extension_reason(
                    payload, target_config, draw, design[draw],
                    base.replications, target_replications)
            except (OSError, json.JSONDecodeError, ValueError) as error:
                reason = f"unreadable or corrupt extension: {error}"
            if reason is None:
                valid.append(draw)
            else:
                invalid.append({"draw": draw, "path": str(path),
                                "reason": reason})
        by_horizon[label] = {
            "days": days, "valid_draws": valid,
            "missing_draws": missing, "invalid_draws": invalid,
        }
    return {
        "selected_draws": list(selected),
        "target_replications": target_replications,
        "horizons": by_horizon,
    }


_T95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
}


def _paired_interval(rows: Sequence[dict[str, Any]], metric: str,
                     baseline: str, policy: str,
                     higher_is_better: bool) -> dict[str, float]:
    replications = sorted({int(row["replication"]) for row in rows})
    differences = []
    for replication in replications:
        base = next(row for row in rows if row["regime"] == baseline
                    and row["replication"] == replication)
        treatment = next(row for row in rows if row["regime"] == policy
                         and row["replication"] == replication)
        left, right = float(base["metrics"][metric]), float(
            treatment["metrics"][metric])
        differences.append(right - left if higher_is_better else left - right)
    mean = statistics.fmean(differences)
    standard_error = (statistics.stdev(differences) / math.sqrt(len(differences))
                      if len(differences) > 1 else 0.0)
    critical = _T95.get(len(differences) - 1, 1.96)
    halfwidth = critical * standard_error
    return {"n": len(differences), "mean": mean,
            "ci95_low": mean - halfwidth,
            "ci95_high": mean + halfwidth,
            "ci95_halfwidth": halfwidth}


def _winner(rows: Sequence[dict[str, Any]], regimes: Sequence[str]) -> tuple[str, list[str]]:
    mean_metrics = {}
    for regime in regimes:
        samples = [row["metrics"] for row in rows if row["regime"] == regime]
        mean_metrics[regime] = {
            metric: statistics.fmean(sample[metric] for sample in samples)
            for metric in samples[0]
        }
    weights = next(weight for weight in DEFAULT_WEIGHT_SCENARIOS
                   if weight.name == "default_experiment")
    scores = composite_scores(mean_metrics, weights)
    ranking = sorted(scores, key=scores.get, reverse=True)
    return ranking[0], ranking


def summarize_extensions(results_root: Path, extension_root: Path,
                         selected: Sequence[int], target_replications: int
                         ) -> dict[str, Any]:
    intervals, rankings = [], []
    metrics = list(HEADLINE_METRICS + HEADLINE_HIGHER)
    for days, label in HORIZONS:
        base = _raw_config(results_root, days, label)
        design = latin_hypercube_design(base.master_seed, base.draws)
        for draw in selected:
            base_payload = _load_base_draw(base, draw, design[draw])
            extension = _load_json(
                extension_root / label / f"draw_{draw:04d}.json")
            combined = list(base_payload["rows"]) + list(extension["rows"])
            winner3, ranking3 = _winner(base_payload["rows"], base.regimes)
            winner_target, ranking_target = _winner(combined, base.regimes)
            rankings.append({
                "horizon_days": days, "draw": draw,
                "winner_3_replications": winner3,
                "winner_target_replications": winner_target,
                "ranking_3_replications": ranking3,
                "ranking_target_replications": ranking_target,
                "winner_stable": winner3 == winner_target,
                "full_ranking_stable": ranking3 == ranking_target,
            })
            for metric in metrics:
                for policy in base.regimes[1:]:
                    base_interval = _paired_interval(
                        base_payload["rows"], metric, base.regimes[0], policy,
                        metric in HEADLINE_HIGHER)
                    target_interval = _paired_interval(
                        combined, metric, base.regimes[0], policy,
                        metric in HEADLINE_HIGHER)
                    intervals.append({
                        "horizon_days": days, "draw": draw,
                        "metric": metric, "policy": policy,
                        "base": base_interval, "target": target_interval,
                        "halfwidth_ratio_target_to_base": (
                            target_interval["ci95_halfwidth"]
                            / base_interval["ci95_halfwidth"]
                            if base_interval["ci95_halfwidth"] else None),
                    })
    return {
        "created_utc": _utc_now(), "notice": NOTICE,
        "selected_draws": list(selected),
        "base_replications": 3,
        "target_replications": target_replications,
        "paired_intervals": intervals,
        "ranking_stability": rankings,
        "winner_stability_fraction": statistics.fmean(
            item["winner_stable"] for item in rankings),
        "full_ranking_stability_fraction": statistics.fmean(
            item["full_ranking_stable"] for item in rankings),
    }


def _write_rankings_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    fields = ("horizon_days", "draw", "winner_3_replications",
              "winner_target_replications", "winner_stable",
              "full_ranking_stable")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in fields})
    os.replace(temporary, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", default="results")
    parser.add_argument("--output-root",
                        default="results/replication_robustness")
    parser.add_argument("--subset-size", type=int, default=12)
    parser.add_argument("--target-replications", type=int, default=15)
    parser.add_argument("--execute-missing", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if not 10 <= args.target_replications <= 20:
        raise ValueError("target replications must lie between 10 and 20")
    results_root = Path(args.results_root).resolve()
    extension_root = Path(args.output_root).resolve()
    selected = select_representative_draws(results_root, args.subset_size)
    audit = inspect_extensions(
        results_root, extension_root, selected, args.target_replications)
    print("representative LHS draws: " + ",".join(map(str, selected)))
    for _, label in HORIZONS:
        horizon = audit["horizons"][label]
        pending = horizon["missing_draws"] + horizon["invalid_draws"]
        print(f"[{horizon['days']} days] valid extensions: "
              f"{len(horizon['valid_draws'])}/{len(selected)}")
        for item in pending:
            print(f"  draw_{item['draw']:04d}: {item['reason']} ({item['path']})")
        if not pending:
            print("  missing/invalid extensions: none")
    if not args.execute_missing:
        print("DRY RUN ONLY: no replication was executed and no file changed.")
        return

    extension_root.mkdir(parents=True, exist_ok=True)
    _atomic_json(extension_root / "manifest.json", {
        "created_utc": _utc_now(), "notice": NOTICE,
        "selection_method": "deterministic maximin coverage of standardized cross-horizon outcomes",
        "selected_draws": selected, "base_replications": 3,
        "target_replications": args.target_replications,
        "status": "running", "preflight": audit,
    })
    for days, label in HORIZONS:
        base = _raw_config(results_root, days, label)
        design = latin_hypercube_design(base.master_seed, base.draws)
        target = CampaignConfig(
            **{**base.__dict__, "outdir": str(extension_root / label),
               "replications": args.target_replications})
        invalid_ids = {item["draw"] for item in
                       audit["horizons"][label]["invalid_draws"]}
        missing_ids = {item["draw"] for item in
                       audit["horizons"][label]["missing_draws"]}
        for draw in sorted(invalid_ids | missing_ids):
            rows = run_replication_rows(
                target, draw, design[draw],
                range(base.replications, args.target_replications))
            _atomic_json(extension_root / label / f"draw_{draw:04d}.json", {
                "complete": True, "draw": draw,
                "sample": design[draw], "horizon_days": days,
                "base_replications": base.replications,
                "target_replications": args.target_replications,
                "replication_indices": list(range(
                    base.replications, args.target_replications)),
                "regimes": list(base.regimes), "rows": rows,
            })
    final_audit = inspect_extensions(
        results_root, extension_root, selected, args.target_replications)
    if any(value["missing_draws"] or value["invalid_draws"]
           for value in final_audit["horizons"].values()):
        raise RuntimeError("replication extension remains incomplete")
    summary = summarize_extensions(
        results_root, extension_root, selected, args.target_replications)
    _atomic_json(extension_root / "replication_robustness_summary.json", summary)
    _write_rankings_csv(extension_root / "ranking_stability.csv",
                        summary["ranking_stability"])
    manifest = _load_json(extension_root / "manifest.json")
    manifest.update({"status": "complete", "completed_utc": _utc_now(),
                     "final_audit": final_audit})
    _atomic_json(extension_root / "manifest.json", manifest)


if __name__ == "__main__":
    main()
