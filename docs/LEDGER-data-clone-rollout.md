# Independent data checkout rollout

Last updated: 2026-09-14T04:48:33Z.

## Authorization and scope

The operator requested rollout to the remaining agent clones after reviewing the ownership model.
This authorizes preparation, preservation, independent commits and pushes, and each approved cutover.
Repo-0 retains the shared production checkout. No production job is started or stopped.
No private record enters a public commit.

## Workstreams

- DC-7 (migrate repo-1): succeeded. Independent checkout created and its private receipt committed and pushed as `e69c0cda6f03702ea51e5d558e9b6efd2babc4aa`.
- DC-8 (migrate repo-2): succeeded. Its private receipt is committed and pushed as `b83eec62d111a46ac4ecdd644ecca47976d8c83a`.
- DC-9 (migrate repo-3): succeeded. Its private receipt is committed and pushed as `e2ea42bc1c8dfb74467a74598501537b3e10a52b`.
- DC-10 (verify independent commits and pushes): succeeded. All five clones have distinct private Git indexes. Each migrated branch is clean and matches its upstream.

The baseline private revision is `70d2945fa9e1c324a061eaf618f193f8ae598713`.
The shared checkout has 1,946 dirty or untracked market-cache files.
These files remain in the shared checkout. No owned experiment directory belongs to repo-1 through repo-3 in the inspected experiment shelf.
Repo-4's existing experiment is already preserved in its independent clone.

## Cutover question

The operator confirmed that repo-3 is paused in Plan Mode and repo-2 is idle.
The cutovers can proceed with an exception for the specific inspected idle process identities.
The migration wrapper checks each PID, command, and UTC start time again before each switch.
New consumers, changed process identities, descendants, or open data files still stop the migration.
No reusable consumer guard is weakened.

## Process record

No detached task, polling loop, model job, daemon, or server was started for this rollout.
Tool-managed Git subprocesses finish within the active turn and are checked before completion.
Foreign consumers observed:

- Repo-2: shell 61551, Claude 67895, and Claude spare 78155.
- Repo-3: shell 1912 and Claude 2160.
- Repo-0: shell 40060 and Claude 48347. No production-owner process is touched.

Verification: inspect `data` symlink targets, private branch/upstream status, and `data_clone_workflow.active_consumers()` for each target clone.

The temporary migration wrapper remains under repo-4's ignored `.data-clones/rollout-2026-09-14/` directory.
It is complete and expendable. It is not a polling loop or a service.
The private receipts contain its preservation results and the authorized process checks.
No remaining task depends on the wrapper or on keeping this session alive.

## Final layout and continuation

- Repo-0: shared production `data`, private branch `main`, input commit `70d2945f`.
- Repo-1: own `.data-clones/experiment`, private branch `codex/repo-1-data-2026-09-14`.
- Repo-2: own `.data-clones/experiment`, private branch `codex/repo-2-data-2026-09-14`.
- Repo-3: own `.data-clones/experiment`, private branch `codex/repo-3-data-2026-09-14`.
- Repo-4: existing `.data-clones/experiment`, private branch `codex/repo-4-policy-2-preserved-2026-09-12`.

Each non-production agent can now stage named experiment files, commit, and push from its own `data` directory.
The [workflow](DATA-CLONE-WORKFLOW.md) describes run creation, output paths, and production integration.
All three new checkouts include the committed prediction results from `70d2945f`.
Their index `inputs_sha256` matches the actual records: `fddfb8e6f55d290e2f8f4abc9d2d3f5d5e13266956c97d48daf89a033261280d`.
The shared market caches remain intact. A new checkout can fetch its own caches during an authorized market run.

No migration or implementation decision remains pending.
The next action is to continue agent work using each clone's own private branch.

Verification completed after the migrations:

```text
$ .venv/bin/python scripts/test_data_clone_workflow.py
PASS: independent data clone workflow
exit 0

Live checkout audit:
PASS: five distinct data indexes; three migrated branches clean and pushed; production inputs and guards preserved
```

The live audit checked distinct index inodes, absence of object alternates, clean private trees, and `0 0` upstream divergence.
It also checked prediction input digests, the production marker, shared-write refusal, and the explicit production publication source.
Each shared cache file and the shared Git index still matched the hashes in all three private migration receipts.

## History

- 2026-09-14T04:42:28Z: preflight found repo-1 idle, repo-2 and repo-3 with open Claude sessions, and all three still sharing production data.
- The operator then confirmed both sessions idle and authorized the quiet cutovers.
- Repo-1 migrated successfully. All 1,946 shared dirty or untracked files, the shared Git index, and other symlinks retained their hashes or targets.
- 2026-09-14T04:48:33Z: repo-2 and repo-3 migrated and pushed their receipts. Both performed three process checks with the authorized idle-session exception.
- The integration test passed after the migrations, including the `inputs_sha256` publication contract raised in the other agent's note.
