"""Read-only static audit of firm-level own-share price feedback.

This utility inspects Python syntax only.  It never imports the model, starts
a simulation, or changes source files.  Its conclusion is evidence about code
dependencies, not evidence that a causal mechanism was active at runtime.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable


AUDIT_SCHEMA = "firm-price-feedback-audit/v1"
FIRM_CLASS_TERMS = ("firm", "corporat", "company", "issuer")
DECISION_CATEGORIES: dict[str, tuple[str, ...]] = {
    "greenwashing_disclosure": ("greenwash", "disclos", "claim", "communicat", "report"),
    "compliance": ("complian", "enforce", "sanction", "remediat"),
    "investment": ("invest", "transition", "capital", "npv"),
    "financing": ("financ", "fund", "treasury", "credit", "debt"),
    "production_or_strategy": ("produc", "strateg", "operat", "output"),
    "reputation_management": ("reput", "brand", "trust"),
}

# These terms can establish evidence that a firm method reads a measure of its
# own listing or its own order book.  Generic ``price`` alone is deliberately
# excluded: it could refer to an input price or the price of green capital.
OWN_SHARE_TERMS = (
    "asset_price", "share_price", "stock_price", "market_cap", "marketcap",
    "valuation", "price_history", "last_price", "mid_price", "midpoint",
    "best_bid", "best_ask", "order_book", "spread", "bid_depth", "ask_depth",
    "trade_volume", "trade_sign", "return", "returns", "asset.get_last_price",
)
MARKET_TERMS = OWN_SHARE_TERMS + (
    "price", "volume", "liquidity", "order", "book", "market", "yield",
    "investor", "financing_cost", "cost_of_capital",
)
IGNORED_DIRECT_NAMES = {"p_green", "green_capital", "policy_rate"}
SKIP_DIRECTORIES = {".git", "__pycache__", "results", "tests", ".venv", "venv"}


@dataclass(frozen=True)
class Evidence:
    path: str
    line: int
    class_name: str | None
    function_name: str | None
    variable_or_call: str
    evidence_kind: str
    category: str | None
    excerpt: str


@dataclass
class MethodInfo:
    path: Path
    class_name: str
    function_name: str
    line: int
    categories: list[str]
    direct_own_share_reads: list[Evidence]
    market_reads: list[Evidence]
    self_calls: set[str]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_text(path: Path, content: str) -> None:
    """Write a file atomically in the destination directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", delete=False,
                             dir=path.parent, prefix=f".{path.name}.", suffix=".tmp") as handle:
        handle.write(content)
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def iter_source_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in repo_root.rglob("*.py"):
        if any(part in SKIP_DIRECTORIES for part in path.relative_to(repo_root).parts):
            continue
        files.append(path)
    return sorted(files)


def _excerpt(lines: list[str], line: int) -> str:
    start = max(0, line - 2)
    end = min(len(lines), line + 1)
    return "\n".join(f"{index + 1}: {lines[index].rstrip()}" for index in range(start, end))


def _categories_for(name: str) -> list[str]:
    lowered = name.lower()
    return [category for category, terms in DECISION_CATEGORIES.items()
            if any(term in lowered for term in terms)]


