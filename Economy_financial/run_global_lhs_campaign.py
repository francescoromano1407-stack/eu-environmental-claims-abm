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
                                              run_campaign,
                                              summarize_campaign,
                                              validate_draw_payload)


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
    existing = Path(args.existing_root).resolve()
    if ((existing / "manifest.json").is_file()
            and (existing / "configuration.json").is_file()
            and (existing / "raw").is_dir()):
        return existing
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


def _identity_mismatch(manifest: dict[str, Any],
                       config: CampaignConfig) -> list[str]:
    """Return whether a candidate directory belongs to this exact design.

    A matching horizon alone is insufficient: resuming from a different LHS
    size, master seed, supervision stream, regime set, or replication count
    would silently destroy the paired comparison.  The design matrix is also
    checked below, draw by draw.
    """
    previous = manifest.get("config", manifest.get("configuration", {}))
    expected = config.to_dict()
    return [key for key in (
        "draws", "replications", "horizon_days", "master_seed",
        "supervision_base_seed", "regimes", "num_traders",
        "num_manipulators", "enable_credit")
        if previous.get(key) != expected.get(key)]


def _identity_matches(manifest: dict[str, Any], config: CampaignConfig) -> bool:
    return not _identity_mismatch(manifest, config)


def _valid_draw_payload(payload: Any, config: CampaignConfig, draw: int,
                        sample: dict[str, float]) -> bool:
    """Validate a completed raw draw before permitting it to be reused."""
    return validate_draw_payload(payload, config, draw, sample)[0]


def _read_draw(path: Path, config: CampaignConfig, draw: int,
               sample: dict[str, float]) -> tuple[dict[str, Any] | None, str]:
    if not path.is_file():
        return None, "file is missing"
    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as error:
        return None, f"corrupt JSON: {error.msg}"
    except OSError as error:
        return None, f"unreadable file: {error}"
    valid, reason = validate_draw_payload(payload, config, draw, sample)
    return (payload if valid else None), reason


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
    flattened = root / "raw" / plan.label
    if flattened.is_dir():
        candidates.append(flattened)
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


def inspect_completed_draws(args: argparse.Namespace, run_dir: Path,
                            destination: Path, plan: HorizonPlan,
                            config: CampaignConfig) -> dict[str, Any]:
    """Read-only audit of active and historical raw draw files.

    The active directory wins.  A draw from a historical directory is only
    listed as importable when both its manifest identity and its complete
    draw payload match the exact requested campaign.
    """
    design = latin_hypercube_design(config.master_seed, config.draws)
    accepted_sources: list[Path] = []
    rejected_directories: list[dict[str, Any]] = []
    for candidate in _candidate_raw_directories(
            args, run_dir, destination, plan):
        manifest = _load_candidate_manifest(candidate)
        if manifest is None:
            rejected_directories.append({
                "path": str(candidate),
                "reason": "manifest.json is missing, corrupt, or not an object",
            })
            continue
        mismatch = _identity_mismatch(manifest, config)
        if mismatch:
            rejected_directories.append({
                "path": str(candidate),
                "reason": "campaign identity mismatch: " + ", ".join(mismatch),
            })
            continue
        accepted_sources.append(candidate)

    reused: list[int] = []
    importable: list[dict[str, Any]] = []
    rejected_draws: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for draw, sample in enumerate(design):
        target = destination / f"draw_{draw:04d}.json"
        payload, target_reason = _read_draw(target, config, draw, sample)
        if payload is not None:
            reused.append(draw)
            continue
        if target.is_file():
            rejected_draws.append({
                "draw": draw, "path": str(target), "reason": target_reason,
            })
        replacement: tuple[Path, dict[str, Any]] | None = None
        for candidate in accepted_sources:
            if candidate == destination:
                continue
            source = candidate / target.name
            candidate_payload, reason = _read_draw(
                source, config, draw, sample)
            if candidate_payload is not None:
                replacement = source, candidate_payload
                break
            if source.is_file():
                rejected_draws.append({
                    "draw": draw, "path": str(source), "reason": reason,
                })
        if replacement is not None:
            importable.append({
                "draw": draw, "source": str(replacement[0]),
                "destination": str(target),
            })
        else:
            unresolved.append({
                "draw": draw, "path": str(target), "reason": target_reason,
            })
    return {
        "label": plan.label,
        "horizon_days": plan.days,
        "target_draws": config.draws,
        "valid_existing_draws": len(reused),
        "valid_existing_draw_ids": reused,
        "importable_draws": len(importable),
        "importable_draw_details": importable,
        "ready_without_simulation": len(reused) + len(importable),
        "missing_or_invalid_draws": unresolved,
        "rejected_draws": rejected_draws,
        "candidate_sources": [str(path) for path in accepted_sources],
        "rejected_candidate_directories": rejected_directories,
    }


def print_inspection(audit: dict[str, Any]) -> None:
    print(f"[{audit['horizon_days']} days / {audit['label']}]", flush=True)
    print("  valid existing draws: "
          f"{audit['valid_existing_draws']}/{audit['target_draws']}",
          flush=True)
    print(f"  valid draws available to import: {audit['importable_draws']}",
          flush=True)
    unresolved = audit["missing_or_invalid_draws"]
    print(f"  missing or invalid draws requiring simulation: {len(unresolved)}",
          flush=True)
    if unresolved:
        for item in unresolved:
            print(f"    draw_{item['draw']:04d}: {item['reason']} "
                  f"({item['path']})", flush=True)
    else:
        print("    none", flush=True)


