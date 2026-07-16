"""Reproducible publication-campaign driver for the anti-greenwashing model.

This is intentionally an orchestration layer.  It does not change model
behaviour: each arm is executed by ``market_sim.sensitivity_campaign`` with
the three primary regimes, paired common random numbers, and the registry's
GSA-eligible (STYLIZATION/EXPERIMENT) dimensions only.

The default command creates one timestamped, resumable run directory.  It
never presents simulation output as an empirical forecast.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from market_sim.parameter_registry import REGISTRY, gsa_space
from market_sim.sensitivity_campaign import (CampaignConfig, DEFAULT_REGIMES,
                                              latin_hypercube_design,
                                              run_campaign)


NOTICE = "Simulation-based policy experiment; not an empirical forecast."
def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
    os.replace(temporary, path)


def _timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S", time.gmtime())


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass(frozen=True)
class HorizonPlan:
    days: int
    label: str
    subset: tuple[int, ...] | None


def planned_horizons(args: argparse.Namespace) -> list[HorizonPlan]:
    plans = [HorizonPlan(args.horizon, f"horizon_{args.horizon}d", None)]
    if args.confirmation or args.full_robustness:
        plans.append(HorizonPlan(365, "robustness_365d", None))
    long_horizons = "1000,2000" if args.full_robustness else args.long_horizons
    if long_horizons:
        wanted = {int(value) for value in long_horizons.split(",")}
        if 1000 in wanted:
            plans.append(HorizonPlan(1000, "robustness_1000d", None))
        if 2000 in wanted:
            plans.append(HorizonPlan(2000, "robustness_2000d", None))
        invalid = wanted - {1000, 2000}
        if invalid:
            raise ValueError("--long-horizons accepts only 1000 and/or 2000")
    return plans


def create_run_directory(args: argparse.Namespace) -> Path:
    if args.resume:
        run_dir = Path(args.resume).resolve()
        if not (run_dir / "manifest.json").is_file():
            raise ValueError("--resume must name an existing campaign directory")
        return run_dir
    return (Path(args.output_root) / _timestamp()).resolve()


def _ensure_layout(run_dir: Path) -> None:
    for name in ("logs", "raw", "summaries", "figures"):
        (run_dir / name).mkdir(parents=True, exist_ok=True)


def _registry_export() -> list[dict[str, Any]]:
    """Export all fields requested for every sampled parameter."""
    eligible = set(gsa_space())
    return [asdict(spec) for spec in REGISTRY if spec.name in eligible]


def _write_readme(run_dir: Path) -> None:
    (run_dir / "README.md").write_text(
        "# Global LHS campaign\n\n"
        f"> {NOTICE}\n\n"
        "`configuration.json` is the complete requested design; "
        "`manifest.json` records its execution state.  Every raw draw is "
        "atomic and resumable.  Latent-truth metrics are evaluator-only "
        "research metrics and are never agent inputs.\n\n"
        "- `raw/<horizon>/draw_*.json`: one completed LHS configuration "
        "with all paired replications and metric families.\n"
        "- `summaries/`: copied machine-readable summaries and flat tables.\n"
        "- `figures/`: publication figures created after at least one horizon "
        "is available.\n"
        "- `raw/<horizon>/failed_runs.json`: atomic failure record, if any.\n",
        encoding="utf-8",
    )


def initialise(run_dir: Path, args: argparse.Namespace,
               plans: Sequence[HorizonPlan]) -> dict[str, Any]:
    _ensure_layout(run_dir)
    config_path = run_dir / "configuration.json"
    if config_path.exists():
        with config_path.open(encoding="utf-8") as handle:
            config = json.load(handle)
        expected = {
            "draws": args.draws,
            "replications": args.replications,
            "master_seed": args.master_seed,
            "supervision_base_seed": args.supervision_base_seed,
            "num_traders": args.num_traders,
            "regimes": list(DEFAULT_REGIMES),
            "horizons": [asdict(plan) for plan in plans],
        }
        differing = [key for key, value in expected.items()
                     if config.get(key) != value]
        if differing:
            raise ValueError("resume configuration differs on "
                             + ", ".join(differing))
        return config
    config = {
        "created_utc": _utc_now(), "draws": args.draws,
        "replications": args.replications, "master_seed": args.master_seed,
        "supervision_base_seed": args.supervision_base_seed,
        "num_traders": args.num_traders,
        "regimes": [
            "current_eu_supervision",
            "sme_algorithmic_prescreening",
            "certified_green_data_connector",
        ],
        "seed_schedule": {
            "market": "master_seed + 1000000*draw + 1000*replication",
            "supervision": "supervision_base_seed + 104729*draw + 7919*replication",
            "common_random_numbers": "both seeds reset for every regime within a replication",
        },
        "horizons": [asdict(plan) for plan in plans],
        "discounting": "social_discount_rate sampled per LHS draw; undiscounted ledgers retained",
        "sampled_parameters": _registry_export(),
        "research_only_metrics": [
            "Latent-truth incidence/severity and evaluator intent metrics are ex-post only.",
            "They are never passed into firm, consumer, investor, workforce, hub, connector, or regulator decisions.",
        ],
        "exact_command": sys.argv,
        "notice": NOTICE,
    }
    _atomic_json(config_path, config)
    _atomic_json(run_dir / "manifest.json", {
        "created_utc": _utc_now(), "configuration": config,
        "status": "created", "horizons": {}, "failures": [],
    })
    _write_readme(run_dir)
    return config


def _update_manifest(run_dir: Path, **changes: Any) -> None:
    path = run_dir / "manifest.json"
    with path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    manifest.update(changes)
    manifest["updated_utc"] = _utc_now()
    _atomic_json(path, manifest)


def _manifest_horizons(run_dir: Path) -> dict[str, Any]:
    with (run_dir / "manifest.json").open(encoding="utf-8") as handle:
        return dict(json.load(handle).get("horizons", {}))


def _copy_summary_artifacts(raw_dir: Path, summary_dir: Path, label: str) -> None:
    for filename in ("summary.json", "draw_effects.csv", "manifest.json",
                     "failed_runs.json"):
        source = raw_dir / filename
        if source.exists():
            shutil.copy2(source, summary_dir / f"{label}_{filename}")


def _metrics_from_draws(raw_dir: Path) -> Iterable[dict[str, Any]]:
    for path in sorted(raw_dir.glob("draw_*.json")):
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("complete"):
            for row in payload["rows"]:
                yield {"draw": payload["draw"], "horizon_days": payload["horizon_days"],
                       "discount_rate": payload["discount_rate"],
                       "parameters": payload["sample"], **row}


def write_raw_metric_table(raw_dir: Path, summaries: Path, label: str) -> None:
    """Make every run-level outcome, seeds, and parameter value tabular."""
    rows = list(_metrics_from_draws(raw_dir))
    if not rows:
        return
    metric_names = sorted(rows[0]["metrics"])
    parameter_names = sorted(rows[0]["parameters"])
    path = summaries / f"{label}_run_level_metrics.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "draw", "horizon_days", "discount_rate", "regime", "replication",
            "market_seed", "supervision_seed", *parameter_names, *metric_names,
        ])
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "draw": row["draw"], "horizon_days": row["horizon_days"],
                "discount_rate": row["discount_rate"], "regime": row["regime"],
                "replication": row["replication"], "market_seed": row["market_seed"],
                "supervision_seed": row["supervision_seed"], **row["parameters"],
                **row["metrics"],
            })


def _identity_matches(manifest: dict[str, Any], config: CampaignConfig) -> bool:
    """Return whether a candidate directory belongs to this exact design.

    A matching horizon alone is insufficient: resuming from a different LHS
    size, master seed, supervision stream, regime set, or replication count
    would silently destroy the paired comparison.  The design matrix is also
    checked below, draw by draw.
    """
    previous = manifest.get("config", manifest.get("configuration", {}))
    expected = config.to_dict()
    return all(previous.get(key) == expected.get(key) for key in (
        "draws", "replications", "horizon_days", "master_seed",
        "supervision_base_seed", "regimes"))


def _valid_draw_payload(payload: Any, config: CampaignConfig, draw: int,
                        sample: dict[str, float]) -> bool:
    """Validate a completed raw draw before permitting it to be reused."""
    if not isinstance(payload, dict) or payload.get("complete") is not True:
        return False
    if (payload.get("draw") != draw or payload.get("sample") != sample
            or payload.get("horizon_days") != config.horizon_days
            or payload.get("replications") != config.replications
            or payload.get("regimes") != list(config.regimes)):
        return False
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) != config.replications * len(config.regimes):
        return False
    expected_rows = {
        (replication, regime): (config.market_seed(draw, replication),
                                config.supervision_seed(draw, replication))
        for replication in range(config.replications)
        for regime in config.regimes
    }
    observed: set[tuple[int, str]] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("metrics"), dict):
            return False
        key = (row.get("replication"), row.get("regime"))
        if key not in expected_rows or key in observed:
            return False
        if (row.get("market_seed"), row.get("supervision_seed")) != expected_rows[key]:
            return False
        try:
            if not all(math.isfinite(float(value)) for value in row["metrics"].values()):
                return False
        except (TypeError, ValueError):
            return False
        observed.add(key)
    return observed == set(expected_rows)


def _load_candidate_manifest(directory: Path) -> dict[str, Any] | None:
    try:
        with (directory / "manifest.json").open(encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _candidate_raw_directories(args: argparse.Namespace, run_dir: Path,
                               destination: Path, plan: HorizonPlan) -> list[Path]:
    """Find both the active run and historical campaign outputs to inspect."""
    candidates = [destination]
    root = Path(args.existing_root).resolve()
    legacy = root / f"campaign_{plan.days}d"
    if legacy.is_dir():
        candidates.append(legacy)
    global_root = root / "global_lhs_campaign"
    if global_root.is_dir():
        for previous in global_root.iterdir():
            raw = previous / "raw"
            if raw.is_dir():
                candidates.extend(path for path in raw.iterdir()
                                  if path.is_dir())
    # Preserve search order while avoiding redundant self-import attempts.
    unique: list[Path] = []
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate not in unique:
            unique.append(candidate)
    return unique


def hydrate_completed_draws(args: argparse.Namespace, run_dir: Path,
                            destination: Path, plan: HorizonPlan,
                            config: CampaignConfig) -> dict[str, Any]:
    """Atomically import only valid, matching raw draws before a resume.

    The active destination is inspected first.  Invalid or corrupt draw
    files are never accepted; a valid draw from a matching historical run can
    replace them atomically.  Missing draws are left for ``run_campaign``.
    """
    destination.mkdir(parents=True, exist_ok=True)
    design = latin_hypercube_design(config.master_seed, config.draws)
    imported = 0
    valid_existing = 0
    rejected_directories: list[str] = []
    sources: list[str] = []
    for candidate in _candidate_raw_directories(args, run_dir, destination, plan):
        manifest = _load_candidate_manifest(candidate)
        if manifest is None or not _identity_matches(manifest, config):
            rejected_directories.append(str(candidate))
            continue
        sources.append(str(candidate))
        for draw, sample in enumerate(design):
            source = candidate / f"draw_{draw:04d}.json"
            if not source.is_file():
                continue
            try:
                with source.open(encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            if not _valid_draw_payload(payload, config, draw, sample):
                continue
            target = destination / source.name
            if candidate == destination:
                valid_existing += 1
                continue
            # Never overwrite a valid active draw; it was inspected first.
            active_valid = False
            if target.is_file():
                try:
                    with target.open(encoding="utf-8") as handle:
                        active = json.load(handle)
                    active_valid = _valid_draw_payload(active, config, draw,
                                                        sample)
                except (OSError, json.JSONDecodeError):
                    pass
            if not active_valid:
                _atomic_json(target, payload)
                imported += 1
    return {
        "valid_existing_draws": valid_existing,
        "imported_draws": imported,
        "candidate_sources": sources,
        "rejected_candidate_directories": rejected_directories,
        "target_draws": config.draws,
    }


def run_plan(run_dir: Path, args: argparse.Namespace,
             plan: HorizonPlan) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_dir = run_dir / "raw" / plan.label
    log = run_dir / "logs" / f"{plan.label}.log"
    config = CampaignConfig(
        outdir=str(raw_dir), draws=args.draws, replications=args.replications,
        horizon_days=plan.days, master_seed=args.master_seed,
        supervision_base_seed=args.supervision_base_seed,
        num_traders=args.num_traders, label=plan.label, subset=plan.subset,
    )
    reuse = hydrate_completed_draws(args, run_dir, raw_dir, plan, config)
    started = time.time()
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"{_utc_now()} started {plan.label}\n")
        try:
            summary = run_campaign(config, progress=True)
        except Exception as error:
            handle.write(f"{_utc_now()} failed: {type(error).__name__}: {error}\n")
            _update_manifest(run_dir, status="failed")
            raise
        handle.write(f"{_utc_now()} completed in {time.time() - started:.3f}s\n")
    _copy_summary_artifacts(raw_dir, run_dir / "summaries", plan.label)
    write_raw_metric_table(raw_dir, run_dir / "summaries", plan.label)
    return summary, reuse


def _figure_footer(figure: Any, summary: dict[str, Any]) -> None:
    figure.text(0.01, 0.01,
                f"Horizon {summary['horizon_days']}d; {summary['draws_summarized']} LHS draws; "
                f"{summary['replications']} paired replications; sampled social discount rate. {NOTICE}",
                fontsize=7, wrap=True)


def generate_figures(run_dir: Path, summaries: Sequence[dict[str, Any]]) -> None:
    """Generate the required distributional/policy figures from summaries.

    This deliberately uses only stored evaluator outputs: no figures cause a
    simulation to be re-run and no latent truth enters agent decisions.
    """
    if not summaries:
        return
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    summary = summaries[0]
    figures = run_dir / "figures"
    regimes = summary["regimes"]
    effects = summary["effect_distributions"]
    colors = ["#4c72b0", "#55a868", "#c44e52"]
    # 1/2: regime outcome and paired-effect distributions.
    for number, metric, title in (
        (1, "exposure_weighted_severity", "Paired severity reduction versus baseline"),
        (2, "mean_greenhushing_gap", "Paired greenhushing improvement versus baseline"),
    ):
        fig, ax = plt.subplots(figsize=(8, 5))
        stats = effects[metric]
        names = list(stats)
        ax.errorbar(range(len(names)), [stats[n]["mean"] for n in names],
                    yerr=[stats[n]["ci95_halfwidth"] for n in names], fmt="o",
                    capsize=4, color="#333333")
        ax.axhline(0, color="#777777", linewidth=.8)
        ax.set_xticks(range(len(names)), names, rotation=15, ha="right")
        ax.set_ylabel("positive = improvement")
        ax.set_title(f"Figure {number}. {title}")
        ax.grid(axis="y", linestyle=":", alpha=.5)
        _figure_footer(fig, summary); fig.tight_layout(rect=(0, .06, 1, 1))
        fig.savefig(figures / f"fig{number:02d}_paired_effects.png", dpi=220); plt.close(fig)
    # 3: greenwashing/greenhushing frontier based on per-draw means.
    fig, ax = plt.subplots(figsize=(8, 5))
    for regime, color in zip(regimes, colors):
        xs, ys = [], []
        for item in summary["per_draw"]:
            xs.append(item["mean_metrics"][regime]["exposure_weighted_severity"])
            ys.append(item["mean_metrics"][regime]["mean_greenhushing_gap"])
        ax.scatter(xs, ys, s=13, alpha=.55, label=regime, color=color)
    ax.set(xlabel="Exposure-weighted severity", ylabel="Greenhushing gap",
           title="Figure 3. Greenwashing-versus-greenhushing frontier")
    ax.legend(fontsize=7); ax.grid(linestyle=":", alpha=.5)
    _figure_footer(fig, summary); fig.tight_layout(rect=(0, .06, 1, 1))
    fig.savefig(figures / "fig03_greenwashing_greenhushing_frontier.png", dpi=220); plt.close(fig)
    # 4: cost-effectiveness plane.
    fig, ax = plt.subplots(figsize=(8, 5))
    baseline = summary["baseline"]
    for regime, color in zip(regimes[1:], colors[1:]):
        cost_difference = [
            (item["mean_metrics"][regime]["discounted_total_public_cost"]
             + item["mean_metrics"][regime]["firm_policy_cost"]
             + item["mean_metrics"][regime]["firm_reporting_cost"])
            - (item["mean_metrics"][baseline]["discounted_total_public_cost"]
               + item["mean_metrics"][baseline]["firm_policy_cost"]
               + item["mean_metrics"][baseline]["firm_reporting_cost"])
            for item in summary["per_draw"]]
        severity = [item["contrasts"]["exposure_weighted_severity"][regime]
                    for item in summary["per_draw"]]
        ax.scatter(cost_difference, severity, s=13, alpha=.55, label=regime,
                   color=color)
    ax.axhline(0, color="#777777", linewidth=.8); ax.axvline(0, color="#777777", linewidth=.8)
    ax.set(title="Figure 4. Cost-effectiveness frontier", xlabel="Additional policy and firm cost", ylabel="Severity reduction")
    ax.legend(fontsize=7); ax.grid(linestyle=":", alpha=.5)
    _figure_footer(fig, summary); fig.tight_layout(rect=(0, .06, 1, 1))
    fig.savefig(figures / "fig04_cost_effectiveness.png", dpi=220); plt.close(fig)
    # 5: Pareto frequency.
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(regimes, [summary["pareto_frequency"][r] for r in regimes], color=colors)
    ax.set(title="Figure 5. Pareto-front frequency", ylabel="LHS draws")
    ax.tick_params(axis="x", rotation=18); ax.grid(axis="y", linestyle=":", alpha=.5)
    _figure_footer(fig, summary); fig.tight_layout(rect=(0, .06, 1, 1))
    fig.savefig(figures / "fig05_pareto_front_frequency.png", dpi=220); plt.close(fig)
    # 6: regulator capacity/backlog relationship.
    fig, ax = plt.subplots(figsize=(8, 5))
    capacities = [item["sample"]["investigation_capacity"] for item in summary["per_draw"]]
    backlog = [item["mean_metrics"][baseline]["backlog_pending_cases"] for item in summary["per_draw"]]
    ax.scatter(capacities, backlog, s=13, alpha=.55)
    ax.set(title="Figure 6. Regulator capacity and backlog", xlabel="Investigation capacity", ylabel="Pending cases")
    ax.grid(linestyle=":", alpha=.5)
    _figure_footer(fig, summary); fig.tight_layout(rect=(0, .06, 1, 1))
    fig.savefig(figures / "fig06_capacity_backlog.png", dpi=220); plt.close(fig)
    # 7/8: parameter importance for severity and default ranking.
    importance_targets = summary["parameter_importance"]
    for number, target, title in ((7, next(key for key in importance_targets if "severity" in key), "Severity importance"),
                                  (8, next(key for key in importance_targets if key.startswith("rank_default_")), "Default-ranking importance")):
        entries = importance_targets[target]
        top = sorted(entries.items(), key=lambda item: abs(item[1]["prcc"]), reverse=True)[:12]
        fig, ax = plt.subplots(figsize=(8, 6))
        ax.barh([name for name, _ in top][::-1], [v["prcc"] for _, v in top][::-1])
        ax.axvline(0, color="#777777", linewidth=.8); ax.set(title=f"Figure {number}. {title} (PRCC)", xlabel="PRCC")
        _figure_footer(fig, summary); fig.tight_layout(rect=(0, .07, 1, 1))
        fig.savefig(figures / f"fig{number:02d}_parameter_importance.png", dpi=220); plt.close(fig)
    # 9: winner frequency by score scenario.
    fig, ax = plt.subplots(figsize=(9, 5))
    scenario = "default_experiment"
    scenarios = list(summary["winner_frequency"])
    for index, regime in enumerate(regimes):
        ax.plot(scenarios, [summary["winner_frequency"][s][regime] for s in scenarios],
                marker="o", label=regime, color=colors[index])
    ax.set(title="Figure 9. Winner frequency by normative weight scenario", ylabel="LHS draws")
    ax.legend(fontsize=7); ax.tick_params(axis="x", rotation=20); ax.grid(linestyle=":", alpha=.5)
    _figure_footer(fig, summary); fig.tight_layout(rect=(0, .07, 1, 1))
    fig.savefig(figures / "fig09_ranking_winner_frequency.png", dpi=220); plt.close(fig)
    # 10: horizon robustness.
    fig, ax = plt.subplots(figsize=(8, 5))
    for other in summaries:
        for regime, color in zip(regimes, colors):
            ax.scatter(other["horizon_days"], other["winner_frequency"][scenario][regime] / other["draws_summarized"],
                       color=color, label=regime if other is summaries[0] else None)
    ax.set(title="Figure 10. Horizon robustness", xlabel="Horizon days", ylabel="Default-weight winner share")
    ax.legend(fontsize=7); ax.grid(linestyle=":", alpha=.5)
    _figure_footer(fig, summary); fig.tight_layout(rect=(0, .07, 1, 1))
    fig.savefig(figures / "fig10_horizon_robustness.png", dpi=220); plt.close(fig)


def write_design_table(run_dir: Path) -> None:
    fields = ["parameter_id", "name", "location", "low", "high", "default",
              "classification", "justification"]
    with (run_dir / "summaries" / "table_lhs_design_ranges.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for spec in _registry_export(): writer.writerow({key: spec[key] for key in fields})


def write_unified_campaign_summary(run_dir: Path,
                                   summaries: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Rebuild cross-horizon ranking stability after every completion pass."""
    by_horizon = {str(summary["horizon_days"]): {
        "draws_summarized": summary["draws_summarized"],
        "replications": summary["replications"],
        "winner_frequency": summary["winner_frequency"],
        "rank_frequency": summary["rank_frequency"],
        "pareto_frequency": summary["pareto_frequency"],
        "parameter_importance": summary["parameter_importance"],
        "parameter_importance_diagnostics": summary["parameter_importance_diagnostics"],
    } for summary in summaries}
    winner_maps = [{item["draw"]: item["winners"]["default_experiment"]
                    for item in summary["per_draw"]}
                   for summary in summaries]
    shared = set.intersection(*(set(mapping) for mapping in winner_maps)) if winner_maps else set()
    reversals = sum(
        len({mapping[draw] for mapping in winner_maps}) > 1
        for draw in shared)
    payload = {
        "updated_utc": _utc_now(), "notice": NOTICE,
        "horizons": by_horizon,
        "shared_draws_for_horizon_ranking": len(shared),
        "ranking_reversals_across_horizons": reversals,
        "ranking_reversal_frequency": reversals / len(shared) if shared else None,
    }
    _atomic_json(run_dir / "summaries" / "unified_campaign_summary.json", payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="results/global_lhs_campaign")
    parser.add_argument("--resume", help="Existing timestamped run directory to resume")
    parser.add_argument("--draws", type=int, default=200)
    parser.add_argument("--replications", type=int, default=3)
    parser.add_argument("--horizon", type=int, default=120)
    parser.add_argument("--master-seed", type=int, default=20260716)
    parser.add_argument("--supervision-base-seed", type=int, default=104729)
    parser.add_argument("--num-traders", type=int, default=8)
    parser.add_argument("--confirmation", action="store_true", help="Add all 200 draws at 365 days")
    parser.add_argument("--long-horizons", help="Add all 200 draws at horizons 1000 and/or 2000")
    parser.add_argument("--full-robustness", action="store_true", help="Add complete 365-, 1000-, and 2000-day campaigns")
    parser.add_argument("--existing-root", default="results", help="Root containing prior campaign directories to inspect")
    parser.add_argument("--development", action="store_true", help="Permit smaller non-publication design")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if not args.development and (args.draws < 200 or args.replications < 3 or args.horizon < 120):
        raise ValueError("publication campaign requires >=200 draws, >=3 replications, and >=120 days")
    plans = planned_horizons(args)
    run_dir = create_run_directory(args)
    initialise(run_dir, args, plans)
    summaries = []
    _update_manifest(run_dir, status="running")
    for plan in plans:
        summary, reuse = run_plan(run_dir, args, plan)
        summaries.append(summary)
        horizons = _manifest_horizons(run_dir)
        horizons[plan.label] = {
            "days": plan.days,
            "draws_summarized": summary["draws_summarized"],
            "reuse": reuse,
            "completed_utc": _utc_now(),
        }
        _update_manifest(run_dir, horizons=horizons)
    write_design_table(run_dir)
    unified = write_unified_campaign_summary(run_dir, summaries)
    generate_figures(run_dir, summaries)
    _update_manifest(run_dir, status="complete", completed_utc=_utc_now(),
                     unified_summary=unified)


if __name__ == "__main__":
    main()