def _node_label(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _node_label(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _matches(label: str | None, terms: Iterable[str]) -> bool:
    lowered = (label or "").lower()
    return any(term in lowered for term in terms)


def _is_own_share_label(label: str | None) -> bool:
    lowered = (label or "").lower()
    return lowered not in IGNORED_DIRECT_NAMES and _matches(lowered, OWN_SHARE_TERMS)


def _method_info(path: Path, lines: list[str], class_name: str,
                 node: ast.FunctionDef | ast.AsyncFunctionDef) -> MethodInfo:
    categories = _categories_for(node.name)
    direct: list[Evidence] = []
    market: list[Evidence] = []
    calls: set[str] = set()
    seen: set[tuple[str, int, str]] = set()

    def add(label: str, ast_node: ast.AST, own_share: bool) -> None:
        key = (label, getattr(ast_node, "lineno", node.lineno), "own" if own_share else "market")
        if key in seen:
            return
        seen.add(key)
        evidence = Evidence(
            path=str(path), line=getattr(ast_node, "lineno", node.lineno),
            class_name=class_name, function_name=node.name, variable_or_call=label,
            evidence_kind="direct_own_share_read" if own_share else "market_related_read",
            category=categories[0] if categories else None,
            excerpt=_excerpt(lines, getattr(ast_node, "lineno", node.lineno)),
        )
        (direct if own_share else market).append(evidence)

    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            label = _node_label(child.func)
            if isinstance(child.func, ast.Attribute) and isinstance(child.func.value, ast.Name) \
                    and child.func.value.id == "self":
                calls.add(child.func.attr)
            if _is_own_share_label(label):
                add(label or "<call>", child, True)
            elif _matches(label, MARKET_TERMS):
                add(label or "<call>", child, False)
        elif isinstance(child, (ast.Name, ast.Attribute)) and isinstance(child.ctx, ast.Load):
            label = _node_label(child)
            if _is_own_share_label(label):
                add(label or "<read>", child, True)
            elif _matches(label, MARKET_TERMS):
                add(label or "<read>", child, False)
    return MethodInfo(path, class_name, node.name, node.lineno, categories, direct, market, calls)


def scan_repository(repo_root: Path) -> tuple[list[dict[str, str]], list[MethodInfo], list[Evidence]]:
    """Parse repository source without importing it; return audited metadata."""
    source_files: list[dict[str, str]] = []
    firm_methods: list[MethodInfo] = []
    non_firm_market_evidence: list[Evidence] = []
    for path in iter_source_files(repo_root):
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            source_files.append({"path": str(path.relative_to(repo_root)), "error": str(exc)})
            continue
        lines = text.splitlines()
        source_files.append({"path": str(path.relative_to(repo_root)), "sha256": sha256_file(path)})
        for class_node in (item for item in ast.walk(tree) if isinstance(item, ast.ClassDef)):
            is_firm = any(term in class_node.name.lower() for term in FIRM_CLASS_TERMS)
            methods = [item for item in class_node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for method in methods:
                info = _method_info(path, lines, class_node.name, method)
                if is_firm:
                    firm_methods.append(info)
                else:
                    non_firm_market_evidence.extend(info.direct_own_share_reads)
                    non_firm_market_evidence.extend(info.market_reads)
    return source_files, firm_methods, non_firm_market_evidence


def build_report(repo_root: Path) -> dict[str, Any]:
    source_files, firm_methods, non_firm_evidence = scan_repository(repo_root)
    decision_methods = [item for item in firm_methods if item.categories]
    direct = [evidence for item in decision_methods for evidence in item.direct_own_share_reads]
    indirect: list[Evidence] = []
    by_class: dict[str, dict[str, MethodInfo]] = {}
    for method in firm_methods:
        by_class.setdefault(method.class_name, {})[method.function_name] = method
    for decision in decision_methods:
        helper_map = by_class[decision.class_name]
        for helper_name in sorted(decision.self_calls):
            helper = helper_map.get(helper_name)
            if not helper or not helper.direct_own_share_reads:
                continue
            source = helper.direct_own_share_reads[0]
            indirect.append(Evidence(
                path=source.path, line=decision.line, class_name=decision.class_name,
                function_name=decision.function_name,
                variable_or_call=f"self.{helper_name}() -> {source.variable_or_call}",
                evidence_kind="evidenced_indirect_own_share_read",
                category=decision.categories[0] if decision.categories else None,
                excerpt=source.excerpt,
            ))

    categories: dict[str, dict[str, Any]] = {}
    for category in DECISION_CATEGORIES:
        methods = [item for item in decision_methods if category in item.categories]
        direct_here = [e for e in direct if e.category == category]
        indirect_here = [e for e in indirect if e.category == category]
        if direct_here:
            classification = "direct_price_feedback_detected"
        elif indirect_here:
            classification = "indirect_price_feedback_detected"
        elif methods:
            classification = "no_price_feedback_detected"
        else:
            classification = "inconclusive_static_analysis"
        categories[category] = {
            "classification": classification,
            "decision_methods": [{"path": str(item.path.relative_to(repo_root)),
                                  "class": item.class_name, "function": item.function_name,
                                  "line": item.line} for item in methods],
            "direct_evidence": [asdict(e) for e in direct_here],
            "indirect_evidence": [asdict(e) for e in indirect_here],
        }

    if direct:
        final = "direct_price_feedback_detected"
        answer = "Yes. At least one firm decision method directly reads an own-share market variable."
    elif indirect:
        final = "indirect_price_feedback_detected"
        answer = "Yes, indirectly. An evidenced call chain links a firm decision method to an own-share market variable."
    elif decision_methods:
        final = "market_variables_present_but_not_used_by_firms" if non_firm_evidence else "no_price_feedback_detected"
        answer = ("No direct or evidenced indirect own-share price feedback was detected in the "
                  "identified firm decision methods by this static audit.")
    else:
        final = "inconclusive_static_analysis"
        answer = "Inconclusive. The audit could not identify firm decision methods using its conservative rules."

    return {
        "audit_schema": AUDIT_SCHEMA,
        "audit_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "repository_root": str(repo_root.resolve()),
        "audited_source_files": source_files,
        "detected_firm_classes": sorted({item.class_name for item in firm_methods}),
        "identified_firm_decision_methods": [{"path": str(item.path.relative_to(repo_root)),
                                               "class": item.class_name, "function": item.function_name,
                                               "line": item.line, "categories": item.categories}
                                              for item in decision_methods],
        "own_share_price_evidence": {"direct": [asdict(e) for e in direct],
                                       "indirect": [asdict(e) for e in indirect]},
        "market_variables_outside_firm_decisions": [asdict(e) for e in non_firm_evidence],
        "dependency_table": categories,
        "final_classification": final,
        "central_question": "Do firms in the current model make decisions that are influenced by the price or market performance of their own stock?",
        "final_answer": answer,
        "limitations": [
            "This is static analysis of Python source. It does not execute the model or prove runtime causality.",
            "A variable used by traders, regulators, investors, or an order book is not treated as firm feedback unless it reaches an identified firm decision method.",
            "Potential dynamic dispatch, external configuration, or dependencies outside the parsed source may require a separate runtime trace audit.",
            "Generic prices, including the green-capital price, are not treated as own-share price feedback without explicit own-listing evidence.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Firm Own-Share Price Feedback Static Audit", "",
        f"- Audit time (UTC): `{report['audit_utc']}`",
        f"- Repository: `{report['repository_root']}`",
        f"- Final classification: `{report['final_classification']}`", "",
        "## Central answer", "", report["final_answer"], "",
        "## Decision-category dependency table", "",
        "| Category | Classification | Decision methods | Direct evidence | Indirect evidence |",
        "|---|---|---:|---:|---:|",
    ]
    for category, details in report["dependency_table"].items():
        lines.append(f"| {category} | {details['classification']} | {len(details['decision_methods'])} | "
                     f"{len(details['direct_evidence'])} | {len(details['indirect_evidence'])} |")
    lines.extend(["", "## Evidence locations", ""])
    evidence = report["own_share_price_evidence"]["direct"] + report["own_share_price_evidence"]["indirect"]
    if evidence:
        for item in evidence:
            lines.extend([f"- `{item['path']}:{item['line']}` — `{item['class_name']}.{item['function_name']}` "
                          f"reads/calls `{item['variable_or_call']}` ({item['evidence_kind']}).",
                          "", "```python", item["excerpt"], "```", ""])
    else:
        lines.append("No direct or evidenced indirect own-share price dependency was detected.")
    lines.extend(["", "## Detected firm classes", "", ", ".join(report["detected_firm_classes"]) or "None.",
                  "", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(["", "## Audited source files", ""])
    for item in report["audited_source_files"]:
        digest = item.get("sha256", f"parse error: {item.get('error', 'unknown')}")
        lines.append(f"- `{item['path']}` — `{digest}`")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd(),
                        help="Repository root to inspect (default: current directory).")
    parser.add_argument("--output-dir", type=Path, default=Path("results/audits"),
                        help="Directory for the two atomic audit reports.")
    parser.add_argument("--fail-on-inconclusive", action="store_true",
                        help="Exit non-zero when the final classification is inconclusive.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    output_dir = args.output_dir if args.output_dir.is_absolute() else repo_root / args.output_dir
    report = build_report(repo_root)
    json_path = output_dir / "firm_price_feedback_audit.json"
    markdown_path = output_dir / "firm_price_feedback_audit.md"
    atomic_write_text(json_path, json.dumps(report, indent=2, sort_keys=True) + "\n")
    atomic_write_text(markdown_path, render_markdown(report))
    print(f"final_classification: {report['final_classification']}")
    print(f"json_report: {json_path}")
    print(f"markdown_report: {markdown_path}")
    print("No simulation was executed; this was static source analysis only.")
    return 2 if args.fail_on_inconclusive and report["final_classification"] == "inconclusive_static_analysis" else 0


if __name__ == "__main__":
    raise SystemExit(main())
