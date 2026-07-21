"""Focused tests for the standalone static firm-price-feedback audit."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import audit_firm_price_feedback as audit


class FirmPriceFeedbackAuditTests(unittest.TestCase):
    def write_source(self, root: Path, text: str, name: str = "model.py") -> None:
        (root / name).write_text(text, encoding="utf-8")

    def test_detects_direct_own_share_read_in_decision_method(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_source(root, """
class CorporatePolicy:
    def decide_disclosure(self):
        return self.asset.get_last_price() > 100
""")
            report = audit.build_report(root)
            self.assertEqual("direct_price_feedback_detected", report["final_classification"])
            self.assertTrue(report["own_share_price_evidence"]["direct"])

    def test_detects_evidenced_indirect_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_source(root, """
class Firm:
    def decide_investment(self):
        return self.market_signal()
    def market_signal(self):
        return self.asset.get_last_price()
""")
            report = audit.build_report(root)
            self.assertEqual("indirect_price_feedback_detected", report["final_classification"])

    def test_green_capital_price_is_not_false_positive_for_own_share_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_source(root, """
class CorporatePolicy:
    def transition_step(self, p_green):
        return p_green * 2
""")
            report = audit.build_report(root)
            self.assertNotIn(report["final_classification"], {
                "direct_price_feedback_detected", "indirect_price_feedback_detected"})

    def test_atomic_outputs_are_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "results" / "audits"
            self.write_source(root, "class Firm:\n    def decide_strategy(self):\n        return 0\n")
            report = audit.build_report(root)
            audit.atomic_write_text(output / "firm_price_feedback_audit.json", json.dumps(report))
            audit.atomic_write_text(output / "firm_price_feedback_audit.md", audit.render_markdown(report))
            self.assertEqual(report["audit_schema"], json.loads(
                (output / "firm_price_feedback_audit.json").read_text(encoding="utf-8"))["audit_schema"])
            self.assertFalse(list(output.glob(".*.tmp")))

    def test_firm_detection_uses_ast_without_importing_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_source(root, """
raise RuntimeError('must never be imported')
class Company:
    def decide_compliance(self):
        return 1
""")
            report = audit.build_report(root)
            self.assertIn("Company", report["detected_firm_classes"])
            self.assertEqual("no_price_feedback_detected", report["final_classification"])


if __name__ == "__main__":
    unittest.main()
