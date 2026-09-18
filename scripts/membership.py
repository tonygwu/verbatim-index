#!/usr/bin/env python3
"""Who is on which board. The only reader of membership.json.

Three boards publish from this one engine and, until this module, nobody was a
member of anything. grade.py scores every file it finds under --transcripts,
--roster only fills open-mode speaker names, and aggregate_predictions.py unions
the roster with any slug that happens to have records. Membership was therefore
whatever the directory listing said, which is how a sentence written into
data/roster/final.json during a 2026-09-05 finalize step -- "Pure investors and
commentators are out" -- became a governing rule that no code read and the
operator never approved.

THE DECISIVE DESIGN RULE.

    Membership decides what is READ, never what is WRITTEN.

An earlier draft had membership gate normalize's writes, which makes a config
file an input to a delete path. Measured hole: ten omitted leaders would delete
153 derived transcripts and orphan 514 grades, and 153 of 664 is 23.0%, under
prune_orphans' 25% ceiling, so it would happen silently. Nothing here is read by
a writer.

MEMBERSHIP IS LEADERS-ONLY, SO EVERY READER MUST BE STUDY-SCOPED. grade.py and
aggregate.py are shared with the pundits study, which is live in repo-3 and
whose slugs are not in this file. A caller applies membership only when
`args.study == SP.LEGACY_STUDY`; for any other study the call site is a no-op.
This module does not enforce that, because it never sees the study. The readers
do, and test_membership_study_scope covers it in P2.

THE LOOKUP SHAPE IS DELIBERATE, because the obvious idioms delete the raise.
`data.get(slug, [])` and `data.get(slug) or []` both turn an unknown slug into
an empty board, which is the silent wrong answer this module exists to refuse,
and neither fails any test that only asks about a slug it knows. So the shape is
`if slug not in data: raise`, and then a membership question is asked as
`"leaders" in data[slug]`, never as `if data[slug]`. `cc-wei` ships with an
empty list precisely so the two cases are distinguishable in a real fixture.

THE VALIDATION HERE IS STRUCTURAL ONLY: malformed JSON, an unknown slug, a board
name outside BOARDS. The whitelist is what catches a "leader"-for-"leaders"
typo, which is valid JSON carrying no unknown slug and which would otherwise
grade nobody, file every grade off-board with the accounting still balancing,
render zero leaders and publish. No count-based guard belongs here: a hardcoded
minimum would be a typed list read by three scripts, so one stale literal would
print AGGREGATE FAILED on every cycle in all three, and a legitimate withdrawal
is enough to make it stale. The count guards live in aggregate.py and deploy.sh,
where the counts are.

THE DEFAULT PATH IS RESOLVED FROM THIS FILE, not from the caller and not from
the working directory. test_render_integrity.py writes a modified copy of
aggregate.py into a temporary directory and runs it there, so a default anchored
anywhere else resolves into that temporary directory and fails. `--membership`
is the override and must be passed as an explicit argument. There is no
environment fallback, because a fallback is exactly the silently-disabled gate
this module exists to remove.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_PATH = REPO / "membership.json"

#: Every board this engine publishes from the leaders study. A name outside this
#: set is a typo, not a new board: adding a board is an edit here plus a reader.
BOARDS = ("leaders", "predictions")


def _no_duplicate_slugs(pairs: list[tuple[str, object]]) -> dict:
    """Refuse a slug declared twice, which json.loads would otherwise collapse.

    Python's decoder keeps the LAST value for a repeated key and says nothing.
    So a file declaring a slug twice, which is what a careless merge or a second
    edit produces, silently discards one of the two board lists. This file is
    edited by hand and by more than one clone, so that is a live shape rather
    than a hypothetical, and a silently discarded edit is exactly the quiet
    wrong answer this module exists to refuse.
    """
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"slug {key!r} is declared more than once; JSON would keep "
                             f"only the last board list and discard the other silently")
        seen[key] = value
    return seen


def load(path: str | Path | None = None) -> dict[str, list[str]]:
    """Read membership, validated. Raises RuntimeError; never returns a guess."""
    p = Path(path) if path is not None else DEFAULT_PATH
    if not p.is_file():
        raise RuntimeError(f"no membership file at {p}; membership is explicit and "
                           f"there is no default board for a slug")
    try:
        data = json.loads(p.read_text(), object_pairs_hook=_no_duplicate_slugs)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{p} is not valid JSON: {exc}") from exc
    except ValueError as exc:  # raised by the hook above; JSONDecodeError is caught first
        raise RuntimeError(f"{p}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{p} must be an object of slug -> boards, got {type(data).__name__}")
    for slug, boards in data.items():
        if not slug or not isinstance(slug, str):
            raise RuntimeError(f"{p} has an empty slug key")
        if not isinstance(boards, list):
            raise RuntimeError(f"{p}: {slug!r} must map to a list of boards, "
                               f"got {type(boards).__name__}")
        seen = set()
        for b in boards:
            if not isinstance(b, str):
                raise RuntimeError(f"{p}: {slug!r} has a board that is not a string: {b!r}")
            if b not in BOARDS:
                raise RuntimeError(f"{p}: {slug!r} names board {b!r}, which is not one of "
                                   f"{list(BOARDS)}; a near miss such as 'leader' for "
                                   f"'leaders' would silently empty the board")
            if b in seen:
                raise RuntimeError(f"{p}: {slug!r} names board {b!r} twice")
            seen.add(b)
    return data


def for_study(study: str, path: str | Path | None = None) -> dict[str, list[str]] | None:
    """The board for `study`, or None when membership does not apply to it.

    THE SCOPING RULE, IN ONE PLACE. membership.json describes the leaders study
    alone. grade.py, aggregate.py and build_site.py are shared with the pundits
    study, which is live in repo-3 and whose slugs are not in this file, so an
    unscoped reader would raise on the first pundit slug and stop that
    production on its next cycle.

    It lives here rather than as `if args.study == SP.LEGACY_STUDY:` repeated in
    three readers, because a condition written three times is a condition that
    can be got right twice. A caller writes:

        board = MB.for_study(args.study, args.membership)
        if board is not None:
            ...

    NOTE FOR ANYONE TESTING THIS: the pundits half cannot be proved end to end
    from repo-0. A pundits grade.py run refuses at "data-pundits is not a git
    checkout" and a pundits aggregate.py run refuses at the v2 contract check,
    both of them long before any reader, because repo-3 owns pundits production
    and this clone has no data-pundits link. That is why the scoping is a
    function with its own direct test rather than something only an end-to-end
    run could exercise.
    """
    import study_profile as SP
    if study != SP.LEGACY_STUDY:
        return None
    return load(path)


def boards_for(data: dict[str, list[str]], slug: str) -> list[str]:
    """The boards `slug` belongs to. An unknown slug RAISES.

    Deliberately not `data.get(slug, [])`: that answers "no boards" for a slug
    nobody declared, which is indistinguishable from a slug declared with none.
    """
    if slug not in data:
        raise RuntimeError(f"{slug!r} is not in membership.json. Every slug the pipeline "
                           f"reads must be declared, even with an empty board list; an "
                           f"undeclared slug is an error, not an empty board")
    return data[slug]


def on_board(data: dict[str, list[str]], slug: str, board: str) -> bool:
    """Whether `slug` publishes on `board`. An unknown slug or board RAISES."""
    if board not in BOARDS:
        raise RuntimeError(f"unknown board {board!r}; expected one of {list(BOARDS)}")
    return board in boards_for(data, slug)


def slugs_on(data: dict[str, list[str]], board: str) -> list[str]:
    """Every slug on `board`, in the file's own order. An unknown board RAISES."""
    if board not in BOARDS:
        raise RuntimeError(f"unknown board {board!r}; expected one of {list(BOARDS)}")
    return [slug for slug, boards in data.items() if board in boards]


def add_membership_arg(ap) -> None:
    """The override, as an EXPLICIT argument. There is no environment fallback."""
    ap.add_argument("--membership", default=None,
                    help="Path to membership.json, which declares which boards each slug "
                         "publishes on. Defaults to the copy beside this repository's "
                         "scripts/. Leaders study only; other studies ignore it.")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Print the membership of a board.")
    add_membership_arg(ap)
    ap.add_argument("--board", default=None, choices=list(BOARDS),
                    help="Print this board's slugs. Without it, print every slug and its boards.")
    args = ap.parse_args()
    d = load(args.membership)
    if args.board:
        for s in slugs_on(d, args.board):
            print(s)
        print(f"# {len(slugs_on(d, args.board))} on {args.board}, of {len(d)} declared")
    else:
        for s, b in d.items():
            print(f"{s}\t{','.join(b) if b else '-'}")
        print(f"# {len(d)} declared")
