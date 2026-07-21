"""The replication extension is dry-run first and never repeats base rows."""

import json

from market_sim.sensitivity_campaign import (CampaignConfig, DEFAULT_REGIMES,
                                              latin_hypercube_design)
from run_replication_robustness import (HORIZONS, build_parser, main,
                                        select_representative_draws)


def _write_summary(path, days):
    per_draw = []
    for draw in range(200):
        per_draw.append({
            "draw": draw,
            "contrasts": {
                "exposure_weighted_severity": {
                    DEFAULT_REGIMES[1]: draw * (days / 120),
                    DEFAULT_REGIMES[2]: (199 - draw) * (days / 120),
                },
                "mean_greenhushing_gap": {
                    DEFAULT_REGIMES[1]: (draw % 17) / 100,
                    DEFAULT_REGIMES[2]: (draw % 23) / 100,
                },
            },
            "winners": {"default_experiment": DEFAULT_REGIMES[draw % 3]},
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"draws_summarized": 200,
                                "per_draw": per_draw}), encoding="utf-8")


def _base_payload(config, draw, sample):
    rows = []
    for replication in range(3):
        for regime in config.regimes:
            rows.append({
                "regime": regime, "replication": replication,
                "market_seed": config.market_seed(draw, replication),
                "supervision_seed": config.supervision_seed(draw, replication),
                "metrics": {"fixture": float(draw + replication + 1)},
            })
    return {
        "complete": True, "draw": draw, "sample": sample,
        "horizon_days": config.horizon_days,
        "discount_rate": sample["social_discount_rate"],
        "replications": 3, "regimes": list(config.regimes), "rows": rows,
    }


def _fixture_campaign(tmp_path):
    root = tmp_path / "results"
    for days, label in HORIZONS:
        _write_summary(root / "summaries" / f"{label}_summary.json", days)
    selected = select_representative_draws(root, 3)
    for days, label in HORIZONS:
        raw = root / "raw" / label
        raw.mkdir(parents=True)
        config = CampaignConfig(
            outdir=str(raw), draws=200, replications=3,
            horizon_days=days, master_seed=42,
            supervision_base_seed=7, regimes=DEFAULT_REGIMES,
            label=label,
        )
        (raw / "manifest.json").write_text(
            json.dumps({"config": config.to_dict()}), encoding="utf-8")
        design = latin_hypercube_design(config.master_seed, config.draws)
        for draw in selected:
            (raw / f"draw_{draw:04d}.json").write_text(
                json.dumps(_base_payload(config, draw, design[draw])),
                encoding="utf-8")
    return root, selected


def test_default_replication_extension_is_inspection_only():
    args = build_parser().parse_args([])
    assert args.execute_missing is False
    assert 10 <= args.target_replications <= 20


def test_representative_selection_is_deterministic(tmp_path):
    root = tmp_path / "results"
    for days, label in HORIZONS:
        _write_summary(root / "summaries" / f"{label}_summary.json", days)
    first = select_representative_draws(root, 12)
    second = select_representative_draws(root, 12)
    assert first == second
    assert len(first) == len(set(first)) == 12


def test_dry_run_does_not_execute_or_create_extension_files(tmp_path,
                                                            monkeypatch):
    root, selected = _fixture_campaign(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("dry run must not run extra replications")

    monkeypatch.setattr("run_replication_robustness.run_replication_rows",
                        forbidden)
    output = tmp_path / "extension"
    main(["--results-root", str(root), "--output-root", str(output),
          "--subset-size", str(len(selected)), "--target-replications", "10"])
    assert not output.exists()