def hydrate_completed_draws(args: argparse.Namespace, run_dir: Path,
                            destination: Path, plan: HorizonPlan,
                            config: CampaignConfig) -> dict[str, Any]:
    """Atomically import only valid, matching raw draws before a resume.

    The active destination is inspected first.  Invalid or corrupt draw
    files are never accepted; a valid draw from a matching historical run can
    replace them atomically.  Missing draws are left for ``run_campaign``.
    """
    destination.mkdir(parents=True, exist_ok=True)
    audit = inspect_completed_draws(
        args, run_dir, destination, plan, config)
    imported: list[int] = []
    for item in audit["importable_draw_details"]:
        source = Path(item["source"])
        with source.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        _atomic_json(Path(item["destination"]), payload)
        imported.append(item["draw"])
    return {
        **audit,
        "imported_draws": len(imported),
        "imported_draw_ids": imported,
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
    preflight = inspect_completed_draws(
        args, run_dir, raw_dir, plan, config)
    reuse = hydrate_completed_draws(args, run_dir, raw_dir, plan, config)
    after_import = inspect_completed_draws(
        args, run_dir, raw_dir, plan, config)
    pending_before_run = {
        item["draw"] for item in after_import["missing_or_invalid_draws"]}
    started = time.time()
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"{_utc_now()} inspected {plan.label}: "
                     f"{len(pending_before_run)} draws require simulation\n")
        try:
            if pending_before_run:
                summary = run_campaign(config, progress=True)
            else:
                summary = summarize_campaign(str(raw_dir), config=config)
        except Exception as error:
            handle.write(f"{_utc_now()} failed: {type(error).__name__}: {error}\n")
            _update_manifest(run_dir, status="failed")
            raise
        handle.write(f"{_utc_now()} completed in {time.time() - started:.3f}s\n")
    final_audit = inspect_completed_draws(
        args, run_dir, raw_dir, plan, config)
    still_pending = {
        item["draw"] for item in final_audit["missing_or_invalid_draws"]}
    ledger = {
        "created_utc": _utc_now(),
        "notice": NOTICE,
        "design_identity": config.to_dict(),
        "reused_draws": preflight["valid_existing_draw_ids"],
        "imported_draws": reuse["imported_draw_ids"],
        "rejected_draws": preflight["rejected_draws"],
        "rejected_candidate_directories":
            preflight["rejected_candidate_directories"],
        "newly_run_draws": sorted(pending_before_run - still_pending),
        "remaining_missing_or_invalid_draws":
            final_audit["missing_or_invalid_draws"],
    }
    _atomic_json(raw_dir / "completion_ledger.json", ledger)
    _copy_summary_artifacts(raw_dir, run_dir / "summaries", plan.label)
    write_raw_metric_table(raw_dir, run_dir / "summaries", plan.label)
    return summary, ledger


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
    parser.add_argument("--full-robustness", dest="full_robustness",
                        action="store_true",
                        help="Inspect/complete 120, 365, 1000, and 2000 days (default)")
    parser.add_argument("--base-horizon-only", dest="full_robustness",
                        action="store_false",
                        help="Inspect only --horizon instead of all four publication horizons")
    parser.add_argument("--existing-root", default="results", help="Root containing prior campaign directories to inspect")
    parser.add_argument("--development", action="store_true", help="Permit smaller non-publication design")
    parser.add_argument(
        "--execute-missing", action="store_true",
        help=("Explicitly permit simulations for the exact missing/invalid "
              "draws printed by the preflight audit"))
    parser.add_argument(
        "--rebuild-only", action="store_true",
        help=("Regenerate summaries/tables/figures without simulation; "
              "refuse if any draw still requires simulation"))
    parser.set_defaults(full_robustness=True)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if not args.development and (args.draws < 200 or args.replications < 3 or args.horizon < 120):
        raise ValueError("publication campaign requires >=200 draws, >=3 replications, and >=120 days")
    plans = planned_horizons(args)
    run_dir = create_run_directory(args)
    audits = []
    for plan in plans:
        raw_dir = run_dir / "raw" / plan.label
        config = CampaignConfig(
            outdir=str(raw_dir), draws=args.draws,
            replications=args.replications, horizon_days=plan.days,
            master_seed=args.master_seed,
            supervision_base_seed=args.supervision_base_seed,
            num_traders=args.num_traders, label=plan.label,
            subset=plan.subset,
        )
        audit = inspect_completed_draws(
            args, run_dir, raw_dir, plan, config)
        audits.append(audit)
        print_inspection(audit)
    if not args.execute_missing and not args.rebuild_only:
        print("DRY RUN ONLY: no files changed and no simulation executed. "
              "Use --execute-missing only after reviewing the lists above.",
              flush=True)
        return
    if args.rebuild_only and any(
            audit["missing_or_invalid_draws"] for audit in audits):
        raise ValueError(
            "--rebuild-only refused: at least one draw requires simulation; "
            "review the exact preflight list above")
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
