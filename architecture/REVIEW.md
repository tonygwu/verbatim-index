# Review of private checkout ownership

The source scope is a small local trace. The evidence, flow, and operations reviews ran as separate local passes.

## Evidence review

E-1 — Accepted: documentation alone cannot prove that repo-4 migrated.
Read-only path resolution, the private Git directory, local role, branch, and upstream comparison establish the current layout.
The report records those observations separately from the generic model.

E-2 — Accepted: the old wording implied that every `data/` operation belonged to repo-0.
The agreement now distinguishes private experiment commits from changes to live production records.
The experiment output restrictions remain explicit.

## Flow review

F-1 — Accepted: cloning a committed snapshot does not copy live uncommitted inputs.
The model separates the remote clone flow from the optional copy of explicitly owned outputs.
The fixture proves that unrelated live edits remain absent from the independent checkout.

F-2 — Accepted: independent commits do not imply automatic production integration.
The overview states that promotion is a reviewed manual procedure outside its arrows.
The real Git conflict fixture proves that isolation does not reconcile conflicting records.

## Operations review

O-1 — Accepted: process inspection needs access outside the filesystem sandbox.
The first test stopped at `ps`. The authorized rerun passed with process inspection enabled.
The final consumer scan found only the named app helper processes referencing repo-4.

O-2 — Retained limitation: no local LikeC4 renderer was available.
The model validates, and the generated sources and data-card text were inspected.
No claim of rendered visual verification is made.

## Disposition

No code change is needed for independent commits and pushes.
The remaining fleet rollout uses the existing setup command from each requesting clone.
The review does not certify Git server access controls or authorize direct experiment pushes to private `main`.
