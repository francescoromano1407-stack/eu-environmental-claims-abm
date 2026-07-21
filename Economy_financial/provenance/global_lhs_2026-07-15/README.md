# Global LHS campaign: archival provenance package

This directory is a separate, additive provenance record for the completed global Latin-hypercube-sampling (LHS) campaign. The directory name follows the requested archival identifier. The authoritative campaign itself records execution from 2026-07-16 14:43:22 UTC through 2026-07-16 14:56:55 UTC.

## Provenance statement

The campaign manifests identify commit `1645f3589408503894c7e8f44a92ffe382a9a5b4` with a non-clean working tree, recorded verbatim as `1645f3589408503894c7e8f44a92ffe382a9a5b4+dirty`.

The original outputs under `results/` are retained unchanged. This package preserves the available source reconstruction, checksums, recorded execution configuration, recoverable environment evidence, and known limitations. It does not change or reinterpret the original `+dirty` labels.

The original dirty patch was not recovered with sufficient reliability. Consequently, bitwise reproduction is **not claimed**. Commit `00134a694e653fc2ce74b62eab1e8c6e9d0f67f7`, a direct child of the documented base committed shortly after the campaign completed, is preserved as a plausible candidate source snapshot, not as a verified copy of the original dirty worktree. See `candidate_source_snapshot.txt` and `reconstruction_status.md`.

**Reconstruction status: PARTIALLY RECONSTRUCTED.**

Later manuscript, audit, validation, financial-validation, replication-robustness, and editorial changes are not part of the original campaign code and must not be treated as such. The current working tree is therefore not archived as the campaign source.

## Package contents

- `base_commit.txt`: documented base revision and immutable Git identifiers.
- `candidate_source_snapshot.txt`: candidate revision, evidentiary basis, and limitations.
- `source_file_hashes.sha256`: SHA-256 hashes of the 22 relevant Python source blobs as stored in the candidate commit.
- `output_file_hashes.sha256`: SHA-256 hashes of 846 authoritative global-campaign configuration, manifest, raw, summary, figure, and log files.
- `environment.md`: execution configuration and environment information recoverable from the preserved records.
- `reconstruction_status.md`: investigation record, classification, and remaining evidence gap.

`working_tree.patch` is intentionally absent because no patch could be tied reliably to the campaign's original dirty state. `untracked_source/` is intentionally absent because no campaign-required source file was demonstrated to be both absent from Git and recoverable as an original untracked file.

## Checksum interpretation

`output_file_hashes.sha256` covers:

- `results/configuration.json` and `results/manifest.json`;
- all files in the four authoritative global-campaign directories under `results/raw/`;
- all files in `results/summaries/`, `results/figures/`, and `results/logs/`.

It excludes later `results/audits/`, `results/financial_validation/`, and `results/replication_robustness/` material. Paths are relative to the project directory.

Entries in `source_file_hashes.sha256` use the prefix `candidate:<commit>/` to make clear that they hash Git blobs from the candidate commit, not the later working tree and not a proven reconstruction of the dirty worktree.

## Read-only validation performed

No simulation was executed. A read-only validation parsed all 800 draw JSON files, the four raw manifests, raw summary files, campaign summary JSON files, and CSV headers. It confirmed the expected draw indices, horizons, completion flags, three replications, three regimes, and unchanged `+dirty` code-version labels. The global campaign paths were also confirmed clean relative to the candidate commit before this package was written.

## Appropriate use

This package supports transparent inspection of the completed computational experiment and a defensible partial reconstruction of its source provenance. It should be cited as archival evidence, not as proof that the original execution environment or dirty source tree can be recreated byte for byte.
