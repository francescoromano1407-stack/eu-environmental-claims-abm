# Post-revision materiality audit (17 July 2026)

This directory holds the re-run of `audit_paper_price_feedback_materiality.py`
against the Strategy-A revised manuscript and documentation. The original
pre-revision audit outputs in `results/audits/` are preserved unchanged.

The classifier is keyword-based and cannot distinguish assertion from
negation, so it still reports
`potential_material_claim_model_mismatch_requires_human_review`. The required
human review was performed on 17 July 2026: every flagged excerpt is a
negation or limitation statement (e.g. "contain **no** own-share-price
feedback", "the paper does **not** claim ... price discipline", claim-matrix
rows classified REMOVED/REFRAMED). No flagged excerpt asserts a
price-to-firm causal channel. The audit's required action — retain the
limitation statement and avoid claiming that equity prices discipline
environmental decisions — is satisfied by the revised text.
