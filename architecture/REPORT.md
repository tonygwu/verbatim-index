# Who can commit private data

Every agent can commit private experiment data from an independent checkout.
The private remote stores those commits on owned branches.
Repo-0 owns the shared production checkout and integrates selected results into production.

For example, an agent starts from a committed input snapshot, saves one experiment, and pushes its branch.
Another agent can fetch that commit without reading the first agent's working files.
The [setup and integration procedure](../docs/DATA-CLONE-WORKFLOW.md) already supports this path.

## Why the original restriction exists

Different public clone directories do not imply different private data checkouts.
Several `data` symlinks can reach one directory, with one working tree, current branch, and Git index.
The index holds the staged files that the next commit includes.
Concurrent agents can therefore commit each other's staged files or change each other's working files through a branch switch.
One owner for that shared checkout prevents these collisions.

Separate private clones remove this shared Git state.
They still need deliberate integration when two commits change the same record.
They also use committed snapshots, so they do not see live uncommitted input changes.
The current experiment role limits pipeline output paths to `predictions/_experiments/UNIQUE-RUN/`.
It does not authorize production ingestion or changes to frozen inputs.

## Inspection and evidence

This review covers checkout ownership, migration, and private branch publication at public source revision `3aba5d8`.
Model execution, scoring, and the contents of private records are outside scope.
The canonical [model](model.jsonl) links each component and flow to source evidence.
The [view guide](views/README.md) provides an overview and a focused migration view.

Read-only inspection on 2026-09-14 UTC resolved each public clone's `data` path and private Git directory:

- Repo-0 through repo-3 resolved to the sibling `data` checkout, on `main`.
- Repo-4 resolved to its own `.data-clones/experiment`, with `verbatim.role=experiment`.
- Repo-4 used branch `codex/repo-4-policy-2-preserved-2026-09-12` at commit `bd7a4a56df34e40710fc63cf3e0dcb7738cdef43`.
- After a private fetch, `git -C data rev-list --left-right --count HEAD...@{upstream}` returned `0 0`.

The setup implementation checks ownership, clones from the private origin, and switches only the requesting symlink.
See [setup](../scripts/data_clone_workflow.py) and [the integration test](../scripts/test_data_clone_workflow.py).
The test checks distinct indexes, independent commits, a branch push, conflict handling, and preservation of live uncommitted files.
It also checks production guards and publication sources.

## Verification

The focused test ran on 2026-09-14 UTC:

```text
$ .venv/bin/python scripts/test_data_clone_workflow.py
PASS: independent data clone workflow
exit 0
```

The first sandboxed attempt stopped because macOS process inspection was unavailable.
The test passed with process inspection enabled. All test Git writes used temporary repositories.
No model quota was spent.
No implementation changed, so this review did not repeat the full application suite.

The architecture validator returned `valid: true`, with no errors or warnings.
The bundle includes Mermaid, FigJam, D2, LikeC4, and HTML data cards.
No LikeC4 executable was available, so the bundle has diagram sources and no verified PNG renders.
The [review record](REVIEW.md) documents the evidence, flow, and operations checks.

## Work record and continuation

- DC-5 (explain independent commit ownership): succeeded. The agreement now names the shared production checkout as the restricted scope.
- DC-6 (verify the existing independent workflow): succeeded. The focused integration test passed and repo-4's private branch matched its upstream.

This turn changed documentation and architecture artifacts only.
The source revision for these changes is the commit that adds this report.
No migration, extraction, daemon, deployment, or background polling job was started.
Both the test and the private fetch finished.

The final consumer scan found app helpers with PIDs 19233, 19234, 19235, 19280, and 20199.
They referenced the repository working directory and ran the artifact picker, computer-use launcher, and JavaScript runtimes.
These app helpers are expendable for this review. No review result depends on keeping them alive.
No approval question or unresolved implementation decision remains.

For rollout, the next action is to run the documented setup dry run from each unmigrated experiment clone.
Its owner must let its consumers finish and name any owned outputs to preserve before applying the migration.
This review changed no other clone's symlink.

To verify durability after fetching public and private refs:

```bash
git status --short --branch
git rev-list --left-right --count HEAD...@{upstream}
git -C data status --short --branch
git -C data rev-list --left-right --count HEAD...@{upstream}
.venv/bin/python scripts/data_clone_workflow.py consumers
```
