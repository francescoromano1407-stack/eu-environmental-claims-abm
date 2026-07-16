"""Part J (Workstream D): publication-quality figures and tables.

Generates the appendix figure set from the sensitivity-campaign outputs
(`results/campaign_*d/`) plus one default-parameter paired comparison.
Every figure states units, horizon, replication count and discounting,
and carries the notice that results are simulation outputs under
stylized parameters -- not forecasts.

Usage:
    python -m market_sim.campaign_reporting --results results --out results/figures
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import statistics
from typing import Any, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

NOT_FORECAST = ("Simulation output under stylized parameters "
                "(see docs/PARAMETER_REGISTRY.md); not a forecast.")

REGIME_SHORT = {
    "current_eu_supervision": "A: ex-post supervision",
    "sme_algorithmic_prescreening": "B: SME pre-screening hub",
    "certified_green_data_connector": "C: green data connector",
    "hybrid_prescreening_and_connector": "B+C hybrid",
}
REGIME_COLOR = {
    "current_eu_supervision": "#4c72b0",
    "sme_algorithmic_prescreening": "#55a868",
    "certified_green_data_connector": "#c44e52",
    "hybrid_prescreening_and_connector": "#8172b2",
}


def _load_summary(results_dir: str, name: str) -> Optional[dict[str, Any]]:
    path = os.path.join(results_dir, name, "summary.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _footer(fig, text: str) -> None:
    fig.text(0.01, 0.005, text + "  " + NOT_FORECAST, fontsize=7,
             color="#444444", wrap=True)


def _save(fig, out_dir: str, name: str) -> str:
    path = os.path.join(out_dir, name)
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)
    print(f"wrote {path}")
    return path


# --------------------------------------------------------------------------- #
# Default-parameter paired comparison (figures 1-3 input)
# --------------------------------------------------------------------------- #
def default_comparison(results_dir: str, replications: int = 5,
                       days: int = 365) -> dict[str, Any]:
    cache = os.path.join(results_dir, "default_comparison.json")
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("replications") == replications \
                and payload.get("days") == days:
            return payload
    from market_sim.policy_comparison import (
        run_greenwashing_policy_comparison)
    report = run_greenwashing_policy_comparison(
        {"num_traders": 8, "days": days}, replications=replications)
    payload = {
        "replications": replications, "days": days,
        "mean_metrics": report.mean_metrics,
        "ci_halfwidth": report.ci_halfwidth,
        "paired_statistics": report.paired_statistics,
        "rankings": report.rankings_by_scenario,
        "pareto": sorted(report.pareto_regimes),
        "warnings": report.warnings,
        "rows": [{"regime": row.regime, "replication": row.replication,
                  "metrics": row.metrics} for row in report.rows],
    }
    with open(cache, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, sort_keys=True)
    return payload


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #
def fig1_regime_comparison(default: dict, out_dir: str) -> None:
    metrics = [
        ("original_material_overstatements", "Material overstatements\n"
         "(original values, count)"),
        ("exposure_weighted_severity",
         "Exposure-weighted severity\n(severity x days)"),
        ("mean_greenhushing_gap", "Mean greenhushing gap\n(share 0-1)"),
        ("discounted_total_public_cost",
         "Discounted public cost\n(EUR, sim scale)"),
        ("population_detection_recall",
         "Population detection recall\n(share 0-1)"),
        ("employee_trust_mean", "Mean employee trust\n(share 0-1)"),
    ]
    regimes = list(default["mean_metrics"].keys())
    fig, axes = plt.subplots(2, 3, figsize=(13, 7))
    for ax, (key, label) in zip(axes.flatten(), metrics):
        values = [default["mean_metrics"][r][key] for r in regimes]
        errors = [default["ci_halfwidth"][r][key] for r in regimes]
        ax.bar(range(len(regimes)), values, yerr=errors, capsize=4,
               color=[REGIME_COLOR[r] for r in regimes])
        ax.set_xticks(range(len(regimes)))
        ax.set_xticklabels([REGIME_SHORT[r].replace(": ", ":\n")
                            for r in regimes], fontsize=7)
        ax.set_title(label, fontsize=9)
        ax.grid(True, linestyle=":", alpha=0.5, axis="y")
    fig.suptitle("Figure 1. Regime comparison at default parameters "
                 "(means with 95% CI across paired replications)",
                 fontsize=11, fontweight="bold")
    _footer(fig, f"Horizon {default['days']} days; "
            f"n={default['replications']} paired replications (common "
            "random numbers within replication); public cost discounted "
            "at 3%/yr, other metrics undiscounted.")
    _save(fig, out_dir, "fig01_regime_comparison.png")


def fig2_itt_vs_tot(default: dict, out_dir: str) -> None:
    hub = "sme_algorithmic_prescreening"
    metrics = default["mean_metrics"].get(hub)
    fig, ax = plt.subplots(figsize=(8, 5))
    if metrics is None:
        ax.text(0.5, 0.5, "hub arm not present", ha="center")
    else:
        labels = ["Participation\n(eligible firm-periods)",
                  "TOT meaningful revision\n(all submissions)",
                  "TOT revision, honest", "TOT revision, adaptive",
                  "TOT revision, greenwasher"]
        keys = ["hub_participation_rate",
                "hub_tot_meaningful_revision_rate",
                "hub_tot_revision_rate_honest",
                "hub_tot_revision_rate_adaptive",
                "hub_tot_revision_rate_greenwasher"]
        values = [metrics[k] for k in keys]
        errors = [default["ci_halfwidth"][hub][k] for k in keys]
        ax.bar(range(len(keys)), values, yerr=errors, capsize=4,
               color="#55a868")
        ax.set_xticks(range(len(keys)))
        ax.set_xticklabels(labels, fontsize=8)
        ax.set_ylabel("rate (share 0-1)")
        ax.grid(True, linestyle=":", alpha=0.5, axis="y")
    fig.suptitle("Figure 2. Hub ITT-style participation vs "
                 "treatment-on-the-treated revision rates", fontsize=11,
                 fontweight="bold")
    _footer(fig, f"Horizon {default['days']} days; "
            f"n={default['replications']} paired replications; "
            "participation is voluntary, so TOT rates reflect endogenous "
            "selection (strategy labels are research-only).")
    _save(fig, out_dir, "fig02_itt_vs_tot.png")


def fig3_incidence_families(default: dict, out_dir: str) -> None:
    regimes = list(default["mean_metrics"].keys())
    keys = [("original_material_overstatements", "original"),
            ("live_uncorrected_material_overstatements",
             "live uncorrected"),
            ("corrected_material_claims", "later corrected"),
            ("exposure_weighted_severity", "exposure-weighted (right)")]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax2 = ax.twinx()
    width = 0.2
    for index, (key, label) in enumerate(keys):
        values = [default["mean_metrics"][r][key] for r in regimes]
        errors = [default["ci_halfwidth"][r][key] for r in regimes]
        target = ax2 if "exposure" in key else ax
        target.bar([p + index * width for p in range(len(regimes))],
                   values, width=width, yerr=errors, capsize=3,
                   label=label,
                   color=["#4c72b0", "#dd8452", "#55a868",
                          "#937860"][index])
    ax.set_xticks([p + 1.5 * width for p in range(len(regimes))])
    ax.set_xticklabels([REGIME_SHORT[r] for r in regimes], fontsize=8)
    ax.set_ylabel("claims (count)")
    ax2.set_ylabel("severity x days")
    lines, labels_a = ax.get_legend_handles_labels()
    lines2, labels_b = ax2.get_legend_handles_labels()
    ax.legend(lines + lines2, labels_a + labels_b, fontsize=8)
    ax.grid(True, linestyle=":", alpha=0.5, axis="y")
    fig.suptitle("Figure 3. Greenwashing incidence families: original vs "
                 "live vs corrected vs exposure-weighted", fontsize=11,
                 fontweight="bold")
    _footer(fig, f"Horizon {default['days']} days; "
            f"n={default['replications']} paired replications; counts "
            "measured on ORIGINAL published values (corrections never "
            "launder history); undiscounted.")
    _save(fig, out_dir, "fig03_incidence_families.png")


def _effects_rows(results_dir: str, campaign: str) -> list[dict[str, str]]:
    path = os.path.join(results_dir, campaign, "draw_effects.csv")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def fig4_greenhushing_frontier(results_dir: str, out_dir: str,
                               summary: dict) -> None:
    rows = _effects_rows(results_dir, "campaign_120d")
    fig, ax = plt.subplots(figsize=(8, 5.5))
    for regime in summary["regimes"]:
        xs = [float(row[f"level__exposure_weighted_severity__{regime}"])
              for row in rows]
        ys = [float(row[f"level__mean_greenhushing_gap__{regime}"])
              for row in rows]
        ax.scatter(xs, ys, s=12, alpha=0.5, label=REGIME_SHORT[regime],
                   color=REGIME_COLOR[regime])
    ax.set_xlabel("exposure-weighted greenwashing severity "
                  "(severity x days, undiscounted)")
    ax.set_ylabel("mean greenhushing gap (share 0-1)")
    ax.legend(fontsize=8)
    ax.grid(True, linestyle=":", alpha=0.5)
    fig.suptitle("Figure 4. Greenhushing-versus-enforcement frontier "
                 "across the sampled parameter space", fontsize=11,
                 fontweight="bold")
    _footer(fig, f"Horizon {summary['horizon_days']} days; "
            f"{summary['draws_summarized']} LHS draws x "
            f"{summary['replications']} paired replications (per-draw "
            "means shown); undiscounted levels.")
    _save(fig, out_dir, "fig04_greenhushing_frontier.png")


def fig5_cost_effectiveness(results_dir: str, out_dir: str,
                            summary: dict) -> None:
    rows = _effects_rows(results_dir, "campaign_120d")
    baseline = summary["baseline"]
    fig, ax = plt.subplots(figsize=(8, 5.5))
    for regime in summary["regimes"][1:]:
        xs = [float(row[
            f"level__discounted_total_public_cost__{regime}"])
            - float(row[
                f"level__discounted_total_public_cost__{baseline}"])
            for row in rows]
        ys = [float(row[
            f"effect__exposure_weighted_severity__{regime}"])
            for row in rows]
        ax.scatter(xs, ys, s=12, alpha=0.5, label=REGIME_SHORT[regime],
                   color=REGIME_COLOR[regime])
    ax.axhline(0.0, color="#888888", linewidth=0.8)
    ax.axvline(0.0, color="#888888", linewidth=0.8)
    ax.set_xlabel("extra discounted public cost vs baseline "
                  "(EUR, sim scale, 3%/yr unless sampled otherwise)")
    ax.set_ylabel("severity reduction vs baseline "
                  "(positive = policy better)")
    ax.legend(fontsize=8)
    ax.grid(True, linestyle=":", alpha=0.5)
    pareto = summary["pareto_frequency"]
    total = summary["draws_summarized"]
    text = "; ".join(f"{REGIME_SHORT[r]}: Pareto-efficient in "
                     f"{count}/{total} draws"
                     for r, count in pareto.items())
    ax.set_title(text, fontsize=8)
    fig.suptitle("Figure 5. Cost-effectiveness plane and Pareto "
                 "frequency (paired, per draw)", fontsize=11,
                 fontweight="bold")
    _footer(fig, f"Horizon {summary['horizon_days']} days; "
            f"{summary['draws_summarized']} draws x "
            f"{summary['replications']} replications; costs discounted "
            "at the per-draw sampled social discount rate.")
    _save(fig, out_dir, "fig05_cost_effectiveness.png")


def fig6_capacity_backlog(results_dir: str, out_dir: str,
                          summary: dict) -> None:
    rows = _effects_rows(results_dir, "campaign_120d")
    baseline = summary["baseline"]
    capacity = [float(row["investigation_capacity"]) for row in rows]
    backlog = [float(row[f"level__backlog_pending_cases__{baseline}"])
               for row in rows]
    age = [float(row[f"level__queue_mean_age_days__{baseline}"])
           for row in rows]
    completion = [float(row[
        f"level__case_completion_days_mean__{baseline}"]) for row in rows]
    conflict_delay = [float(row[
        f"level__conflict_resolution_delay_mean__{baseline}"])
        for row in rows]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.4))
    for ax, (ys, label) in zip(axes, [
            (backlog, "pending cases at horizon (count)"),
            (age, "mean queue age (days)"),
            (completion, "mean case completion (days)")]):
        ax.scatter(capacity, ys, s=12, alpha=0.5, color="#4c72b0")
        ax.set_xlabel("sampled investigation capacity (per period)")
        ax.set_ylabel(label)
        ax.grid(True, linestyle=":", alpha=0.5)
    positive_delays = [d for d in conflict_delay if d > 0]
    axes[2].set_title(
        f"conflict investigations: mean resolution delay "
        f"{statistics.fmean(positive_delays):.0f}d over "
        f"{len(positive_delays)} draws with conflicts"
        if positive_delays else "no conflicts in sampled draws",
        fontsize=8)
    fig.suptitle("Figure 6. Regulator capacity vs backlog, queue age and "
                 "completion time (baseline regime)", fontsize=11,
                 fontweight="bold")
    _footer(fig, f"Horizon {summary['horizon_days']} days; "
            f"{summary['draws_summarized']} draws x "
            f"{summary['replications']} replications; undiscounted.")
    _save(fig, out_dir, "fig06_capacity_backlog.png")


def fig7_parameter_importance(summary: dict, out_dir: str) -> None:
    targets = [key for key in summary["parameter_importance"]
               if key.startswith("effect_severity")] \
        + ["baseline_exposure_weighted_severity"]
    fig, axes = plt.subplots(1, len(targets),
                             figsize=(5.5 * len(targets), 7),
                             squeeze=False)
    for ax, target in zip(axes[0], targets):
        entries = summary["parameter_importance"][target]
        ordered = sorted(entries.items(),
                         key=lambda kv: abs(kv[1]["src"]))[-12:]
        names = [name for name, _ in ordered]
        src = [values["src"] for _, values in ordered]
        prcc = [values["prcc"] for _, values in ordered]
        positions = range(len(names))
        ax.barh([p + 0.2 for p in positions], src, height=0.38,
                label="SRC", color="#4c72b0")
        ax.barh([p - 0.2 for p in positions], prcc, height=0.38,
                label="PRCC", color="#dd8452")
        ax.set_yticks(list(positions))
        ax.set_yticklabels(names, fontsize=7)
        ax.axvline(0.0, color="#888888", linewidth=0.8)
        ax.set_title(target, fontsize=9)
        ax.legend(fontsize=7)
        ax.grid(True, linestyle=":", alpha=0.5, axis="x")
    fig.suptitle("Figure 7. Global sensitivity: standardized regression "
                 "coefficients and partial rank correlations (top 12)",
                 fontsize=11, fontweight="bold")
    _footer(fig, f"Horizon {summary['horizon_days']} days; "
            f"{summary['draws_summarized']} LHS draws; measures "
            "parameter dependence of the MODEL, not causal effects.")
    _save(fig, out_dir, "fig07_parameter_importance.png")


def fig8_winner_frequency(summary: dict, out_dir: str) -> None:
    scenarios = list(summary["winner_frequency"].keys())
    regimes = summary["regimes"]
    fig, ax = plt.subplots(figsize=(9, 5))
    bottom = [0.0] * len(scenarios)
    total = summary["draws_summarized"]
    for regime in regimes:
        values = [summary["winner_frequency"][s].get(regime, 0) / total
                  for s in scenarios]
        ax.bar(range(len(scenarios)), values, bottom=bottom,
               label=REGIME_SHORT[regime], color=REGIME_COLOR[regime])
        bottom = [b + v for b, v in zip(bottom, values)]
    ax.set_xticks(range(len(scenarios)))
    ax.set_xticklabels([s.replace("_", "\n") for s in scenarios],
                       fontsize=8)
    ax.set_ylabel("share of draws won")
    ax.legend(fontsize=8)
    ax.set_title(
        f"winner changes across weight scenarios in "
        f"{summary['weight_sensitive_fraction']:.0%} of draws",
        fontsize=9)
    ax.grid(True, linestyle=":", alpha=0.5, axis="y")
    fig.suptitle("Figure 8. Winner frequency by composite-weight "
                 "scenario (rank stability)", fontsize=11,
                 fontweight="bold")
    _footer(fig, f"Horizon {summary['horizon_days']} days; "
            f"{summary['draws_summarized']} draws x "
            f"{summary['replications']} replications; composite weights "
            "are EXPERIMENT settings.")
    _save(fig, out_dir, "fig08_winner_frequency.png")


def fig9_horizon_robustness(results_dir: str, out_dir: str) -> None:
    campaigns = [("campaign_120d", 120), ("campaign_365d", 365),
                 ("campaign_1000d", 1000), ("campaign_2000d", 2000)]
    loaded = [(name, days, _load_summary(results_dir, name))
              for name, days in campaigns]
    loaded = [(name, days, s) for name, days, s in loaded
              if s is not None]
    hub = "sme_algorithmic_prescreening"
    con = "certified_green_data_connector"
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    # Left: shared-draw winner agreement across horizons.
    shared: Optional[set] = None
    for _, _, summary in loaded:
        draws = {item["draw"] for item in summary["per_draw"]}
        shared = draws if shared is None else shared & draws
    shared = sorted(shared or [])
    for name, days, summary in loaded:
        winners = {item["draw"]: item["winners"]["default_experiment"]
                   for item in summary["per_draw"]}
        values = [winners[d] for d in shared]
        for index, regime in enumerate(summary["regimes"]):
            share = sum(1 for v in values if v == regime) \
                / max(1, len(values))
            # Slight horizontal offset so equal shares stay visible.
            ax1.scatter([days * (0.94 + 0.06 * index)], [share],
                        color=REGIME_COLOR[regime], s=45)
    for regime in (hub, con, "current_eu_supervision"):
        ax1.plot([], [], color=REGIME_COLOR[regime],
                 label=REGIME_SHORT[regime], marker="o", linestyle="")
    ax1.set_xscale("log")
    ax1.set_xlabel("horizon (days, log scale)")
    ax1.set_ylabel("default-weight winner share "
                   f"(shared draws, n={len(shared)})")
    ax1.legend(fontsize=8)
    ax1.grid(True, linestyle=":", alpha=0.5)
    # Right: discount-rate dependence of the hub severity effect (120d).
    rows = _effects_rows(results_dir, "campaign_120d")
    xs = [float(row["social_discount_rate"]) for row in rows]
    ys = [float(row[
        "effect__discounted_exposure_weighted_severity__" + hub])
        for row in rows]
    ax2.scatter(xs, ys, s=12, alpha=0.5, color=REGIME_COLOR[hub])
    ax2.axhline(0.0, color="#888888", linewidth=0.8)
    ax2.set_xlabel("sampled social discount rate (1/yr)")
    ax2.set_ylabel("hub discounted-severity reduction vs baseline")
    ax2.grid(True, linestyle=":", alpha=0.5)
    fig.suptitle("Figure 9. Horizon and discount-rate robustness",
                 fontsize=11, fontweight="bold")
    _footer(fig, "Left: default-weight winner shares on the draw subset "
            "shared by all horizon campaigns (3 replications each). "
            "Right: 120-day campaign, 200 draws; discounted at the "
            "per-draw sampled rate.")
    _save(fig, out_dir, "fig09_horizon_robustness.png")


def fig10_connector_robustness(results_dir: str, out_dir: str,
                               summary: dict) -> None:
    rows = _effects_rows(results_dir, "campaign_120d")
    con = "certified_green_data_connector"
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    xs = [float(row["connector_coverage_scale"]) for row in rows]
    ys = [float(row[f"effect__exposure_weighted_severity__{con}"])
          for row in rows]
    ax1.scatter(xs, ys, s=12, alpha=0.5, color=REGIME_COLOR[con])
    ax1.axhline(0.0, color="#888888", linewidth=0.8)
    ax1.set_xlabel("sampled connector coverage scale")
    ax1.set_ylabel("connector severity reduction vs baseline")
    ax1.grid(True, linestyle=":", alpha=0.5)
    xs2 = [float(row["connector_register_error_probability"])
           for row in rows]
    ax2.scatter(xs2, ys, s=12, alpha=0.5, color=REGIME_COLOR[con])
    ax2.axhline(0.0, color="#888888", linewidth=0.8)
    ax2.set_xlabel("sampled register-error probability (per transfer)")
    ax2.set_ylabel("connector severity reduction vs baseline")
    ax2.grid(True, linestyle=":", alpha=0.5)
    fig.suptitle("Figure 10. Connector effect vs coverage and "
                 "source-error assumptions", fontsize=11,
                 fontweight="bold")
    _footer(fig, f"Horizon {summary['horizon_days']} days; "
            f"{summary['draws_summarized']} draws x "
            f"{summary['replications']} replications; undiscounted "
            "severity effects (positive = connector better).")
    _save(fig, out_dir, "fig10_connector_robustness.png")


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #
def table_regime_comparison(default: dict, out_dir: str) -> None:
    keys = sorted(next(iter(default["mean_metrics"].values())).keys())
    path = os.path.join(out_dir, "table_regime_comparison.csv")
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric"] + [
            f"{r}__{suffix}" for r in default["mean_metrics"]
            for suffix in ("mean", "ci95")])
        for key in keys:
            row = [key]
            for regime in default["mean_metrics"]:
                row.append(default["mean_metrics"][regime][key])
                row.append(default["ci_halfwidth"][regime][key])
            writer.writerow(row)
    print(f"wrote {path}")


def table_effects_summary(summary: dict, out_dir: str,
                          label: str) -> None:
    path = os.path.join(out_dir, f"table_effects_{label}.csv")
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "regime_vs_baseline", "n_draws",
                         "mean_effect", "sd", "ci95_halfwidth",
                         "prob_improvement", "p05", "p50", "p95"])
        for metric, per_regime in summary["effect_distributions"].items():
            for regime, stats in per_regime.items():
                writer.writerow([
                    metric, regime, int(stats["n"]), stats["mean"],
                    stats["sd"], stats["ci95_halfwidth"],
                    stats["prob_improvement"], stats.get("p05", ""),
                    stats.get("p50", ""), stats.get("p95", "")])
    print(f"wrote {path}")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def generate_all(results_dir: str, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    summary = _load_summary(results_dir, "campaign_120d")
    if summary is None:
        raise SystemExit("campaign_120d summary missing; run the "
                         "sensitivity campaign first")
    default = default_comparison(results_dir)
    fig1_regime_comparison(default, out_dir)
    fig2_itt_vs_tot(default, out_dir)
    fig3_incidence_families(default, out_dir)
    fig4_greenhushing_frontier(results_dir, out_dir, summary)
    fig5_cost_effectiveness(results_dir, out_dir, summary)
    fig6_capacity_backlog(results_dir, out_dir, summary)
    fig7_parameter_importance(summary, out_dir)
    fig8_winner_frequency(summary, out_dir)
    fig9_horizon_robustness(results_dir, out_dir)
    fig10_connector_robustness(results_dir, out_dir, summary)
    table_regime_comparison(default, out_dir)
    table_effects_summary(summary, out_dir, "120d")
    for name in ("campaign_365d", "campaign_1000d", "campaign_2000d"):
        other = _load_summary(results_dir, name)
        if other is not None:
            table_effects_summary(other, out_dir,
                                  name.replace("campaign_", ""))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate publication figures and tables from the "
                    "sensitivity-campaign outputs.")
    parser.add_argument("--results", default="results")
    parser.add_argument("--out", default="results/figures")
    args = parser.parse_args()
    generate_all(args.results, args.out)


if __name__ == "__main__":
    main()
