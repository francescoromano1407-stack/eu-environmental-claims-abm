"""Part J (Workstream A): global sensitivity-analysis campaign.

A reproducible Latin-hypercube campaign over the GSA-eligible parameter
space of `parameter_registry.py`:

* >= 200 parameter draws by default, each evaluated with >= 3 PAIRED
  replications (common random numbers across regimes WITHIN each
  replication; independent stochastic environments ACROSS replications
  and draws, on a transparent seed schedule);
* per-draw JSON result files written atomically, so an interrupted
  campaign resumes without corrupting or recomputing prior valid draws;
* a machine-readable campaign manifest (master seed, full design matrix,
  replication seed schedule, horizon, discount-rate handling, code
  version, regime identifiers);
* robust summaries: paired-effect distributions, probabilities of
  improvement, confidence intervals, rank and winner frequencies, Pareto
  frequencies, weight-sensitivity fractions, and parameter-importance
  estimates (standardized regression coefficients on sampled inputs and
  partial rank correlation coefficients).

The campaign measures MODEL ROBUSTNESS AND PARAMETER DEPENDENCE. It does
not identify causal effects of real-world policies, and no result of it
is an empirical prediction.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

from market_sim.parameter_registry import (
    build_simulation_kwargs,
    gsa_space,
)
from market_sim.policy_comparison import (
    DEFAULT_WEIGHT_SCENARIOS,
    PolicyOutcomeEvaluator,
    composite_scores,
    pareto_frontier,
)
from market_sim.policy_regimes import GreenwashingPolicyRegime

DEFAULT_REGIMES: tuple[str, ...] = (
    GreenwashingPolicyRegime.CURRENT_EU_SUPERVISION.value,
    GreenwashingPolicyRegime.SME_ALGORITHMIC_PRESCREENING.value,
    GreenwashingPolicyRegime.CERTIFIED_GREEN_DATA_CONNECTOR.value,
)

# Headline lower-is-better outcomes for paired contrasts.
HEADLINE_METRICS: tuple[str, ...] = (
    "original_material_overstatements",
    "exposure_weighted_severity",
    "discounted_exposure_weighted_severity",
    "misleading_claim_days",
    "mean_greenhushing_gap",
    "discounted_total_public_cost",
    "sme_burden",
    "consumer_perceived_misallocation",
    "investor_signal_distortion",
    "turnover_replacement_cost",
    "backlog_pending_cases",
    "queue_mean_age_days",
    "case_completion_days_mean",
    "conflict_resolution_delay_mean",
)
# Higher-is-better outcomes reported alongside.
HEADLINE_HIGHER: tuple[str, ...] = (
    "population_detection_recall",
    "screening_conditioned_precision",
    "green_welfare_share",
    "employee_trust_mean",
    "voluntary_claims_published",
    "real_environmental_investment",
)


def _git_version() -> str:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            timeout=10, check=True).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True,
            text=True, timeout=10, check=True).stdout.strip()
        return head + ("+dirty" if dirty else "")
    except Exception:
        return "unknown"


def latin_hypercube_design(seed: int, draws: int) \
        -> list[dict[str, float]]:
    """Stratified LHS over the registry's GSA space: one draw per bin per
    dimension, independently permuted across dimensions. Integer
    parameters are rounded at APPLICATION time (the design keeps the raw
    stratified value for reproducibility)."""
    rng = random.Random(seed)
    space = gsa_space()
    columns: dict[str, list[float]] = {}
    for name, spec in space.items():
        points = [(index + rng.random()) / draws for index in range(draws)]
        rng.shuffle(points)
        low, high = float(spec.low), float(spec.high)
        columns[name] = [low + point * (high - low) for point in points]
    return [{name: columns[name][index] for name in space}
            for index in range(draws)]


@dataclass(frozen=True)
class CampaignConfig:
    outdir: str
    draws: int = 200
    replications: int = 3
    horizon_days: int = 120
    master_seed: int = 20260716
    supervision_base_seed: int = 104729
    regimes: tuple[str, ...] = DEFAULT_REGIMES
    num_traders: int = 8
    num_manipulators: int = 0
    enable_credit: bool = False
    label: str = "campaign"
    subset: Optional[tuple[int, ...]] = None   # Draw indices to run.

    def market_seed(self, draw: int, replication: int) -> int:
        return (self.master_seed + 1_000_000 * draw
                + 1_000 * replication)

    def supervision_seed(self, draw: int, replication: int) -> int:
        return (self.supervision_base_seed + 104_729 * draw
                + 7_919 * replication)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label, "outdir": self.outdir,
            "draws": self.draws, "replications": self.replications,
            "horizon_days": self.horizon_days,
            "master_seed": self.master_seed,
            "supervision_base_seed": self.supervision_base_seed,
            "seed_schedule": {
                "market_seed": "master_seed + 1000000*draw + 1000*rep",
                "supervision_seed":
                    "supervision_base_seed + 104729*draw + 7919*rep",
            },
            "regimes": list(self.regimes),
            "num_traders": self.num_traders,
            "num_manipulators": self.num_manipulators,
            "enable_credit": self.enable_credit,
            "subset": list(self.subset) if self.subset else None,
            "discount_rate": "sampled per draw "
                             "(social_discount_rate dimension)",
        }


def _atomic_write_json(path: str, payload: Mapping[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, sort_keys=True)
    os.replace(tmp, path)


def _draw_path(outdir: str, draw: int) -> str:
    return os.path.join(outdir, f"draw_{draw:04d}.json")


def _failure_path(outdir: str) -> str:
    """Location of the atomic failed-run ledger for one campaign."""
    return os.path.join(outdir, "failed_runs.json")


def _record_failure(outdir: str, draw: int, error: Exception) -> None:
    """Append-or-replace a failed-draw record without risking a torn log.

    A failed draw is deliberately not marked complete.  On a later resume it
    is attempted again, while this ledger retains the prior failure for the
    reproducibility record.  The small JSON list is rewritten atomically so a
    power loss cannot corrupt previously recorded failures.
    """
    path = _failure_path(outdir)
    records: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, list):
            records = loaded
    except (OSError, json.JSONDecodeError):
        pass
    records.append({
        "draw": draw,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                        time.gmtime()),
        "error_type": type(error).__name__,
        "error": str(error),
    })
    _atomic_write_json(path, records)


def validate_draw_payload(payload: Any, config: CampaignConfig, draw: int,
                          sample: Mapping[str, float]) -> tuple[bool, str]:
    """Validate one atomic draw against the exact paired campaign design.

    ``complete: true`` is deliberately insufficient.  A resumable campaign
    must not silently accept a file produced with a different LHS point,
    horizon, replication schedule, regime set, or random-number stream.
    The reason string is intended for inspection manifests and dry-run logs.
    """
    if not isinstance(payload, dict):
        return False, "payload is not a JSON object"
    if payload.get("complete") is not True:
        return False, "draw is not marked complete"
    expected_sample = dict(sample)
    identity = (
        ("draw", draw),
        ("sample", expected_sample),
        ("horizon_days", config.horizon_days),
        ("replications", config.replications),
        ("regimes", list(config.regimes)),
    )
    for key, expected in identity:
        if payload.get(key) != expected:
            return False, f"{key} mismatch"
    expected_discount = float(expected_sample["social_discount_rate"])
    try:
        observed_discount = float(payload.get("discount_rate"))
    except (TypeError, ValueError):
        return False, "discount_rate is missing or non-numeric"
    if not math.isclose(observed_discount, expected_discount,
                        rel_tol=0.0, abs_tol=1e-15):
        return False, "discount_rate does not match the LHS point"
    rows = payload.get("rows")
    expected_count = config.replications * len(config.regimes)
    if not isinstance(rows, list) or len(rows) != expected_count:
        return False, f"expected {expected_count} regime-replication rows"
    expected_rows = {
        (replication, regime): (
            config.market_seed(draw, replication),
            config.supervision_seed(draw, replication),
        )
        for replication in range(config.replications)
        for regime in config.regimes
    }
    observed: set[tuple[int, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            return False, "a run row is not a JSON object"
        key = (row.get("replication"), row.get("regime"))
        if key not in expected_rows:
            return False, "unexpected regime-replication row"
        if key in observed:
            return False, "duplicate regime-replication row"
        if (row.get("market_seed"), row.get("supervision_seed")) \
                != expected_rows[key]:
            return False, "market or supervision seed mismatch"
        metrics = row.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            return False, "metrics are missing or empty"
        try:
            if not all(math.isfinite(float(value))
                       for value in metrics.values()):
                return False, "metrics contain NaN or infinity"
        except (TypeError, ValueError):
            return False, "metrics contain a non-numeric value"
        observed.add(key)
    if observed != set(expected_rows):
        return False, "regime-replication schedule is incomplete"
    return True, "valid"


def _load_valid_draw(path: str, config: Optional[CampaignConfig] = None,
                     draw: Optional[int] = None,
                     sample: Optional[Mapping[str, float]] = None
                     ) -> Optional[dict[str, Any]]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        if config is not None:
            if draw is None or sample is None:
                raise ValueError("strict draw validation needs draw and sample")
            valid, _ = validate_draw_payload(payload, config, draw, sample)
            return payload if valid else None
        if isinstance(payload, dict) and payload.get("complete") is True:
            return payload
    except (json.JSONDecodeError, OSError):
        return None
    return None


def run_replication_rows(config: CampaignConfig, draw: int,
                         sample: Mapping[str, float],
                         replications: Iterable[int]) -> list[dict[str, Any]]:
    """Run selected paired replications without repeating existing ones."""
    from market_sim.simulation import Simulation   # Local: avoid cycles.

    discount = float(sample["social_discount_rate"])
    evaluator = PolicyOutcomeEvaluator(discount_rate_annual=discount)
    kwargs = build_simulation_kwargs(sample)
    rows: list[dict[str, Any]] = []
    for replication in replications:
        if replication < 0:
            raise ValueError("replication indices must be non-negative")
        market_seed = config.market_seed(draw, replication)
        supervision_seed = config.supervision_seed(draw, replication)
        for regime in config.regimes:
            random.seed(market_seed)
            sim = Simulation(
                days=config.horizon_days,
                num_traders=config.num_traders,
                num_manipulators=config.num_manipulators,
                enable_credit=config.enable_credit,
                enable_esg=True,
                enable_greenwashing_supervision=True,
                supervision_seed=supervision_seed,
                greenwashing_policy_regime=GreenwashingPolicyRegime(
                    regime),
                **kwargs)
            sim.run()
            metrics = evaluator.evaluate(sim)
            _validate_metrics(metrics, draw, regime, replication)
            rows.append({
                "regime": regime, "replication": replication,
                "market_seed": market_seed,
                "supervision_seed": supervision_seed,
                "metrics": metrics,
            })
    return rows


def run_one_draw(config: CampaignConfig, draw: int,
                 sample: Mapping[str, float]) -> dict[str, Any]:
    """Run all paired replications of one parameter draw."""
    rows = run_replication_rows(
        config, draw, sample, range(config.replications))
    discount = float(sample["social_discount_rate"])
    return {
        "complete": True,
        "draw": draw,
        "sample": dict(sample),
        "horizon_days": config.horizon_days,
        "discount_rate": discount,
        "replications": config.replications,
        "regimes": list(config.regimes),
        "code_version": _git_version(),
        "rows": rows,
    }


def _validate_metrics(metrics: Mapping[str, float], draw: int,
                      regime: str, replication: int) -> None:
    """Numerical integrity: no NaN/Inf, probabilities in [0, 1]."""
    probability_keys = (
        "precision", "recall", "specificity",
        "population_detection_recall", "detection_coverage",
        "severity_weighted_detection_recall",
        "false_positive_rate_assessed", "green_welfare_share",
        "hub_participation_rate", "employee_trust_mean")
    for key, value in metrics.items():
        if not math.isfinite(float(value)):
            raise ValueError(
                f"non-finite metric {key}={value} (draw {draw}, "
                f"{regime}, rep {replication})")
    for key in probability_keys:
        value = float(metrics.get(key, 0.0))
        if not -1e-9 <= value <= 1.0 + 1e-9:
            raise ValueError(
                f"probability metric out of range {key}={value} "
                f"(draw {draw}, {regime}, rep {replication})")


def run_campaign(config: CampaignConfig,
                 progress: bool = True) -> dict[str, Any]:
    """Execute (or resume) a campaign; returns the summary payload."""
    os.makedirs(config.outdir, exist_ok=True)
    design = latin_hypercube_design(config.master_seed, config.draws)
    manifest = {
        "config": config.to_dict(),
        "code_version": _git_version(),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "space": {name: {"low": spec.low, "high": spec.high,
                         "default": spec.default,
                         "integer": spec.integer,
                         "classification": spec.classification}
                  for name, spec in gsa_space().items()},
        "design": design,
        "seed_schedule_example": {
            "draw0_rep0": {
                "market_seed": config.market_seed(0, 0),
                "supervision_seed": config.supervision_seed(0, 0)},
            "draw1_rep2": {
                "market_seed": config.market_seed(1, 2),
                "supervision_seed": config.supervision_seed(1, 2)},
        },
    }
    manifest_path = os.path.join(config.outdir, "manifest.json")
    existing = None
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as handle:
                existing = json.load(handle)
        except (json.JSONDecodeError, OSError):
            existing = None
    if existing is not None:
        prior = dict(existing.get("config", {}))
        current = config.to_dict()
        for key in ("draws", "replications", "horizon_days",
                    "master_seed", "supervision_base_seed", "regimes"):
            if prior.get(key) != current.get(key):
                raise ValueError(
                    f"Resume refused: existing manifest differs on "
                    f"'{key}' ({prior.get(key)} != {current.get(key)}). "
                    "Use a fresh --outdir for a different design.")
    else:
        _atomic_write_json(manifest_path, manifest)

    indices = list(config.subset) if config.subset \
        else list(range(config.draws))
    started = time.time()
    completed = 0
    skipped = 0
    for draw in indices:
        path = _draw_path(config.outdir, draw)
        if _load_valid_draw(path, config, draw, design[draw]) is not None:
            skipped += 1
            continue
        try:
            payload = run_one_draw(config, draw, design[draw])
            _atomic_write_json(path, payload)
            completed += 1
        except Exception as error:
            _record_failure(config.outdir, draw, error)
            raise
        if progress and (completed % 10 == 0 or completed == 1):
            elapsed = time.time() - started
            rate = completed / max(elapsed, 1e-9)
            remaining = (len(indices) - skipped - completed) / max(rate,
                                                                   1e-9)
            print(f"[{config.label}] draw {draw}: {completed} run, "
                  f"{skipped} resumed, ~{remaining/60:.1f} min left",
                  flush=True)
    summary = summarize_campaign(config.outdir, config=config)
    if progress:
        print(f"[{config.label}] finished: {completed} new draws, "
              f"{skipped} resumed, "
              f"{time.time()-started:.0f}s", flush=True)
    return summary


# --------------------------------------------------------------------------- #
# Summaries
# --------------------------------------------------------------------------- #
def _quantiles(values: Sequence[float]) -> dict[str, float]:
    ordered = sorted(values)
    n = len(ordered)

    def q(p: float) -> float:
        if n == 1:
            return ordered[0]
        position = p * (n - 1)
        lower = int(position)
        upper = min(n - 1, lower + 1)
        weight = position - lower
        return ordered[lower] * (1 - weight) + ordered[upper] * weight

    return {"p05": q(0.05), "p25": q(0.25), "p50": q(0.50),
            "p75": q(0.75), "p95": q(0.95)}


def _paired_summary(diffs: Sequence[float]) -> dict[str, float]:
    n = len(diffs)
    mean = statistics.fmean(diffs) if diffs else 0.0
    sd = statistics.stdev(diffs) if n > 1 else 0.0
    ci = 1.96 * sd / math.sqrt(n) if n > 1 else 0.0
    result = {"n": float(n), "mean": mean, "sd": sd,
              "ci95_halfwidth": ci,
              "prob_improvement": (sum(d > 0 for d in diffs) / n)
              if n else 0.0}
    result.update(_quantiles(diffs) if diffs else {})
    return result


def _importance(design_rows: list[dict[str, float]],
                outcomes: list[float]) -> dict[str, dict[str, float]]:
    """Parameter importance for one outcome across draws.

    * SRC: standardized regression coefficients from an OLS of the
      standardized outcome on all standardized inputs jointly.
    * PRCC: partial rank correlation coefficients (rank-transformed
      inputs/outcome; correlation of residuals after regressing out all
      other inputs).
    Both are appropriate to a near-orthogonal LHS design and are reported
    together; neither implies causal identification.
    """
    import numpy as np

    names = sorted(design_rows[0].keys())
    X = np.array([[row[name] for name in names] for row in design_rows],
                 dtype=float)
    y = np.array(outcomes, dtype=float)
    keep = [i for i in range(X.shape[1]) if X[:, i].std() > 1e-12]
    names = [names[i] for i in keep]
    X = X[:, keep]

    def _standardize(matrix: "np.ndarray") -> "np.ndarray":
        return (matrix - matrix.mean(axis=0)) \
            / np.where(matrix.std(axis=0) > 1e-12, matrix.std(axis=0), 1.0)

    result: dict[str, dict[str, float]] = {}
    if y.std() <= 1e-12:
        return {name: {"src": 0.0, "prcc": 0.0} for name in names}
    Xs = _standardize(X)
    ys = (y - y.mean()) / y.std()
    design = np.column_stack([np.ones(len(ys)), Xs])
    beta, *_ = np.linalg.lstsq(design, ys, rcond=None)
    src = beta[1:]

    ranks_X = np.argsort(np.argsort(X, axis=0), axis=0).astype(float)
    ranks_y = np.argsort(np.argsort(y)).astype(float)
    Rs = _standardize(ranks_X)
    rys = (ranks_y - ranks_y.mean()) / max(ranks_y.std(), 1e-12)
    for index, name in enumerate(names):
        others = np.delete(Rs, index, axis=1)
        base = np.column_stack([np.ones(len(rys)), others])
        bx, *_ = np.linalg.lstsq(base, Rs[:, index], rcond=None)
        by, *_ = np.linalg.lstsq(base, rys, rcond=None)
        res_x = Rs[:, index] - base @ bx
        res_y = rys - base @ by
        denom = np.linalg.norm(res_x) * np.linalg.norm(res_y)
        prcc = float(res_x @ res_y / denom) if denom > 1e-12 else 0.0
        result[name] = {"src": float(src[index]), "prcc": prcc}
    return result


def _importance_diagnostics(design_rows: list[dict[str, float]],
                            outcomes: list[float]) -> dict[str, Any]:
    """Transparent limitations accompanying every global-importance fit.

    The campaign reports these diagnostic values instead of silently
    treating a linear, rank-linear approximation as a causal model.  A high
    condition number signals collinearity; a low R-squared signals that SRC
    is a weak summary of a nonlinear or interaction-heavy response.
    """
    import numpy as np

    names = sorted(design_rows[0])
    X = np.array([[row[name] for name in names] for row in design_rows],
                 dtype=float)
    y = np.array(outcomes, dtype=float)
    X = (X - X.mean(axis=0)) / np.where(X.std(axis=0) > 1e-12,
                                        X.std(axis=0), 1.0)
    design = np.column_stack([np.ones(len(X)), X])
    coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
    fitted = design @ coefficients
    total = float(np.sum((y - y.mean()) ** 2))
    residual = float(np.sum((y - fitted) ** 2))
    condition = float(np.linalg.cond(design))
    r_squared = 1.0 - residual / total if total > 1e-12 else 0.0
    warnings: list[str] = [
        "Associational model-sensitivity result, not a causal estimate.",
        "SRC is linear and PRCC is monotonic/rank-linear; interactions and nonlinearity can be missed.",
    ]
    if condition > 30.0:
        warnings.append(f"Potential collinearity: design condition number {condition:.2f} > 30.")
    if r_squared < 0.20:
        warnings.append(f"Weak linear explanatory power: R-squared {r_squared:.3f} < 0.20.")
    if len(outcomes) < 30:
        warnings.append("Small effective sample for a global importance fit (<30 draws).")
    return {"n_draws": len(outcomes), "r_squared": r_squared,
            "condition_number": condition, "warnings": warnings}


def summarize_campaign(outdir: str, write: bool = True,
                       config: Optional[CampaignConfig] = None
                       ) -> dict[str, Any]:
    """Aggregate all valid draw files in `outdir` into the campaign
    summary (paired contrasts, rank/winner/Pareto frequencies,
    weight-sensitivity fraction, parameter importance)."""
    draws: list[dict[str, Any]] = []
    design = (latin_hypercube_design(config.master_seed, config.draws)
              if config is not None else None)
    for name in sorted(os.listdir(outdir)):
        if name.startswith("draw_") and name.endswith(".json"):
            draw_number = int(name[5:-5])
            payload = _load_valid_draw(
                os.path.join(outdir, name), config, draw_number,
                design[draw_number] if design is not None
                and 0 <= draw_number < len(design) else None,
            ) if config is not None and 0 <= draw_number < len(design) \
                else _load_valid_draw(os.path.join(outdir, name))
            if payload is not None:
                draws.append(payload)
    if not draws:
        raise ValueError(f"no valid draw files in {outdir}")

    regimes = draws[0]["regimes"]
    baseline = regimes[0]
    scenario_names = [w.name for w in DEFAULT_WEIGHT_SCENARIOS]

    per_draw: list[dict[str, Any]] = []
    for payload in draws:
        rows = payload["rows"]
        mean_metrics: dict[str, dict[str, float]] = {}
        for regime in regimes:
            samples = [row["metrics"] for row in rows
                       if row["regime"] == regime]
            mean_metrics[regime] = {
                key: statistics.fmean(sample[key] for sample in samples)
                for key in samples[0]}
        scores = {name: composite_scores(
            mean_metrics, weights)
            for name, weights in zip(
                scenario_names, DEFAULT_WEIGHT_SCENARIOS)}
        winners = {name: max(sc, key=sc.get)
                   for name, sc in scores.items()}
        rankings = {name: sorted(sc, key=sc.get, reverse=True)
                    for name, sc in scores.items()}
        pareto = sorted(pareto_frontier(mean_metrics))
        contrasts: dict[str, dict[str, list[float]]] = {}
        for metric in HEADLINE_METRICS + HEADLINE_HIGHER:
            per_regime: dict[str, list[float]] = {}
            for regime in regimes[1:]:
                diffs = []
                for replication in range(payload["replications"]):
                    base_row = next(
                        row for row in rows
                        if row["regime"] == baseline
                        and row["replication"] == replication)
                    policy_row = next(
                        row for row in rows
                        if row["regime"] == regime
                        and row["replication"] == replication)
                    base_value = base_row["metrics"].get(metric, 0.0)
                    policy_value = policy_row["metrics"].get(metric, 0.0)
                    # Positive = the policy regime improves the outcome.
                    if metric in HEADLINE_HIGHER:
                        diffs.append(policy_value - base_value)
                    else:
                        diffs.append(base_value - policy_value)
                per_regime[regime] = diffs
            contrasts[metric] = per_regime
        per_draw.append({
            "draw": payload["draw"], "sample": payload["sample"],
            "winners": winners, "rankings": rankings, "pareto": pareto,
            "weight_sensitive": len(set(winners.values())) > 1,
            "contrasts": {
                metric: {regime: statistics.fmean(diffs)
                         for regime, diffs in per_regime.items()}
                for metric, per_regime in contrasts.items()},
            "mean_metrics": mean_metrics,
        })

    # Winner and rank frequencies.
    winner_frequency: dict[str, dict[str, int]] = {
        name: {regime: 0 for regime in regimes}
        for name in scenario_names}
    rank_frequency: dict[str, dict[str, list[int]]] = {
        name: {regime: [0] * len(regimes) for regime in regimes}
        for name in scenario_names}
    pareto_frequency = {regime: 0 for regime in regimes}
    weight_sensitive = 0
    for item in per_draw:
        for name in scenario_names:
            winner_frequency[name][item["winners"][name]] += 1
            for position, regime in enumerate(item["rankings"][name]):
                rank_frequency[name][regime][position] += 1
        for regime in item["pareto"]:
            pareto_frequency[regime] += 1
        weight_sensitive += bool(item["weight_sensitive"])

    # Paired-effect distributions across draws (of per-draw mean diffs).
    effect_distributions: dict[str, dict[str, dict[str, float]]] = {}
    for metric in HEADLINE_METRICS + HEADLINE_HIGHER:
        per_regime = {}
        for regime in regimes[1:]:
            values = [item["contrasts"][metric][regime]
                      for item in per_draw]
            per_regime[regime] = _paired_summary(values)
        effect_distributions[metric] = per_regime

    # Parameter importance for headline outcomes.
    design_rows = [item["sample"] for item in per_draw]
    importance: dict[str, Any] = {}
    importance_targets = {
        "baseline_exposure_weighted_severity": [
            item["mean_metrics"][baseline]["exposure_weighted_severity"]
            for item in per_draw],
        "baseline_greenhushing_gap": [
            item["mean_metrics"][baseline]["mean_greenhushing_gap"]
            for item in per_draw],
    }
    for regime in regimes[1:]:
        importance_targets[f"effect_severity_{regime}"] = [
            item["contrasts"]["exposure_weighted_severity"][regime]
            for item in per_draw]
        importance_targets[f"effect_greenhushing_{regime}"] = [
            item["contrasts"]["mean_greenhushing_gap"][regime]
            for item in per_draw]
        importance_targets[f"effect_total_cost_{regime}"] = [
            (item["mean_metrics"][baseline]["discounted_total_public_cost"]
             + item["mean_metrics"][baseline]["firm_policy_cost"]
             + item["mean_metrics"][baseline]["firm_reporting_cost"])
            - (item["mean_metrics"][regime]["discounted_total_public_cost"]
               + item["mean_metrics"][regime]["firm_policy_cost"]
               + item["mean_metrics"][regime]["firm_reporting_cost"])
            for item in per_draw]
    default_scenario = "default_experiment"
    for regime in regimes:
        importance_targets[f"rank_default_{regime}"] = [
            -float(item["rankings"][default_scenario].index(regime))
            for item in per_draw]
        importance_targets[f"winner_default_{regime}"] = [
            float(item["winners"][default_scenario] == regime)
            for item in per_draw]
        importance_targets[f"pareto_membership_{regime}"] = [
            float(regime in item["pareto"]) for item in per_draw]
    for target, values in importance_targets.items():
        importance[target] = _importance(design_rows, values)
    importance_diagnostics = {
        target: _importance_diagnostics(design_rows, values)
        for target, values in importance_targets.items()
    }

    summary = {
        "outdir": outdir,
        "draws_summarized": len(per_draw),
        "replications": draws[0]["replications"],
        "horizon_days": draws[0]["horizon_days"],
        "regimes": regimes,
        "baseline": baseline,
        "code_version": _git_version(),
        "note": ("Simulation outputs under stylized parameters; measures "
                 "model robustness and parameter dependence, NOT causal "
                 "or empirical policy effects."),
        "winner_frequency": winner_frequency,
        "rank_frequency": rank_frequency,
        "pareto_frequency": pareto_frequency,
        "weight_sensitive_fraction": weight_sensitive / len(per_draw),
        "effect_distributions": effect_distributions,
        "parameter_importance": importance,
        "parameter_importance_diagnostics": importance_diagnostics,
        "per_draw": per_draw,
    }
    if write:
        _atomic_write_json(os.path.join(outdir, "summary.json"), summary)
        _write_effects_csv(outdir, per_draw, regimes)
    return summary


def _write_effects_csv(outdir: str, per_draw: list[dict[str, Any]],
                       regimes: list[str]) -> None:
    """Flat per-draw table for external analysis and figures."""
    import csv as _csv

    parameter_names = sorted(per_draw[0]["sample"].keys())
    metric_names = list(HEADLINE_METRICS + HEADLINE_HIGHER)
    path = os.path.join(outdir, "draw_effects.csv")
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = _csv.writer(handle)
        header = ["draw"] + parameter_names \
            + [f"winner__{name}" for name in
               (w.name for w in DEFAULT_WEIGHT_SCENARIOS)] \
            + ["weight_sensitive", "pareto"]
        for regime in regimes[1:]:
            header += [f"effect__{metric}__{regime}"
                       for metric in metric_names]
        for regime in regimes:
            header += [f"level__{metric}__{regime}"
                       for metric in metric_names]
        writer.writerow(header)
        for item in per_draw:
            row: list[Any] = [item["draw"]]
            row += [item["sample"][name] for name in parameter_names]
            row += [item["winners"][name] for name in
                    (w.name for w in DEFAULT_WEIGHT_SCENARIOS)]
            row += [item["weight_sensitive"], "|".join(item["pareto"])]
            for regime in regimes[1:]:
                row += [item["contrasts"][metric][regime]
                        for metric in metric_names]
            for regime in regimes:
                row += [item["mean_metrics"][regime].get(metric, "")
                        for metric in metric_names]
            writer.writerow(row)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Global sensitivity campaign (LHS, paired "
                    "replications, resumable).")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--draws", type=int, default=200)
    parser.add_argument("--replications", type=int, default=3)
    parser.add_argument("--horizon", type=int, default=120)
    parser.add_argument("--master-seed", type=int, default=20260716)
    parser.add_argument("--num-traders", type=int, default=8)
    parser.add_argument("--label", default="campaign")
    parser.add_argument("--include-hybrid", action="store_true",
                        help="Add the hybrid arm to the comparison.")
    parser.add_argument("--subset", default=None,
                        help="Comma-separated draw indices to run "
                             "(e.g. confirmation campaigns).")
    parser.add_argument("--summary-only", action="store_true",
                        help="Only aggregate existing draw files.")
    args = parser.parse_args(argv)

    regimes = list(DEFAULT_REGIMES)
    if args.include_hybrid:
        regimes.append(
            GreenwashingPolicyRegime
            .HYBRID_PRESCREENING_AND_CONNECTOR.value)
    subset = tuple(int(part) for part in args.subset.split(",")) \
        if args.subset else None
    config = CampaignConfig(
        outdir=args.outdir, draws=args.draws,
        replications=args.replications, horizon_days=args.horizon,
        master_seed=args.master_seed, num_traders=args.num_traders,
        label=args.label, regimes=tuple(regimes), subset=subset)
    if args.summary_only:
        summarize_campaign(args.outdir)
    else:
        run_campaign(config)


if __name__ == "__main__":
    main()
