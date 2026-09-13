# Independent data clones with one production checkout

The production checkout remains at `verbatim-index/data`. Only its production
owner, currently `repo-0`, manages that checkout's Git index, commits, and pushes.
Each experiment clone can own a separate checkout of the same private repository.
Experiment agents can commit and push their own branches without coordinating a shared Git index.

Public code and private records remain in separate repositories.
Both `/data` and `/.data-clones/` are ignored by the public repository.
Never force-add either path to a public commit.

## Ownership

- The production owner runs ingestion, withdrawals, production aggregation, and daemons.
- Unmigrated clones keep their existing `data` symlink. Migration changes no other clone.
- Existing authorized prediction jobs in unmigrated clones can finish in the shared checkout.
  Only the production owner commits their shared outputs.
- Independent experiment clones write results under `data/predictions/_experiments/UNIQUE-RUN/`.
  Their owners control their private Git indexes, branches, commits, and pushes.
- Experiment inputs remain frozen. Input modifications belong inside the run directory, with hashes and provenance.
  An experiment never replaces production transcripts, grades, or indexes directly.

The experiment role is stored in the private clone's local Git config as
`verbatim.role=experiment`. It is not inherited from the remote repository.
Production guards reject this role even if someone copies `.daemon-clone` into it.
These guards prevent accidental misuse. They do not replace Git access controls.

## Prepare and migrate one clone

Start in your own non-daemon public clone. Install the normal Python dependencies.
Read the production data revision without pulling or changing its checkout:

```bash
DATA_BASE=$(git -C ../data rev-parse HEAD)
.venv/bin/python scripts/data_clone_workflow.py setup \
  --source ../data --revision "$DATA_BASE" \
  --branch codex/repo-N-experiment-UNIQUE --dry-run
```

Replace `repo-N-experiment-UNIQUE` with your own unique branch name.
The dry run checks paths, ownership, the baseline commit, and any requested copy sources.
It does not clone, change a Git config, or replace a symlink.

To preserve an existing run that you own, add this argument:

```bash
--copy-owned predictions/_experiments/YOUR-RUN
```

Repeat `--copy-owned` for separate owned runs. Never name the whole experiments directory.
The command copies regular files only. It rejects symlinks, traversal, and conflicting destination content.
It compares SHA-256 hashes before and after copying. Source files remain intact.
Unrelated uncommitted or untracked production files are neither copied nor changed.

Before applying, let this clone's data consumers and writers finish.
Do not start another job in this clone during migration.
Run the same setup command with `--apply` instead of `--dry-run`.

The command performs these steps:

1. Refuse the production owner, unignored private paths, or an unknown existing `data` target.
2. Inspect same-user process commands, working directories, and open files for this public clone.
3. Clone the private origin into the ignored `.data-clones/experiment` directory.
   Use an independent object store and Git index, without hardlinks, alternates, or Git worktrees.
4. Check out the exact baseline commit on the named experiment branch.
   Refuse a branch name that already exists on the remote.
5. Copy the explicitly owned outputs and check repository connectivity.
6. Repeat the process and output checks before switching the requesting clone's `data` symlink atomically.

The original production checkout, other symlinks, and running jobs remain unchanged.
No command pulls, resets, stages, or commits the shared checkout.
No new `.daemon-clone` marker is created.
The public clone records its production source in local config, `verbatim.productionData`.
The private clone records preparation details and copied hashes in `.git/verbatim-clone.json`.
Machine paths in these local records are never public source code.

Process inspection requires `ps` and `lsof`. Inspection failure leaves migration pending.
Ancestor processes belong to the invoking terminal or agent and are excluded.
The check is a process snapshot, not a scheduler lock. Keep the clone idle until the command returns.

