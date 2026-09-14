# Independent data commits

Private checkout ownership, setup, and branch publication. Production scoring and model calls are outside scope.

Start with the overview, then choose the question you want to explore.

## 1. How agents publish independent data commits

What does an independent data checkout change?

The private remote supplies a committed snapshot to each independent checkout. Its owner preserves named outputs and pushes an owned branch. Live production remains a separate checkout. Promotion is a reviewed manual procedure outside these arrows.

[Mermaid diagram](sources/overview.mmd) · [FigJam source](sources/overview.figjam.mmd) · [D2](sources/overview.d2)

[Data examples and table schemas](data/overview.html) · [Native canvas card text](data/overview.json)

The diagrams use color and shape for component roles; status words identify what exists or is planned.

- **Shared production checkout** (Saved data; existing): Holds live data and one Git index managed by the production owner. Unmigrated clones share this directory.
- **Agent-owned experiment checkout** (Saved data; existing): Holds frozen inputs and owned results with a separate working tree, Git index, branch, and object store.
- **Private Git remote** (External software or service; existing): Stores committed snapshots and experiment branches for exchange between clones.

## 2. How one clone changes its data target

How are live files protected during migration?

The requesting agent runs setup. It checks the production source, prepares a separate clone, copies only named owned runs, and checks hashes and consumers before switching its symlink. The remote clone transfer is shown in the overview.

[Mermaid diagram](sources/migration.mmd) · [FigJam source](sources/migration.figjam.mmd) · [D2](sources/migration.d2)

[Data examples and table schemas](data/migration.html) · [Native canvas card text](data/migration.json)

The diagrams use color and shape for component roles; status words identify what exists or is planned.

- **Shared production checkout** (Saved data; existing): Holds live data and one Git index managed by the production owner. Unmigrated clones share this directory.
- **Prepare one independent checkout** (Program step - fixed rules; existing): Checks ownership and active consumers, clones committed inputs, and switches only the requesting data symlink.
- **Agent-owned experiment checkout** (Saved data; existing): Holds frozen inputs and owned results with a separate working tree, Git index, branch, and object store.
