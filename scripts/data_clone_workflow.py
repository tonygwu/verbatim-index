#!/usr/bin/env python3
"""Independent experiment checkouts; no Git writes to the shared production tree."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

REPO = Path(__file__).resolve().parent.parent
ROLE_KEY = 'verbatim.role'
STATE_FILE = 'verbatim-clone.json'


def git(root: Path, *args: str) -> str:
    # Avoid read-only commands refreshing the shared index as a side effect.
    p = subprocess.run(['git', '-C', str(root), *args], text=True, capture_output=True,
                       env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    if p.returncode:
        raise RuntimeError(f'git {args[0]} in {root}: {p.stderr.strip()}')
    return p.stdout.strip()


def config(root: Path, key: str) -> str:
    p = subprocess.run(['git', '-C', str(root), 'config', '--local', '--get', key],
                       text=True, capture_output=True)
    return p.stdout.strip() if p.returncode == 0 else ''


def role(data: Path) -> str:
    return config(data, ROLE_KEY)


def production_path(repo: Path, study: str = 'leaders') -> Path:
    """The registered live checkout for a study.

    Leaders keeps its historical fallback to <repo parent>/data. Any other study
    has no fallback: its production checkout must be registered under its own
    config key, or nothing may publish or aggregate it.
    """
    import study_profile as SP
    prof = SP.load(study)
    configured = config(repo, prof['production_data_key'])
    if configured:
        return Path(configured).resolve()
    if study != SP.LEGACY_STUDY:
        raise RuntimeError(f"{prof['production_data_key']} is not set in {repo}; register the "
                           f"{study} production checkout explicitly")
    return (repo.parent / 'data').resolve()


def owner_error(repo: Path, study: str = 'leaders') -> str | None:
    import study_profile as SP
    try:
        data = (repo / SP.data_link(study)).resolve()
        SP.check_path(data, study)
    except RuntimeError as exc:
        return str(exc)
    if role(data) == 'experiment':
        return 'experiment data cannot run production jobs, even with a copied .daemon-clone marker'
    marker = data / '.daemon-clone'
    if not marker.is_file():
        return f'{marker} is missing; it must name the production owner'
    owner = marker.read_text().strip()
    if repo.resolve().name != owner:
        return f'this clone is {repo.name!r}, but {marker} names {owner!r}'
    return None


def publication_source(repo: Path, source: Path | None, revision: str | None,
                       study: str = 'leaders') -> Path:
    import study_profile as SP
    if source is None or not revision:
        raise RuntimeError('explicit --production-data and --data-revision are required')
    source = source.resolve()
    live = production_path(repo, study)
    if source != live or role(source) == 'experiment':
        raise RuntimeError(f'production source must be {live}; got {source}')
    SP.check_path(source, study)
    marker = source / '.daemon-clone'
    if not marker.is_file() or not marker.read_text().strip():
        raise RuntimeError('production source has no .daemon-clone owner')
    if not re.fullmatch(r'[0-9a-f]{40}', revision) or git(source, 'rev-parse', 'HEAD') != revision:
        raise RuntimeError('production data revision must be the full current HEAD SHA')
    if git(source, 'rev-parse', '--show-toplevel') != str(source):
        raise RuntimeError('production source must be a private repository root')
    return source


def tree_hashes(root: Path) -> dict[str, str]:
    if root.is_symlink():
        raise RuntimeError(f'symlink is not an owned regular output: {root}')
    if not root.is_dir():
        raise RuntimeError(f'missing experiment directory: {root}')
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise RuntimeError(f'symlink is not an owned regular output: {path}')
        if path.is_file():
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif not path.is_dir():
            raise RuntimeError(f'not a regular output: {path}')
    return result


def owned_path(value: str) -> Path:
    p = Path(value)
    if (p.is_absolute() or len(p.parts) != 3 or p.parts[:2] != ('predictions', '_experiments')
            or p.parts[2] in ('.', '..') or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', p.parts[2])):
        raise RuntimeError('--copy-owned must name one whole experiment: predictions/_experiments/RUN')
    return p


def copy_owned(source: Path, dest: Path, paths: list[str]) -> dict:
    for p in paths:
        if (source / owned_path(p)).resolve() != source / p:
            raise RuntimeError(f'symlink in source experiment path: {p}')
    before = {p: tree_hashes(source / owned_path(p)) for p in paths}
    # Preflight ALL collisions before the first copy. Never overwrite a result.
    for rel, files in before.items():
        target = dest / rel
        for ancestor in (target, *target.parents):
            if ancestor == dest:
                break
            if ancestor.is_symlink():
                raise RuntimeError(f'copy conflict: symlink at {ancestor}')
        existing = tree_hashes(target) if target.exists() else {}
        if any(name not in files or files[name] != digest for name, digest in existing.items()):
            raise RuntimeError(f'copy conflict in {target}; both versions are preserved')
    for rel, files in before.items():
        target = dest / rel
        target.mkdir(parents=True, exist_ok=True)
        for name in files:
            out = target / name
            out.parent.mkdir(parents=True, exist_ok=True)
            if not out.exists():
                # Exclusive creation also refuses a collision arriving after preflight.
                with out.open('xb') as stream:
                    stream.write((source / rel / name).read_bytes())
                shutil.copystat(source / rel / name, out, follow_symlinks=False)
        if tree_hashes(target) != files or tree_hashes(source / rel) != files:
            raise RuntimeError(f'owned outputs changed during copy: {rel}; symlink was not switched')
    return before


def active_consumers(repo: Path) -> list[dict]:
    """Conservative same-user process check: cwd, open files, and explicit clone paths.

    Ancestors are the invoking terminal/agent, not background jobs. Do not start
    new work in this clone between this check and the atomic symlink switch.
    Inability to inspect processes is a refusal, never evidence of an idle clone.
    """
    ps = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,command='], text=True)
    rows = {}
    for line in ps.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) == 3:
            rows[int(fields[0])] = (int(fields[1]), fields[2])
    ancestors = {os.getpid()}
    pid = os.getpid()
    while pid in rows and rows[pid][0] not in ancestors:
        pid = rows[pid][0]
        ancestors.add(pid)
    proc = subprocess.run(['lsof', '-nP', '-u', str(os.getuid()), '-Fpn'], text=True, capture_output=True, timeout=30)
    if proc.returncode not in (0, 1) or not proc.stdout:
        raise RuntimeError(f'cannot inspect active consumers with lsof: {proc.stderr.strip()}')
    refs = {}
    pid = None
    for line in proc.stdout.splitlines():
        if line.startswith('p') and line[1:].isdigit():
            pid = int(line[1:])
        elif pid is not None and line.startswith('n'):
            name = line[1:]
            if name == str(repo) or name.startswith(str(repo) + '/'):
                refs.setdefault(pid, []).append(name)
    matches = []
    for pid, (_, command) in rows.items():
        if pid in ancestors:
            continue
        if pid in refs or re.search(re.escape(str(repo)) + r'(?:/|\s|$)', command):
            matches.append({'pid': pid, 'command': command[:300], 'paths': refs.get(pid, [])[:3]})
    return matches


def assert_idle(repo: Path) -> None:
    consumers = active_consumers(repo)
    if consumers:
        raise RuntimeError('active consumers; migration pending: ' + json.dumps(consumers))


def write_state(path: Path, value: dict) -> None:
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(temp, path)


def setup(repo: Path, source: Path, revision: str, branch: str,
          copies: list[str], *, apply: bool = False) -> Path:
    repo, source = repo.resolve(), source.resolve()
    link, dest = repo / 'data', repo / '.data-clones' / 'experiment'
    if dest.parent.is_symlink():
        raise RuntimeError('private clone destination parent must not be a symlink')
    for rel in copies:
        owned_path(rel)
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise RuntimeError('--revision must be a full data commit SHA')
    if not branch.startswith('codex/'):
        raise RuntimeError('use an owned codex/ branch, never private main')
    git(repo, 'check-ref-format', '--branch', branch)
    if role(source) == 'experiment':
        raise RuntimeError('source must be the live production checkout, not an experiment')
    marker = source / '.daemon-clone'
    if not marker.is_file() or not marker.read_text().strip():
        raise RuntimeError('source has no production owner marker')
    if repo.name == marker.read_text().strip():
        raise RuntimeError('the production owner cannot migrate its live data checkout')
    if source == dest.resolve() or source == repo or repo in source.parents:
        raise RuntimeError('source must be a separate production checkout')
    if git(source, 'rev-parse', '--show-toplevel') != str(source):
        raise RuntimeError('source must be the root of the private production repository')
    git(source, 'cat-file', '-e', revision + '^{commit}')
    origin = git(source, 'remote', 'get-url', 'origin')
    if git(repo, 'check-ignore', 'data', '.data-clones/experiment') == '':
        raise RuntimeError('data and .data-clones must be ignored by the public repository')
    for ignored in ('data', '.data-clones/experiment'):
        git(repo, 'check-ignore', ignored)
    if git(repo, 'ls-files', 'data', '.data-clones'):
        raise RuntimeError('public index already tracks private paths; repair it before migration')
    if link.exists() or link.is_symlink():
        if not link.is_symlink() or link.resolve() not in (source, dest.resolve()):
            raise RuntimeError('data must be absent or the requesting clone’s known symlink')
    plan = {'owner': str(repo), 'source': str(source), 'revision': revision,
            'branch': branch, 'origin': origin, 'copy_owned': sorted(set(copies))}
    state_path = dest / '.git' / STATE_FILE
    state = json.loads(state_path.read_text()) if state_path.is_file() else None
    if dest.exists():
        if not state or any(state.get(k) != v for k, v in plan.items()):
            raise RuntimeError(f'prepared clone conflict at {dest}; preserved, not reset')
        if (not (dest / '.git').is_dir() or (dest / '.git').is_symlink()
                or (dest / '.git/objects/info/alternates').exists()
                or role(dest) != 'experiment' or git(dest, 'branch', '--show-current') != branch
                or git(dest, 'remote', 'get-url', 'origin') != origin):
            raise RuntimeError('prepared clone identity or independence changed')
        if link.resolve() == dest.resolve() and state.get('ready'):
            print(f'already migrated: {link} -> {dest}; existing work retained')
            return dest
    for rel in copies:
        tree_hashes(source / rel)
    print(json.dumps({'mode': 'apply' if apply else 'dry-run', **plan, 'destination': str(dest)}, indent=2))
    if not apply:
        return dest
    assert_idle(repo)
    if not dest.exists():
        dest.parent.mkdir(exist_ok=True)
        # Remote transport (also for local test remotes): no shared objects/index,
        # no worktree, no alternates, no files from the live working tree.
        subprocess.run(['git', 'clone', '--no-local', '--no-checkout', origin, str(dest)], check=True)
        refs = git(dest, 'for-each-ref', '--format=%(refname)', 'refs/remotes/origin/' + branch)
        if refs:
            raise RuntimeError(f'branch already exists on the private remote: {branch}; choose a unique branch')
        git(dest, 'switch', '-c', branch, revision)
        git(dest, 'config', ROLE_KEY, 'experiment')
        git(dest, 'config', 'verbatim.owner', str(repo))
        git(dest, 'config', 'user.email', '446441+tonygwu@users.noreply.github.com')
        git(dest, 'config', 'user.name', git(repo, 'config', 'user.name'))
        git(dest, 'config', 'push.default', 'current')
        state = {**plan, 'ready': False}
        write_state(state_path, state)
    if (dest / '.daemon-clone').exists():
        raise RuntimeError('prepared experiment contains a production owner marker; refusing switch')
    if git(dest, 'rev-parse', 'HEAD') != revision:
        raise RuntimeError('prepared clone moved before migration; refusing to reset it')
    hashes = copy_owned(source, dest, copies)
    git(dest, 'fsck', '--connectivity-only')
    assert_idle(repo)
    if (link.exists() or link.is_symlink()) and (not link.is_symlink() or link.resolve() != source):
        raise RuntimeError('data symlink changed during preparation; preserved without switching')
    for rel, expected in hashes.items():
        if tree_hashes(source / rel) != expected or tree_hashes(dest / rel) != expected:
            raise RuntimeError('owned outputs changed before switch; migration pending')
    # Only the requesting PUBLIC clone's local config is changed.
    git(repo, 'config', 'verbatim.productionData', str(source))
    write_state(state_path, {**plan, 'ready': True, 'copied_sha256': hashes})
    temp_link = repo / '.data-clones' / ('link-' + uuid.uuid4().hex)
    temp_link.symlink_to(dest, target_is_directory=True)
    os.replace(temp_link, link)
    print(f'migrated: {link} -> {dest}; shared source and original outputs unchanged')
    return dest


SITE_SHELVES = {
    'leaderboard': ['results.json', 'results_audit.json', 'roster/final.json',
                    'logs/calibration.json', 'sources/discovered.json', 'grades'],
    'pundits': ['results.json', 'results_audit.json', 'roster/final.json',
                'logs/calibration.json', 'sources/discovered.json', 'grades'],
    'predictions': ['predictions', 'roster/final.json'],
}

#: Render inputs that live in the PUBLIC repository rather than the data
#: checkout, per site. Declared explicitly and per site, never guessed: binding
#: the predictions render to membership.json would refuse deploys over an input
#: build_predictions_site.py has never read. Every key in SITE_SHELVES needs an
#: entry here, and test_publication_fingerprint_inputs.py asserts that.
SITE_REPO_INPUTS = {
    'leaderboard': ('membership.json',),
    'pundits': (),
    'predictions': (),
}


def fingerprint(source: Path, site: str, repo: Path | None = None) -> str:
    """Bind one render to the live bytes read, including dirty production files.

    An unknown site is refused. It used to fall through to the predictions
    shelves, so any new site would have been fingerprinted on the wrong files.

    SOME RENDER INPUTS ARE NOT IN THE DATA CHECKOUT. `membership.json` lives at
    the root of the PUBLIC repository and, since P2 of the board-membership work,
    it decides which grades reach `usable`, how many people the page says are on
    the roster, and which transcripts count toward the words-graded total. It is
    therefore hashed too, from `SITE_REPO_INPUTS`, or an edit between the before
    and after checks would change the published page with the guard still
    passing. MEASURED before this: retyping every board name left the fingerprint
    byte-identical.

    `scripts/` is deliberately NOT covered. Code is tracked, reviewed and pinned
    by the commit being deployed; `membership.json` is a config file edited by
    hand that now moves the board.
    """
    if site not in SITE_SHELVES:
        raise RuntimeError(f'unknown publication site {site!r}; known: {sorted(SITE_SHELVES)}')
    shelves = SITE_SHELVES[site]
    hashes = {}
    root = Path(repo) if repo is not None else REPO
    for name in SITE_REPO_INPUTS.get(site, ()):
        p = root / name
        if not p.is_file():
            raise RuntimeError(
                f'{p} is missing, and it is a render input for {site!r}. Hashing '
                f'nothing here would make a deleted gate look like an unchanged '
                f'one, so publication is refused instead.')
        hashes[f'<repo>/{name}'] = hashlib.sha256(p.read_bytes()).hexdigest()
    for shelf in shelves:
        base = source / shelf
        paths = base.rglob('*') if base.is_dir() else [base]
        for p in sorted(paths):
            rel = p.relative_to(source)
            if any(part.startswith('_') for part in rel.parts):
                continue
            if p.is_file():
                hashes[str(rel)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()


def prediction_inputs_sha256(predictions: Path) -> str:
    """One digest of the record and sidecar bytes a predictions index is built from.

    Counts cannot see an in-place rewrite. Verification and market consensus change
    records without adding lines, so an index can match every count and still
    describe an older corpus. Directories starting with _ are skipped, as
    aggregate_predictions.py skips them.
    """
    files = sorted(p for pattern in ('*/*.jsonl', '*/*.meta.json') for p in predictions.glob(pattern)
                   if not p.parent.name.startswith('_'))
    h = hashlib.sha256()
    for p in files:
        h.update(f'{p.relative_to(predictions)}\0{hashlib.sha256(p.read_bytes()).hexdigest()}\n'.encode())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Freshness of the derived predictions files. These live here, beside
# prediction_inputs_sha256, and not in the scripts that build the files,
# because the deploy and data_sync.py must check freshness without importing
# the model harness that predictions_lib pulls in.
# ---------------------------------------------------------------------------

# Every key a scoring config must carry, and nothing else. A missing key refuses
# rather than defaulting, because a default here silently changes a published
# number; an unknown key refuses because it is usually a typo of a real one.
CONFIG_KEYS = ("as_of", "trend", "min_lead_days", "predictions", "runs", "index", "out")
SIDECAR_DIRS = ("resolutions", "priors", "criteria_repairs")


def transcript_listing(roots: list[Path]) -> set[tuple[str, str]]:
    """(slug, stem) of every transcript file under the roots. A named root that is
    missing raises: counting it as zero is how "22 of 15" reached the page."""
    out: set[tuple[str, str]] = set()
    for root in roots:
        if not root.is_dir():
            raise FileNotFoundError(f"transcript root {root} does not exist")
        out.update((p.parent.name, p.stem) for p in root.glob("*/*.json"))
    return out


def listing_sha256(listing: set[tuple[str, str]]) -> str:
    return hashlib.sha256("".join(f"{s}/{t}\n" for s, t in sorted(listing)).encode()).hexdigest()


def count_records(pred_root: Path) -> tuple[int, int]:
    files = [p for p in pred_root.glob("*/*.jsonl") if not p.parent.name.startswith("_")]
    return len(files), sum(1 for p in files for _ in p.open())


def index_staleness(index: dict, pred_root: Path, roster_path: Path, roots: list[Path]) -> str | None:
    """None when every input the index read is unchanged on disk; otherwise a
    message naming the input that moved. Refuses an index that predates a
    fingerprint, because such an index cannot be proved current."""
    for k in ("files_read", "records_read", "inputs_sha256", "roster_sha256", "transcripts_listing_sha256"):
        if index.get(k) is None:
            return f"index.json lacks {k}, so its freshness cannot be checked; re-run aggregate_predictions.py"
    roster_now = hashlib.sha256(Path(roster_path).read_bytes()).hexdigest()
    if index["roster_sha256"] != roster_now:
        return (f"the roster changed since the index was built (index {index['roster_sha256'][:12]}, "
                f"disk {roster_now[:12]}); the index unions roster slugs, so it lists the wrong people")
    files, lines = count_records(pred_root)
    if (index["files_read"], index["records_read"]) != (files, lines):
        return (f"record counts changed: index read {index['files_read']} files / {index['records_read']} "
                f"records, disk has {files} / {lines}")
    digest = prediction_inputs_sha256(pred_root)
    if index["inputs_sha256"] != digest:
        return (f"record contents changed in place: counts match ({files} files, {lines} records) but "
                f"inputs sha256 is {digest[:12]}, index says {index['inputs_sha256'][:12]}")
    listing = listing_sha256(transcript_listing(roots))
    if index["transcripts_listing_sha256"] != listing:
        return (f"the transcript listing changed (index {index['transcripts_listing_sha256'][:12]}, "
                f"disk {listing[:12]}); coverage counts are stale")
    return None


def load_scoring_config(path: Path) -> tuple[Path, dict]:
    """(data root, config). The root is the config file's grandparent, since the
    config lives at <data>/predictions/scoring.json and its paths are relative to
    <data>."""
    cfg = json.loads(Path(path).read_text())
    missing = [k for k in CONFIG_KEYS if k not in cfg]
    unknown = sorted(set(cfg) - set(CONFIG_KEYS))
    if missing or unknown:
        raise SystemExit(f"{path}: missing keys {missing}, unknown keys {unknown}; "
                         f"a scoring config carries exactly {list(CONFIG_KEYS)}")
    if not isinstance(cfg["trend"], bool) or not isinstance(cfg["min_lead_days"], int) \
            or not cfg["predictions"] or not cfg["runs"]:
        raise SystemExit(f"{path}: trend must be a boolean, min_lead_days an integer, and predictions "
                         f"and runs non-empty lists")
    return Path(path).resolve().parent.parent, cfg


def scoring_rel(path: Path, root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(root))
    except ValueError:
        raise SystemExit(f"{path} is outside the data root {root}; every scoring input must live under it")


def score_inputs_sha256(root: Path, settings: dict) -> str:
    """One digest of everything a scores.json is computed from: the settings, the
    records, the index it takes names from, and every sidecar in every run."""
    h = hashlib.sha256()
    h.update(json.dumps(settings, sort_keys=True).encode() + b"\n")
    for pd in settings["predictions"]:
        h.update(f"records {pd} {prediction_inputs_sha256(root / pd)}\n".encode())
    h.update(f"index {hashlib.sha256((root / settings['index']).read_bytes()).hexdigest()}\n".encode())
    for run in settings["runs"]:
        for sub in SIDECAR_DIRS:
            for f in sorted((root / run / sub).glob("*/*.json")):
                h.update(f"{run}/{f.relative_to(root / run)} {hashlib.sha256(f.read_bytes()).hexdigest()}\n".encode())
    return h.hexdigest()


def settings_from_config(cfg: dict) -> dict:
    return {k: cfg[k] for k in ("as_of", "trend", "min_lead_days", "predictions", "runs", "index")}


def scores_staleness(scores_path: Path, config_path: Path) -> str | None:
    """None when scores.json was computed from exactly the inputs on disk now."""
    root, cfg = load_scoring_config(config_path)
    doc = json.loads(Path(scores_path).read_text())
    if not doc.get("inputs_sha256"):
        return "scores.json lacks inputs_sha256, so its freshness cannot be checked; re-run score_predictions.py"
    want = settings_from_config(cfg)
    if doc.get("settings") != want:
        return f"scores.json was computed with settings {doc.get('settings')}, the config now says {want}"
    now = score_inputs_sha256(root, want)
    if doc["inputs_sha256"] != now:
        return (f"an input changed since scores.json was computed (scores {doc['inputs_sha256'][:12]}, "
                f"disk {now[:12]}): a record, a sidecar or the index")
    return None




def guard_prediction_write(repo: Path, path: Path, root: Path, study: str = 'leaders') -> None:
    path, root = path.resolve(), root.resolve()
    if role(root) != 'experiment':
        return
    live = production_path(repo, study)
    if path == live or live in path.parents:
        raise RuntimeError('experiment clone cannot write the shared production checkout')
    if path == root or root in path.parents:
        allowed = root / 'predictions' / '_experiments'
        if allowed not in path.parents or len(path.relative_to(allowed).parts) < 1:
            raise RuntimeError(f'experiment writes require {allowed}/UNIQUE-RUN/')


def guard_aggregate(repo: Path, path: Path, study: str = 'leaders') -> None:
    import study_profile as SP
    SP.check_path(path, study)
    path = path.resolve()
    own = (repo / SP.data_link(study)).resolve()
    try:
        live = production_path(repo, study)
    except RuntimeError:
        # A study with no registered production checkout: its own link is the
        # only thing that could be production, so writing under it still needs
        # the owner. Anything else is not production and is allowed.
        live = own
    if path == live or live in path.parents:
        why = owner_error(repo, study)
        if why or own != live:
            raise RuntimeError(why or 'production aggregation requires the production owner')
    guard_prediction_write(repo, path, own, study)


def new_run(repo: Path, name: str, extractor: str, verifier: str, astra_model: str) -> Path:
    import predictions_lib as L
    data = (repo / 'data').resolve()
    if role(data) != 'experiment':
        raise RuntimeError('new-run requires an independent experiment clone')
    rel = owned_path('predictions/_experiments/' + name)
    manifest = {
        'schema_version': 1, 'experiment_id': name,
        'input_data_commit': git(data, 'rev-parse', 'HEAD'),
        'input_worktree_dirty': bool(git(data, 'status', '--porcelain')),
        'code_commit': git(repo, 'rev-parse', 'HEAD'),
        'code_worktree_dirty': bool(git(repo, 'status', '--porcelain')),
        'policy_release': L.load_policy_release(),
        'extraction_contract': L.extraction_contract(),
        'verification_contract': L.verification_contract(),
        'requested_models': {'extractor': extractor, 'verifier': verifier, 'astra_model': astra_model},
        'served_model_evidence': 'Use each result’s extraction/verification model and raw call telemetry; requested identity is not served identity.',
        'input_evidence': 'Each stage audit hashes its actual input bundle and exact prompts.',
    }
    out = data / rel
    # Exist-ok would silently mix two experiments with the same display name.
    out.mkdir(parents=True, exist_ok=False)
    write_state(out / 'experiment.json', manifest)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    s = sub.add_parser('setup', help='dry-run by default; --apply prepares then switches this clone only')
    s.add_argument('--source', type=Path, required=True)
    s.add_argument('--revision', required=True)
    s.add_argument('--branch', required=True)
    s.add_argument('--copy-owned', action='append', default=[])
    mode = s.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--dry-run', action='store_true')
    n = sub.add_parser('new-run', help='reserve a unique run directory and pin its provenance')
    n.add_argument('--name', required=True)
    n.add_argument('--extractor', required=True)
    n.add_argument('--verifier', required=True)
    n.add_argument('--astra-model', default='gpt-6-astra')
    sub.add_parser('consumers', help='inspect this clone without changing jobs')
    p = sub.add_parser('publication-source')
    p.add_argument('--production-data', type=Path)
    p.add_argument('--data-revision')
    p.add_argument('--site', choices=sorted(SITE_SHELVES))
    p.add_argument('--study', default=os.environ.get('STUDY') or 'leaders')
    p.add_argument('--fingerprint', action='store_true')
    args = ap.parse_args()
    try:
        if args.command == 'setup':
            setup(REPO, args.source, args.revision, args.branch, args.copy_owned, apply=args.apply)
        elif args.command == 'new-run':
            print(new_run(REPO, args.name, args.extractor, args.verifier, args.astra_model))
        elif args.command == 'consumers':
            print(json.dumps(active_consumers(REPO), indent=2))
        else:
            source = publication_source(REPO, args.production_data, args.data_revision, args.study)
            print(fingerprint(source, args.site) if args.fingerprint else source)
        return 0
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f'REFUSING: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