The command is repeatable with identical arguments. After a completed migration,
it leaves later experiment changes and commits intact.
A failed preparation remains under the ignored destination for inspection.
An incompatible existing destination is never reset or deleted automatically.
Before retrying a partial preparation, inspect its state and resolve the reported conflict.
If a clone failed before writing its state file, preserve that directory under another ignored name before retrying.

Inspect current consumers without changing jobs:

```bash
.venv/bin/python scripts/data_clone_workflow.py consumers
```

## Create and record an experiment

Reserve a unique directory before running the prediction pipeline:

```bash
.venv/bin/python scripts/data_clone_workflow.py new-run \
  --name YOUR-UNIQUE-RUN --extractor astra --verifier fable --astra-model gpt-6-astra
```

This command spends no model quota. It refuses an existing run name.
Its `experiment.json` records the input data commit, code commit, dirty-tree flags,
requested models, policy release, and full specification and schema hashes.
Commit code before a real run so the recorded code revision identifies the implementation.

Set every output path to that run directory, including reports and derived indexes.
For example, an authorized single-transcript extraction uses:

```bash
.venv/bin/python scripts/extract_predictions.py --stage both \
  --single data/transcripts_open/SLUG/SOURCE.json \
  --extractor astra --astra-model gpt-6-astra --verifier fable \
  --out data/predictions/_experiments/YOUR-UNIQUE-RUN/results
```

This example spends model quota. Setup, migration, validation, and this task's tests do not.
A quota-spending run still needs its own authorized scope.

The runner already records each stage's contract, exact prompts, input hashes,
raw responses, model names, and routing telemetry. It also records the input checkout revision.
A requested model name is not proof of the served model.
Use each call's model and telemetry for that evidence, and label unknown identity explicitly.
A checkout revision does not prove that inputs were committed.
Use the saved input bundles and hashes to identify the actual bytes, including frozen older snapshots.

The policy release pairs compatible extraction and verification contracts.
Existing cache checks reject mismatched contracts, inputs, prompts, or model requests without spending quota.
Keep experiments with different releases or inputs separate.
The production aggregator excludes directories beginning with `_`, so preserving an experiment does not promote it.

Commit and push only your owned run in your independent private clone:

```bash
git -C data status --short --branch
git -C data add predictions/_experiments/YOUR-UNIQUE-RUN
git -C data commit -m "Record YOUR-UNIQUE-RUN experiment"
git -C data push -u origin codex/repo-N-experiment-UNIQUE
```

Never push an experiment to private `main`. Never stage from the shared production checkout.
Use Git to exchange commits between agents. Do not copy another agent's working tree.

## Incorporate selected results into production

The production owner performs integration after reviewing the experiment.
Preserving an experiment commit and promoting its results are separate decisions.
Git can merge text that represents incompatible records.

1. Fetch the selected private branch into an independent review clone.
   Inspect the exact commit and its changed paths before applying anything.
2. Check its parent input revision, code revision, input hashes, schema version,
   policy release, extraction contract, verification contract, and served-model evidence.
   Check that its run manifest agrees with each candidate and transcript sidecar.
3. Compare frozen transcript bytes, source identities, roster, dates, exclusions,
   and candidate identifiers against current production inputs.
   Changed inputs need an explicit reconciliation decision, never an assumed cache match.
4. Validate the experiment with the code and specification release that produced it:

   ```bash
   .venv/bin/python scripts/validate_predictions.py \
     --predictions data/predictions/_experiments/YOUR-UNIQUE-RUN/results \
     --transcripts data/predictions/_experiments/YOUR-UNIQUE-RUN/snapshot/transcripts \
     --report data/predictions/_experiments/YOUR-UNIQUE-RUN/validation.json
   ```

   Use the actual saved input directory. Some experiments read unchanged committed transcripts instead.
   Schema validity alone cannot decide eligibility, quotation fidelity, or model identity.
   Review disagreements and selection criteria before promoting candidates.
