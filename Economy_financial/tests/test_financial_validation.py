"""Low-cost tests for diagnostics that read existing paths only."""

import csv
import math
import random

from market_sim.financial_validation import (diagnose_csv, diagnose_prices,
                                              main, write_artifacts)


def _prices_from_returns(returns):
    prices = [100.0]
    for value in returns:
        prices.append(prices[-1] * math.exp(value))
    return prices


def test_diagnostics_report_all_three_stylized_fact_contracts():
    rng = random.Random(12)
    returns = [rng.gauss(0.0, 0.01) for _ in range(900)]
    for index in range(40, 900, 100):
        returns[index] *= 15
    result = diagnose_prices(_prices_from_returns(returns))
    assert set(result["classifications"]) == {
        "fat_tailed_returns",
        "weak_linear_return_autocorrelation",
        "volatility_clustering",
    }
    assert result["calendar_log_returns"] == 900
    assert result["absolute_return_hill_tail"]["k"] > 0
    assert result["ljung_box_returns_lag20"]["lag"] == 20


def test_csv_provenance_and_atomic_artifacts(tmp_path):
    csv_path = tmp_path / "saved_path.csv"
    prices = _prices_from_returns([0.003 * math.sin(index / 7)
                                   for index in range(1, 301)])
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("day", "asset_price"))
        writer.writeheader()
        for day, price in enumerate(prices):
            writer.writerow({"day": day, "asset_price": price})
    result, loaded = diagnose_csv(csv_path)
    assert len(result["source_sha256"]) == 64
    assert result["provenance_status"].startswith("detached")
    output = tmp_path / "validation"
    write_artifacts(result, loaded, output)
    assert (output / "financial_stylized_facts.json").is_file()
    assert (output / "financial_stylized_facts.csv").is_file()
    assert len(list(output.glob("*.svg"))) == 3
    assert not list(output.glob("*.tmp"))


def test_cli_is_read_only_without_write_flag(tmp_path, capsys):
    csv_path = tmp_path / "path.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("asset_price",))
        writer.writeheader()
        for price in _prices_from_returns([0.001] * 60):
            writer.writerow({"asset_price": price})
    output = tmp_path / "not_created"
    main(["--input", str(csv_path), "--output-dir", str(output)])
    assert not output.exists()
    assert "No simulation was executed" in capsys.readouterr().out
