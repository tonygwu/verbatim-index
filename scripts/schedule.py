#!/usr/bin/env python3
"""Build the seeded grading schedule the pundits plan requires, and read it back strictly.

Pundits plan, P5. The leaders queue is a sorted product ordered breadth-first,
which leaves two confounds the pundits study cannot accept. If people are graded
lean by lean, a quota stop or a judge's drift over the night lines up with lean.
If every blinded call runs before every open one, drift lines up with mode, and
the halo (open minus blinded) absorbs it. So:

  - transcripts are cut into time blocks of `block_size`;
  - within each lean, people are shuffled and their transcripts dealt round-robin,
    and the leans are interleaved, so every block mixes leans;
  - inside a block, each (transcript, judge) runs both modes back to back, and a
    seeded coin decides which mode goes first;
  - optional drift anchors: fixed transcripts re-graded in both modes by every
    judge once per `anchor_every` blocks, as run 1, 2, ...

A person with no lean label is refused rather than placed in a guessed stratum.
The manifest never contains a lean label: lean labels are private, and the
manifest is an operational file.

  schedule.py build --transcripts data-pundits/transcripts_blind \
      --lean-labels data-pundits/private/lean_labels.json \
      --judges fable,astra,gemini --block-size 20 --seed 20260914 \
      --anchors slug/source,slug/source --anchor-every 4 \
      --out data-pundits/logs/schedule/pilot.jsonl

Then: grade.py --study pundits --schedule data-pundits/logs/schedule/pilot.jsonl ...
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

MODES = ("blinded", "open")
FIELDS = ("block", "slug", "source_id", "judge", "mode", "run")


def build_schedule(items: list[tuple[str, str]], leans: dict[str, str], judges: list[str],
                   block_size: int = 20, seed: int = 0,
                   anchors: list[tuple[str, str]] | None = None,
                   anchor_every: int | None = None) -> list[dict]:
    if block_size < 1:
        raise ValueError("block_size must be at least 1")
    if not judges:
        raise ValueError("no judges")
    items = sorted(set(items))
    missing = sorted({slug for slug, _ in items if slug not in leans})
    if missing:
        raise RuntimeError(f"no lean label for {missing}; the schedule is stratified by lean and never "
                           f"guesses one")
    anchors = list(anchors or [])
    unknown = [a for a in anchors if a not in set(items)]
    if unknown:
        raise RuntimeError(f"anchor transcripts {unknown} are not in the schedule's transcripts")
    if anchors and not anchor_every:
        raise ValueError("anchors need anchor_every")

    rng = random.Random(seed)
    by_lean: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for slug, sid in items:
        by_lean[leans[slug]][slug].append(sid)

    queues: dict[str, list[tuple[str, str]]] = {}
    for lean in sorted(by_lean):
        people = sorted(by_lean[lean])
        rng.shuffle(people)
        stacks = {p: sorted(by_lean[lean][p]) for p in people}
        for p in people:
            rng.shuffle(stacks[p])
        q: list[tuple[str, str]] = []
        while any(stacks.values()):
            for p in people:
                if stacks[p]:
                    q.append((p, stacks[p].pop()))
        queues[lean] = q

    lean_order = sorted(queues)
    rng.shuffle(lean_order)
    order: list[tuple[str, str]] = []
    while any(queues.values()):
        for lean in lean_order:
            if queues[lean]:
                order.append(queues[lean].pop(0))

    entries: list[dict] = []

    def emit(slug: str, sid: str, block: int, run: int) -> None:
        for judge in judges:
            first = rng.choice(MODES)
            for mode in (first, MODES[1] if first == MODES[0] else MODES[0]):
                entries.append({"block": block, "slug": slug, "source_id": sid,
                                "judge": judge, "mode": mode, "run": run})

    n_blocks = math.ceil(len(order) / block_size)
    for b in range(n_blocks):
        for slug, sid in order[b * block_size:(b + 1) * block_size]:
            emit(slug, sid, b, 0)
        if anchors and (b + 1) % anchor_every == 0:
            group = (b + 1) // anchor_every
            for slug, sid in anchors:
                emit(slug, sid, b, group)
    return entries


def write_manifest(path: Path, entries: list[dict]) -> None:
    from atomicio import write_atomic
    write_atomic(Path(path), "".join(json.dumps(e, sort_keys=True) + "\n" for e in entries))


def read_manifest(path: Path) -> list[dict]:
    entries, seen = [], set()
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        e = json.loads(line)
        missing = [f for f in FIELDS if f not in e]
        if missing:
            raise RuntimeError(f"{path}:{n} is missing {missing}")
        if e["mode"] not in MODES or not isinstance(e["run"], int) or not isinstance(e["block"], int):
            raise RuntimeError(f"{path}:{n} has an invalid mode, run or block: {e}")
        key = (e["slug"], e["source_id"], e["judge"], e["mode"], e["run"])
        if key in seen:
            raise RuntimeError(f"{path}:{n} duplicates {key}")
        seen.add(key)
        entries.append(e)
    if not entries:
        raise RuntimeError(f"{path} holds no entries")
    return entries


def main() -> int:
    import study_profile as SP
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--transcripts", required=True)
    b.add_argument("--lean-labels", required=True, help="JSON object {slug: lean}. Private; never copied into the manifest.")
    b.add_argument("--judges", required=True)
    b.add_argument("--block-size", type=int, default=20)
    b.add_argument("--seed", type=int, required=True)
    b.add_argument("--anchors", default="", help="Comma-separated slug/source_id transcripts to re-grade per group.")
    b.add_argument("--anchor-every", type=int, default=None)
    b.add_argument("--out", required=True)
    SP.add_study_arg(b)
    args = ap.parse_args()
    SP.guard(args.study, args.transcripts, args.lean_labels, args.out)
    items = [(p.parent.name, p.stem) for p in sorted(Path(args.transcripts).rglob("*.json"))
             if not p.name.endswith(".tmp")]
    leans = json.loads(Path(args.lean_labels).read_text())
    anchors = [tuple(a.split("/", 1)) for a in args.anchors.split(",") if a.strip()]
    try:
        entries = build_schedule(items, leans, [j.strip() for j in args.judges.split(",") if j.strip()],
                                 args.block_size, args.seed, anchors, args.anchor_every)
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(f"REFUSING: {exc}") from None
    write_manifest(Path(args.out), entries)
    blocks = max(e["block"] for e in entries) + 1
    print(f"wrote {args.out}: {len(entries)} calls over {len(items)} transcripts in {blocks} blocks, seed {args.seed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
