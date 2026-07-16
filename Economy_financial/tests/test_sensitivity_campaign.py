"""Part J (Workstream A/E) tests: global sensitivity campaign engine.

Reproducibility, stratification, resume-without-corruption, manifest
guards, paired-order invariance, numerical integrity, and registry
round-trips. All runs use tiny horizons so the suite stays fast.
"""

import json
import math
import os
import random

import pytest

from market_sim.parameter_registry import (
    REGISTRY,
    build_simulation_kwargs,
    gsa_defaults,
    gsa_space,
)
from market_sim.sensitivity_campaign import (
    CampaignConfig,
    HEADLINE_METRICS,
    _validate_metrics,
    latin_hypercube_design,
    run_campaign,
    run_one_draw,
    summarize_campaign,
)


def _config(tmp_path, **overrides) -> CampaignConfig:
    base = dict(outdir=str(tmp_path / "campaign"), draws=2,
                replications=2, horizon_days=60, master_seed=99,
                num_traders=8, label="test")
    base.update(overrides)
    return CampaignConfig(**base)


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def test_registry_ids_and_names_unique_and_bounded():
    ids = [spec.parameter_id for spec in REGISTRY]
    names = [spec.name for spec in REGISTRY]
    assert len(set(ids)) == len(ids)
    assert len(set(names)) == len(names)
    for spec in REGISTRY:
        assert spec.classification in {"LEGAL", "LEGAL-ANCHOR",
                                       "STYLIZATION", "EXPERIMENT"}
        assert spec.evidence_class in {
            "legally_mandated", "empirically_estimated",
            "reference_class", "illustrative_scenario"}
        assert spec.source.strip(), spec.parameter_id
        if spec.gsa_eligible:
            assert spec.low is not None and spec.high is not None
            assert spec.low < spec.high
            assert spec.low <= float(spec.default) <= spec.high


def test_no_gsa_parameter_is_legally_mandated():
    """Legal values are never varied by the sensitivity campaign."""
    for spec in REGISTRY:
        if spec.gsa_eligible:
            assert spec.evidence_class != "legally_mandated"
            assert spec.classification not in {"LEGAL", "LEGAL-ANCHOR"}


def test_build_simulation_kwargs_round_trip_defaults():
    kwargs = build_simulation_kwargs(gsa_defaults())
    supervision = kwargs["supervision_parameters"]
    assert supervision.evidence_request_capacity == 20
    assert supervision.investigation_capacity == 5
    assert kwargs["regulatory_strictness"] == pytest.approx(0.55)
    assert kwargs["compliance_burden_scale"] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# LHS design
# --------------------------------------------------------------------------- #
def test_lhs_design_is_reproducible_and_stratified():
    first = latin_hypercube_design(7, 16)
    second = latin_hypercube_design(7, 16)
    assert first == second
    other = latin_hypercube_design(8, 16)
    assert first != other
    space = gsa_space()
    for name, spec in space.items():
        column = sorted(row[name] for row in first)
        low, high = float(spec.low), float(spec.high)
        width = (high - low) / 16
        for index, value in enumerate(column):
            assert low + index * width <= value + 1e-12
            assert value <= low + (index + 1) * width + 1e-12


# --------------------------------------------------------------------------- #
# Determinism and paired-order invariance
# --------------------------------------------------------------------------- #
def test_draw_is_deterministic_and_order_invariant(tmp_path):
    config = _config(tmp_path, draws=1, replications=1)
    design = latin_hypercube_design(config.master_seed, config.draws)
    first = run_one_draw(config, 0, design[0])
    second = run_one_draw(config, 0, design[0])
    assert first["rows"][0]["metrics"] == second["rows"][0]["metrics"]
    # Reversing the regime order must not change any arm's metrics
    # (common random numbers are re-seeded per arm).
    reversed_config = CampaignConfig(
        **{**config.to_dict_kwargs(), "regimes": tuple(
            reversed(config.regimes))}) \
        if hasattr(config, "to_dict_kwargs") else CampaignConfig(
        outdir=config.outdir, draws=config.draws,
        replications=config.replications,
        horizon_days=config.horizon_days,
        master_seed=config.master_seed, num_traders=config.num_traders,
        label=config.label, regimes=tuple(reversed(config.regimes)))
    third = run_one_draw(reversed_config, 0, design[0])
    by_regime_first = {row["regime"]: row["metrics"]
                       for row in first["rows"]}
    by_regime_third = {row["regime"]: row["metrics"]
                       for row in third["rows"]}
    assert by_regime_first == by_regime_third


