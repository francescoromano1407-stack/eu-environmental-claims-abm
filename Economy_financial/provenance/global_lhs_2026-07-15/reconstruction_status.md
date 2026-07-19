# Reconstruction status

## Classification: PARTIALLY RECONSTRUCTED

The documented Git base is verified, the authoritative outputs and execution configuration are preserved and checksummed, and a strongly plausible later committed source snapshot has been identified. The original non-committed diff cannot be recovered or proven exactly. Exact or bitwise reproducibility is therefore not claimed.

## Verified facts

- Every inspected global manifest and draw file retains `1645f3589408503894c7e8f44a92ffe382a9a5b4+dirty`.
- Git object `1645f3589408503894c7e8f44a92ffe382a9a5b4` exists and has tree `4e331edd7a8b84ca1fb108a42097a2135169f812`.
- Candidate commit `00134a694e653fc2ce74b62eab1e8c6e9d0f67f7` is a direct child of that base and contains the relevant source and global outputs.
- Before package creation, the authoritative global configuration, manifests, raw outputs, summaries, figures, and logs were clean relative to the candidate commit.
- Read-only validation parsed 800 expected draw files and found no metadata, completion, horizon, replication, regime-count, or code-version mismatch.
- `source_file_hashes.sha256` contains 22 candidate Git-blob hashes; `output_file_hashes.sha256` contains 846 preserved output-file hashes.

## Investigation performed

- Inspected all local branches, remote-tracking refs, tags, the full reflog, and Git history around the documented base.
- Inspected Git stashes: none exist.
- Inspected unreachable Git objects without writing recovery refs: 545 blobs and 183 trees were found, but no unreachable commit. The anonymous objects have no reliable filename/timestamp association to the original campaign state and cannot support an authenticated patch.
- Inspected the Codex turn-diff capture ref: it is a later tree capture and does not establish the 15–16 July dirty state.
- Searched the Desktop for duplicate project directories and common archive formats. The only duplicate project copy was created on 2026-07-19, has an empty `.git` directory, and its compared Python sources match the later current worktree, including post-campaign changes.
- Inspected local-history directories for Visual Studio Code, Cursor, and VSCodium: no entries were available.
- Compared candidate source against the committed CPython 3.12 caches. All 22 corresponding source files compile to matching marshalled code objects, which is corroborating semantic evidence only.

## Remaining evidence gap

The decisive missing artifact is the original dirty patch, or an independently timestamped source snapshot/source-tree digest made at execution time. The manifests also omit exact Python and package versions. Without at least one of those source-identity artifacts, textual and bitwise identity cannot be established.

## Files intentionally omitted

- `working_tree.patch`: omitted because the base-to-candidate diff is only a candidate reconstruction, not a reliably recovered original patch.
- `untracked_source/`: omitted because no source file was demonstrated to be both required by the campaign, absent from Git, and recoverable as the original untracked file.

## Archival conclusion

The defensible statement is: the campaign outputs are immutable and fully checksummed; their configuration and seed schedules are recorded; the documented base commit is available; and commit `00134a694e653fc2ce74b62eab1e8c6e9d0f67f7` is the best available, semantically corroborated candidate source snapshot. The original dirty worktree remains unverified.
