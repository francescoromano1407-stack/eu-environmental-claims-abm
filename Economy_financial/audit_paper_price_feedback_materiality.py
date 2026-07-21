"""Read-only audit of whether missing firm price feedback is material to paper claims.

The tool compares explicit manuscript/documentation language with the static
firm-price-feedback audit.  It makes no claim about empirical validity and
never imports or executes the simulation model.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from xml.etree import ElementTree


SCHEMA = "paper-price-feedback-materiality-audit/v1"
PRICE_FEEDBACK_PATTERNS = (
    r"market[ -]feedback", r"price[ -]feedback", r"equity[ -]price",
    r"share[ -]price", r"stock[ -]price", r"market discipline",
    r"financial[ -]market feedback", r"price signal",
)
FIRM_DECISION_PATTERNS = (
    r"greenwash", r"disclos", r"environmental claim", r"transition invest",
    r"firm incentive", r"corporate incentive", r"corporate decision",
)
RELEVANT_CATEGORIES = ("greenwashing_disclosure", "investment", "reputation_management")


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent,
                             prefix=f".{path.name}.", suffix=".tmp") as handle:
        handle.write(content)
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_document(path: Path) -> str:
    """Read Markdown/text or extract visible paragraph text from a DOCX file."""
    if path.suffix.lower() != ".docx":
        return path.read_text(encoding="utf-8", errors="replace")
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    return "\n\n".join("".join(node.text or "" for node in paragraph.iter(f"{namespace}t"))
                     for paragraph in root.iter(f"{namespace}p"))


def snippets(text: str, patterns: tuple[str, ...], radius: int = 180) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            start = max(0, match.start() - radius)
            end = min(len(text), match.end() + radius)
            excerpt = re.sub(r"\s+", " ", text[start:end]).strip()
            if excerpt not in matches:
                matches.append(excerpt)
    return matches


def assess_materiality(price_audit: dict[str, Any], claim_evidence: list[dict[str, Any]],
                       confirmed_price_to_firm_claim: bool = False) -> tuple[str, str]:
    table = price_audit.get("dependency_table", {})
    relevant = [table.get(category, {}).get("classification") for category in RELEVANT_CATEGORIES]
    implemented = any(value in {"direct_price_feedback_detected", "indirect_price_feedback_detected"}
                      for value in relevant)
    asserts_price_to_firm = bool(claim_evidence)
    if asserts_price_to_firm and not implemented:
        if not confirmed_price_to_firm_claim:
            return (
                "potential_material_claim_model_mismatch_requires_human_review",
                "Keyword evidence suggests that the paper may invoke price or market feedback near firm environmental decisions, but the static audit found no evidenced own-share feedback in disclosure, investment, or reputation decisions. Human review must confirm that this is a causal paper claim before treating it as a material mismatch.",
            )
        return (
            "material_claim_model_mismatch",
            "The paper appears to invoke price or market feedback in relation to firm environmental decisions, but the static audit found no evidenced own-share feedback in disclosure, investment, or reputation decisions.",
        )
    if asserts_price_to_firm:
        return (
            "no_static_mechanism_mismatch_detected",
            "The paper invokes price feedback and the static audit found an evidenced relevant firm-level price-feedback path. Runtime causality still requires separate verification.",
        )
    if price_audit.get("final_classification") in {"direct_price_feedback_detected", "indirect_price_feedback_detected"}:
        return (
            "material_limitation_to_market_feedback_framing_only",
            "A narrow price-feedback path exists, but no detected paper claim was found that requires own-share prices to discipline environmental decisions. The limitation should be disclosed if discussing market feedback.",
        )
    return (
        "not_material_to_detected_paper_claims",
        "No detected paper claim invokes firm-level own-share price feedback, and the static audit found no such feedback path.",
    )


def build_report(price_audit_path: Path, documents: list[Path],
                 confirmed_price_to_firm_claim: bool = False) -> dict[str, Any]:
    price_audit = json.loads(price_audit_path.read_text(encoding="utf-8"))
    evidence: list[dict[str, Any]] = []
    scanned: list[str] = []
    for document in documents:
        if not document.exists():
            continue
        text = read_document(document)
        scanned.append(str(document))
        # Only flag a possible causal claim when both concepts occur in the
        # same paragraph. Generic market descriptions elsewhere are ignored.
        for paragraph in re.split(r"\n\s*\n", text):
            if not any(re.search(pattern, paragraph, flags=re.IGNORECASE)
                       for pattern in FIRM_DECISION_PATTERNS):
                continue
            for hit in snippets(paragraph, PRICE_FEEDBACK_PATTERNS):
                evidence.append({"document": str(document), "claim_type": "possible_price_to_firm_claim",
                                 "excerpt": hit})
    classification, conclusion = assess_materiality(price_audit, evidence, confirmed_price_to_firm_claim)
    return {
        "audit_schema": SCHEMA,
        "audit_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "price_feedback_audit_path": str(price_audit_path.resolve()),
        "price_feedback_audit_final_classification": price_audit.get("final_classification"),
        "relevant_firm_decision_classifications": {
            category: price_audit.get("dependency_table", {}).get(category, {}).get("classification", "missing")
            for category in RELEVANT_CATEGORIES
        },
        "documents_scanned": scanned,
        "claim_evidence": evidence,
        "price_to_firm_claim_human_confirmed": confirmed_price_to_firm_claim,
        "materiality_classification": classification,
        "conclusion": conclusion,
        "required_action": (
            "Revise price-feedback claims, or implement and validate an explicit price-to-firm decision channel before relying on those claims. A substantive model change requires fresh financial validation and may require rerunning affected policy experiments."
            if classification == "material_claim_model_mismatch" else
            "Retain the limitation statement and avoid claiming that equity prices directly discipline environmental decisions unless a separate runtime audit establishes that channel."
        ),
        "limitations": [
            "Claim detection is keyword-based and conservative; human review of every flagged excerpt is required.",
            "Static source analysis identifies explicit dependencies, not realized runtime causality or effect magnitude.",
            "This audit does not execute a simulation or assess the empirical realism of any mechanism.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Paper Materiality Audit: Firm Own-Share Price Feedback", "",
             f"- Audit time (UTC): `{report['audit_utc']}`",
             f"- Materiality classification: `{report['materiality_classification']}`", "",
             "## Conclusion", "", report["conclusion"], "",
             "## Relevant model mechanisms", "",
             "| Firm decision category | Static-audit classification |",
             "|---|---|"]
    lines.extend(f"| {category} | {value} |" for category, value in
                 report["relevant_firm_decision_classifications"].items())
    lines.extend(["", "## Flagged manuscript/documentation evidence", ""])
    if report["claim_evidence"]:
        for item in report["claim_evidence"]:
            lines.extend([f"- `{item['document']}` — {item['claim_type']}: {item['excerpt']}", ""])
    else:
        lines.append("No price-to-firm claim was detected by the conservative keyword scan.")
    lines.extend(["", "## Required action", "", report["required_action"], "", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


def default_documents(repo_root: Path) -> list[Path]:
    revised = repo_root / "Francesco_Romano_EU_Environmental_Claims_ABM_Paper_revised.docx"
    documents = [revised] if revised.exists() else []
    documents.extend(sorted((repo_root / "docs").glob("*.md")) if (repo_root / "docs").exists() else [])
    return documents


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--price-audit", type=Path, default=Path("results/audits/firm_price_feedback_audit.json"))
    parser.add_argument("--manuscript", type=Path, action="append", default=None,
                        help="Optional Markdown, text, or DOCX document to inspect; repeatable.")
    parser.add_argument("--output-dir", type=Path, default=Path("results/audits"))
    parser.add_argument("--confirmed-price-to-firm-claim", action="store_true",
                        help="Use only after human review confirms the paper makes this causal claim.")
    parser.add_argument("--fail-on-material-mismatch", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.repo_root.resolve()
    price_audit = args.price_audit if args.price_audit.is_absolute() else root / args.price_audit
    output = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    documents = args.manuscript or default_documents(root)
    documents = [item if item.is_absolute() else root / item for item in documents]
    report = build_report(price_audit, documents, args.confirmed_price_to_firm_claim)
    atomic_write_text(output / "paper_price_feedback_materiality_audit.json", json.dumps(report, indent=2) + "\n")
    atomic_write_text(output / "paper_price_feedback_materiality_audit.md", render_markdown(report))
    print(f"materiality_classification: {report['materiality_classification']}")
    print("No simulation was executed; this was a static claim-and-mechanism audit only.")
    return 2 if args.fail_on_material_mismatch and report["materiality_classification"] == "material_claim_model_mismatch" else 0


if __name__ == "__main__":
    raise SystemExit(main())
