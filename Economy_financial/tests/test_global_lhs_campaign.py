"""Contract tests for the top-level publication-campaign driver.

These use no simulation runs; engine behaviour remains covered by the
existing sensitivity-campaign tests.
"""

import json

import pytest

from market_sim.sensitivity_campaign import (CampaignConfig, DEFAULT_REGIMES,
                                              latin_hypercube_design)
from run_global_lhs_campaign import (HorizonPlan, build_parser,
                                     hydrate_completed_draws, initialise,
                                     inspect_completed_draws, main,
                                     planned_horizons)


def test_default_design_meets_publication_minimums():
    args = build_parser().parse_args([])
    assert args.draws >= 200
    assert args.replications >= 3
    assert args.horizon >= 120
    assert [plan.days for plan in planned_horizons(args)] == [120, 365, 1000, 2000]
    assert args.execute_missing is False


def test_confirmation_is_a_complete_365_day_design():
    args = build_parser().parse_args(["--confirmation"])
    plan = planned_horizons(args)[1]
    assert plan.days == 365
    assert plan.subset is None


def test_initialisation_writes_required_artifact_contract(tmp_path):
    args = build_parser().parse_args([])
    run_dir = tmp_path / "campaign"
    config = initialise(run_dir, args, planned_horizons(args))
    assert config["regimes"] == ["current_eu_supervision", "sme_algorithmic_prescreening", "certified_green_data_connector"]
    for path in ("manifest.json", "configuration.json", "README.md", "logs", "raw", "summaries", "figures"):
        assert (run_dir / path).exists()
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["configuration"]["seed_schedule"]["common_random_numbers"]


def test_full_robustness_targets_every_draw_at_every_horizon():
    args = build_parser().parse_args(["--full-robustness"])
    plans = planned_horizons(args)
    assert [plan.days for plan in plans] == [120, 365, 1000, 2000]
    assert all(plan.subset is None for plan in plans)


def _payload(config, draw, sample):
    rows = []
    for replication in range(config.replications):
        for regime in config.regimes:
            rows.append({
                "regime": regime, "replication": replication,
                "market_seed": config.market_seed(draw, replication),
                "supervision_seed": config.supervision_seed(draw, replication),
                "metrics": {"finite_fixture_metric": 1.0},
            })
    return {
        "complete": True, "draw": draw, "sample": sample,
        "horizon_days": config.horizon_days,
        "discount_rate": sample["social_discount_rate"],
        "replications": config.replications,
        "regimes": list(config.regimes), "rows": rows,
    }


def test_matching_valid_draw_is_imported_atomically_without_running(tmp_path):
    existing_root = tmp_path / "results"
    legacy = existing_root / "campaign_365d"
    legacy.mkdir(parents=True)
    destination = tmp_path / "run" / "raw" / "robustness_365d"
    config = CampaignConfig(
        outdir=str(destination), draws=2, replications=3, horizon_days=365,
        master_seed=42, supervision_base_seed=7, regimes=DEFAULT_REGIMES,
    )
    design = latin_hypercube_design(config.master_seed, config.draws)
    (legacy / "manifest.json").write_text(json.dumps({"config": config.to_dict()}), encoding="utf-8")
    (legacy / "draw_0000.json").write_text(json.dumps(_payload(config, 0, design[0])), encoding="utf-8")
    destination.mkdir(parents=True)
    (destination / "manifest.json").write_text(json.dumps({"config": config.to_dict()}), encoding="utf-8")
    args = build_parser().parse_args(["--existing-root", str(existing_root)])
    reused = hydrate_completed_draws(args, tmp_path / "run", destination,
                                    HorizonPlan(365, "robustness_365d", None), config)
    assert reused["imported_draws"] == 1
    assert reused["valid_existing_draws"] == 0
    assert json.loads((destination / "draw_0000.json").read_text(encoding="utf-8"))["complete"] is True
    resumed = hydrate_completed_draws(args, tmp_path / "run", destination,
                                      HorizonPlan(365, "robustness_365d", None), config)
    assert resumed["imported_draws"] == 0
    assert resumed["valid_existing_draws"] == 1


def test_mismatched_or_corrupt_draws_are_not_reused(tmp_path):
    existing_root = tmp_path / "results"
    legacy = existing_root / "campaign_1000d"
    legacy.mkdir(parents=True)
    destination = tmp_path / "run" / "raw" / "robustness_1000d"
    config = CampaignConfig(
        outdir=str(destination), draws=2, replications=3, horizon_days=1000,
        master_seed=42, supervision_base_seed=7, regimes=DEFAULT_REGIMES,
    )
    wrong = config.to_dict()
    wrong["master_seed"] = 43
    (legacy / "manifest.json").write_text(json.dumps({"config": wrong}), encoding="utf-8")
    design = latin_hypercube_design(config.master_seed, config.draws)
    broken = _payload(config, 0, design[0])
    broken["rows"][0]["market_seed"] = -1
    (legacy / "draw_0000.json").write_text(json.dumps(broken), encoding="utf-8")
    args = build_parser().parse_args(["--existing-root", str(existing_root)])
    reused = hydrate_completed_draws(args, tmp_path / "run", destination,
                                    HorizonPlan(1000, "robustness_1000d", None), config)
    assert reused["imported_draws"] == 0
    assert not (destination / "draw_0000.json").exists()


def test_read_only_inspection_reports_exact_missing_and_invalid_draws(tmp_path):
    destination = tmp_path / "run" / "raw" / "horizon_120d"
    destination.mkdir(parents=True)
    config = CampaignConfig(
        outdir=str(destination), draws=3, replications=1,
        horizon_days=120, master_seed=42, supervision_base_seed=7,
        regimes=DEFAULT_REGIMES,
    )
    design = latin_hypercube_design(config.master_seed, config.draws)
    (destination / "manifest.json").write_text(
        json.dumps({"config": config.to_dict()}), encoding="utf-8")
    (destination / "draw_0000.json").write_text(
        json.dumps(_payload(config, 0, design[0])), encoding="utf-8")
    (destination / "draw_0001.json").write_text("{broken", encoding="utf-8")
    args = build_parser().parse_args([
        "--development", "--draws", "3", "--replications", "1",
        "--base-horizon-only", "--existing-root", str(tmp_path / "none"),
    ])
    audit = inspect_completed_draws(
        args, tmp_path / "run", destination,
        HorizonPlan(120, "horizon_120d", None), config)
    assert audit["valid_existing_draw_ids"] == [0]
    assert [item["draw"] for item in audit["missing_or_invalid_draws"]] == [1, 2]
    assert "corrupt JSON" in audit["missing_or_invalid_draws"][0]["reason"]
    assert audit["missing_or_invalid_draws"][1]["reason"] == "file is missing"


def test_cli_defaults_to_non_mutating_dry_run(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run must not execute the campaign")

    monkeypatch.setattr("run_global_lhs_campaign.run_campaign", forbidden)
    output_root = tmp_path / "campaigns"
    main([
        "--development", "--draws", "2", "--replications", "1",
        "--base-horizon-only", "--existing-root", str(tmp_path / "none"),
        "--output-root", str(output_root),
    ])
    assert not output_root.exists()


def test_rebuild_only_refuses_when_simulations_are_missing(tmp_path):
    with pytest.raises(ValueError, match="requires simulation"):
        main([
            "--development", "--draws", "2", "--replications", "1",
            "--base-horizon-only", "--existing-root", str(tmp_path / "none"),
            "--output-root", str(tmp_path / "campaigns"), "--rebuild-only",
        ])
