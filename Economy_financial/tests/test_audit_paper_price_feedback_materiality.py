from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import audit_paper_price_feedback_materiality as audit


def price_audit(*, disclosure: str = "no_price_feedback_detected", investment: str = "no_price_feedback_detected",
                reputation: str = "no_price_feedback_detected") -> dict:
    return {"final_classification": "direct_price_feedback_detected", "dependency_table": {
        "greenwashing_disclosure": {"classification": disclosure},
        "investment": {"classification": investment},
        "reputation_management": {"classification": reputation},
    }}


class MaterialityAuditTests(unittest.TestCase):
    def test_price_to_firm_claim_without_mechanism_is_material_mismatch(self) -> None:
        result, _ = audit.assess_materiality(price_audit(), [{"excerpt": "share price disciplines greenwashing"}], True)
        self.assertEqual("material_claim_model_mismatch", result)

    def test_unconfirmed_keyword_evidence_requires_human_review(self) -> None:
        result, _ = audit.assess_materiality(price_audit(), [{"excerpt": "share price disciplines greenwashing"}])
        self.assertEqual("potential_material_claim_model_mismatch_requires_human_review", result)

    def test_relevant_direct_mechanism_removes_static_mismatch(self) -> None:
        result, _ = audit.assess_materiality(
            price_audit(disclosure="direct_price_feedback_detected"), [{"excerpt": "share price disciplines disclosure"}])
        self.assertEqual("no_static_mechanism_mismatch_detected", result)

    def test_no_claim_is_not_a_claim_model_mismatch(self) -> None:
        result, _ = audit.assess_materiality(price_audit(), [])
        self.assertEqual("material_limitation_to_market_feedback_framing_only", result)

    def test_markdown_scan_and_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audit_file = root / "price.json"
            manuscript = root / "paper.md"
            audit_file.write_text(json.dumps(price_audit()), encoding="utf-8")
            manuscript.write_text("Our share price market feedback disciplines greenwashing by firms.", encoding="utf-8")
            report = audit.build_report(audit_file, [manuscript])
            self.assertEqual("potential_material_claim_model_mismatch_requires_human_review", report["materiality_classification"])
            self.assertTrue(report["claim_evidence"])
            audit.atomic_write_text(root / "out.json", json.dumps(report))
            self.assertEqual(report["audit_schema"], json.loads((root / "out.json").read_text())["audit_schema"])


if __name__ == "__main__":
    unittest.main()