def test_replications_vary_the_stochastic_environment(tmp_path):
    config = _config(tmp_path, draws=1, replications=2, horizon_days=120)
    design = latin_hypercube_design(config.master_seed, 1)
    payload = run_one_draw(config, 0, design[0])
    baseline_rows = [row for row in payload["rows"]
                     if row["regime"] == config.regimes[0]]
    assert baseline_rows[0]["market_seed"] != baseline_rows[1]["market_seed"]
    assert baseline_rows[0]["metrics"] != baseline_rows[1]["metrics"]


# --------------------------------------------------------------------------- #
# Campaign run, resume, manifest guard
# --------------------------------------------------------------------------- #
def test_campaign_resume_without_corruption(tmp_path):
    config = _config(tmp_path)
    summary = run_campaign(config, progress=False)
    assert summary["draws_summarized"] == 2
    outdir = config.outdir
    with open(os.path.join(outdir, "draw_0001.json")) as handle:
        original = json.load(handle)
    os.remove(os.path.join(outdir, "draw_0001.json"))
    resumed = run_campaign(config, progress=False)
    assert resumed["draws_summarized"] == 2
    with open(os.path.join(outdir, "draw_0001.json")) as handle:
        recomputed = json.load(handle)
    assert recomputed["rows"] == original["rows"]
    assert os.path.exists(os.path.join(outdir, "manifest.json"))
    assert os.path.exists(os.path.join(outdir, "summary.json"))
    assert os.path.exists(os.path.join(outdir, "draw_effects.csv"))


def test_manifest_guard_refuses_conflicting_resume(tmp_path):
    config = _config(tmp_path)
    run_campaign(config, progress=False)
    conflicting = _config(tmp_path, horizon_days=90)
    with pytest.raises(ValueError, match="Resume refused"):
        run_campaign(conflicting, progress=False)


def test_partial_draw_file_is_recomputed(tmp_path):
    config = _config(tmp_path)
    run_campaign(config, progress=False)
    path = os.path.join(config.outdir, "draw_0000.json")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('{"complete": false, "rows": []}')
    resumed = run_campaign(config, progress=False)
    assert resumed["draws_summarized"] == 2
    with open(path) as handle:
        assert json.load(handle)["complete"] is True


# --------------------------------------------------------------------------- #
# Summary content
# --------------------------------------------------------------------------- #
def test_summary_reports_paired_effects_and_importance(tmp_path):
    config = _config(tmp_path, draws=3, horizon_days=120)
    summary = run_campaign(config, progress=False)
    assert summary["weight_sensitive_fraction"] >= 0.0
    for metric in HEADLINE_METRICS:
        assert metric in summary["effect_distributions"]
        for regime, stats in summary["effect_distributions"][
                metric].items():
            assert math.isfinite(stats["mean"])
            assert 0.0 <= stats["prob_improvement"] <= 1.0
    importance = summary["parameter_importance"]
    assert "baseline_exposure_weighted_severity" in importance
    for target, entries in importance.items():
        for name, values in entries.items():
            assert math.isfinite(values["src"])
            assert -1.0 - 1e-9 <= values["prcc"] <= 1.0 + 1e-9
    frequencies = summary["winner_frequency"]["default_experiment"]
    assert sum(frequencies.values()) == summary["draws_summarized"]
    # The manifest records the full design and the seed schedule.
    with open(os.path.join(config.outdir, "manifest.json")) as handle:
        manifest = json.load(handle)
    assert len(manifest["design"]) == config.draws
    assert manifest["config"]["seed_schedule"]


# --------------------------------------------------------------------------- #
# Numerical integrity
# --------------------------------------------------------------------------- #
def test_metric_validation_rejects_nan_and_bad_probability():
    with pytest.raises(ValueError, match="non-finite"):
        _validate_metrics({"anything": float("nan")}, 0, "r", 0)
    with pytest.raises(ValueError, match="out of range"):
        _validate_metrics({"precision": 1.5}, 0, "r", 0)
    _validate_metrics({"precision": 1.0, "recall": 0.0}, 0, "r", 0)


def test_no_truth_leakage_into_simulation_kwargs():
    kwargs = build_simulation_kwargs(gsa_defaults())
    flat = repr(kwargs)
    assert "truth" not in flat
    assert "_evaluation" not in flat