5. Inspect a proposed private cherry-pick in the review clone.
   On a conflict, inspect both records. If compatibility is unresolved, abort the cherry-pick.
   Never use a blanket `ours` or `theirs` resolution for prediction records.
6. Record the selected experiment commit, promoted transcript IDs, compatibility decision,
   and replaced production IDs in a private integration manifest.
   Preserve the original run and raw evidence. Do not import its derived index as the production index.
7. Coordinate with production writers before incorporating the reviewed commit through the production owner.
   Do not reset or discard a dirty production checkout to make integration succeed.
   Copy selected candidate files and matching sidecars only after the compatibility decision.
8. In the production owner's clone, validate the resulting production records and regenerate the index:

   ```bash
   .venv/bin/python scripts/validate_predictions.py
   .venv/bin/python scripts/aggregate_predictions.py
   ```

   Inspect contract-pair counts and coverage in the regenerated index.
   Keep incompatible releases separate. Do not combine their acceptance rates into one model-agreement claim.
   For leaderboard changes, regenerate its aggregate and audit through the production owner as well.
9. Stage named private files, including the integration manifest and regenerated indexes.
   The production owner commits and pushes the production change.

Integration does not authorize a new model pass or deployment.

## Publish from an explicit production source

Both deployment scripts require the production path and the full current data commit:

```bash
PRODUCTION_DATA=../data
DATA_REVISION=$(git -C "$PRODUCTION_DATA" rev-parse HEAD)
bash scripts/deploy.sh --production-data "$PRODUCTION_DATA" --data-revision "$DATA_REVISION" --dry-run
bash scripts/deploy_predictions.sh --production-data "$PRODUCTION_DATA" --data-revision "$DATA_REVISION" --dry-run
```

After deployment is authorized, omit `--dry-run` for the chosen site.
The production source must match local `verbatim.productionData`, or the conventional sibling `../data` if unset.
An experiment checkout is refused even if its commit matches production.
A stale copied checkout is refused even if it contains a production owner marker.
Do not change the production-source config to authorize an experiment.

The scripts render from that explicit source and check its revision again before publication.
They hash render inputs before and after rendering, including dirty production files.
They print the source path, commit, and content hash.
Production daemons can legitimately advance uncommitted data, so a clean working tree is not required.
A changed source, missing freshness counts, or count mismatch stops publication.
Counts detect missing records but cannot establish semantic freshness after same-count edits.
After such edits, the production owner must regenerate the aggregate with `--refresh`.

`--refresh` requires the production owner's own data checkout.
`PUBLISH_ON_COMPLETE=1` retains its existing authorization and supplies explicit source and revision arguments automatically.
Direct `npx wrangler deploy` bypasses these checks. Use the deployment scripts for production publication.
No deployment was performed for this migration.

## Verification and migration record

Public baseline: `98a7de6239a36a6e3f1034b9d63f89d85098f91b`.
Private baseline: `06f1ec2a1b41aeed5cec0d1c4f0ae85cd180c399`.
These identify the requested baseline, not an assertion that remote main remains unchanged.

```bash
.venv/bin/python scripts/test_data_clone_workflow.py
for t in scripts/test_*.py; do .venv/bin/python "$t" || exit 1; done
```

The workflow test uses temporary repositories and a deployment tripwire.
Its required success line is `PASS: independent data clone workflow`.
It exercises independent commits and pushes, real Git conflicts, owned-output preservation,
active consumers, shared-index protection, experiment provenance, and both publication entry points.

Work record, repo-4:

- DC-1 (opt-in clone preparation and migration tooling): succeeded. Temporary repository tests passed.
- DC-2 (production publication and ownership guards): succeeded. Both deployment entry points passed the source and revision checks.
- DC-3 (temporary repository tests and quota-free suite): succeeded. All 41 `scripts/test_*.py` files passed. No model quota or deployment.
- DC-4 (repo-4 migration and preservation of `policy-2-2026-09-12`): pending completed tests and a fresh consumer check.
