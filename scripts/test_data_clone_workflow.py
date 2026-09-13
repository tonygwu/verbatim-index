#!/usr/bin/env python3
"""Quota-free integration tests. Every Git write and fake deployment uses temp repos."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'scripts'))


def run(*args, cwd=None, ok=True):
    p = subprocess.run([str(a) for a in args], cwd=cwd, text=True, capture_output=True)
    if ok and p.returncode:
        raise AssertionError(f'{args}: {p.stdout}\n{p.stderr}')
    return p


def git(path, *args, ok=True):
    return run('git', '-C', path, *args, ok=ok).stdout.strip()


def rejected(fn, needle):
    try:
        fn()
    except (RuntimeError, ValueError) as exc:
        assert needle in str(exc), str(exc)
    else:
        raise AssertionError(f'expected rejection: {needle}')


def main():
    import data_clone_workflow as D
    with tempfile.TemporaryDirectory(prefix='data-clone-test-') as td:
        t = Path(td).resolve()
        live = t / 'data'
        live.mkdir()
        git(live, 'init', '-b', 'main')
        git(live, 'config', 'user.email', '446441+tonygwu@users.noreply.github.com')
        git(live, 'config', 'user.name', 'Fixture')
        (live / '.gitignore').write_text('.daemon-clone\n')
        (live / 'input.txt').write_text('frozen input\n')
        git(live, 'add', '.gitignore', 'input.txt')
        git(live, 'commit', '-m', 'baseline')
        revision = git(live, 'rev-parse', 'HEAD')
        remote = t / 'remote.git'
        run('git', 'clone', '--bare', live, remote)
        git(live, 'remote', 'add', 'origin', str(remote))
        (live / '.daemon-clone').write_text('repo-0\n')
        (live / 'input.txt').write_text('uncommitted production edit\n')
        owned = 'predictions/_experiments/owned-run'
        (live / owned).mkdir(parents=True)
        (live / owned / 'raw.txt').write_text('irreplaceable private output\n')
        (live / owned / 'raw.txt').chmod(0o755)
        (live / 'someone-elses-output').write_text('leave me alone\n')
        live_index = (live / '.git/index').read_bytes()
        original = D.tree_hashes(live / owned)

        def public(name):
            p = t / name
            p.mkdir()
            git(p, 'init', '-b', 'main')
            git(p, 'config', 'user.name', 'Fixture')
            git(p, 'config', 'user.email', '446441+tonygwu@users.noreply.github.com')
            (p / '.gitignore').write_text('/data\n/.data-clones/\n')
            git(p, 'add', '.gitignore')
            git(p, 'commit', '-m', 'public fixture')
            (p / 'data').symlink_to(live, target_is_directory=True)
            return p

        a, b, owner = public('repo-4'), public('repo-5'), public('repo-0')
        branch = 'codex/repo-4-test'
        # Dry run does not even create a destination or edit a Git config/index.
        D.setup(a, live, revision, branch, [owned], apply=False)
        assert not (a / '.data-clones').exists()
        assert (a / 'data').resolve() == live
        rejected(lambda: D.setup(owner, live, revision, 'codex/owner', [], apply=True), 'production owner')
        rejected(lambda: D.setup(a, live, revision, branch, ['input.txt'], apply=True), 'whole experiment')
        rejected(lambda: D.setup(a, live, revision, branch, ['predictions/_experiments/../bad'], apply=True), 'whole experiment')
        # An active consumer blocks the switch. No arbitrary process is killed.
        consumer = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], cwd=a)
        try:
            rejected(lambda: D.setup(a, live, revision, branch, [owned], apply=True), 'active consumers')
        finally:
            consumer.terminate()
            consumer.wait(timeout=5)
        D.setup(a, live, revision, branch, [owned], apply=True)
        da = (a / 'data').resolve()
        assert da != live and (da / '.git').is_dir()
        assert not (da / '.git/objects/info/alternates').exists()
        assert (da / '.git/index').stat().st_ino != (live / '.git/index').stat().st_ino
        assert (da / 'input.txt').read_text() == 'frozen input\n'
        assert not (da / 'someone-elses-output').exists()
        assert not (da / '.daemon-clone').exists()
        rejected(lambda: D.guard_prediction_write(a, da / 'predictions/index.json', da), 'UNIQUE-RUN')
        rejected(lambda: D.guard_prediction_write(a, live / 'predictions/index.json', da), 'shared production')
        D.guard_prediction_write(a, da / owned / 'results.json', da)
        rejected(lambda: D.guard_aggregate(a, live / 'results.json'), 'experiment')
        D.guard_aggregate(owner, live / 'results.json')
        assert D.tree_hashes(da / owned) == original == D.tree_hashes(live / owned)
        assert (da / owned / 'raw.txt').stat().st_mode & 0o777 == 0o755
        assert (live / '.git/index').read_bytes() == live_index
        D.setup(a, live, revision, branch, [owned], apply=True)  # repeatable, no reset
        git(da, 'add', owned)
        git(da, 'commit', '-m', 'preserved experiment')
        git(da, 'push', '-u', 'origin', branch)
        assert git(live, 'rev-parse', 'HEAD') == revision
        assert git(da, 'status', '--porcelain') == ''
        assert git(a, 'status', '--porcelain') == ''  # no private material in public index
        D.setup(b, live, revision, 'codex/repo-5-test', [], apply=True)
        db = (b / 'data').resolve()
        assert not (db / owned).exists()
        assert git(db, 'rev-parse', 'HEAD') == revision
        # Independent incompatible edits produce a real Git conflict; no shared write.
        for data, content in ((da, 'arm A\n'), (db, 'arm B\n')):
            (data / 'input.txt').write_text(content)
            git(data, 'add', 'input.txt')
            git(data, 'commit', '-m', content.strip())
        git(db, 'fetch', str(da), 'HEAD')
        conflict = run('git', '-C', db, 'cherry-pick', 'FETCH_HEAD', ok=False)
        assert conflict.returncode != 0 and git(db, 'ls-files', '-u')
        git(db, 'cherry-pick', '--abort')
        assert (db / 'input.txt').read_text() == 'arm B\n'
        assert (live / 'input.txt').read_text() == 'uncommitted production edit\n'
        # Migration copy collisions and symlink escapes never overwrite either side.
        (da / owned / 'raw.txt').write_text('different result')
        rejected(lambda: D.copy_owned(live, da, [owned]), 'conflict')
        assert D.tree_hashes(live / owned) == original
        (live / owned / 'escape').symlink_to(live / 'input.txt')
        rejected(lambda: D.tree_hashes(live / owned), 'symlink')
        (live / owned / 'escape').unlink()
        # Experiment role defeats a copied daemon marker, even on the owner name.
        (da / '.daemon-clone').write_text('repo-4\n')
        assert 'experiment' in D.owner_error(a)
        assert D.owner_error(owner) is None
        # Publication needs an explicit, registered live path and exact revision.
        assert D.publication_source(a, live, revision) == live
        rejected(lambda: D.publication_source(a, da, git(da, 'rev-parse', 'HEAD')), 'production source')
        rejected(lambda: D.publication_source(a, live, '0' * 40), 'revision')
        rejected(lambda: D.publication_source(a, None, revision), 'explicit')
        stale = t / 'stale'
        run('git', 'clone', remote, stale)
        (stale / '.daemon-clone').write_text('repo-0\n')
        rejected(lambda: D.publication_source(a, stale, revision), 'production source')
        # Both shell entry points reject missing/experimental sources before render/deploy.
        (a / 'scripts').mkdir()
        (a / '.venv/bin').mkdir(parents=True)
        (a / '.venv/bin/python').symlink_to(sys.executable)
        for name in ('data_clone_workflow.py', 'daemon_guard.sh', 'deploy_source.sh',
                     'deploy.sh', 'deploy_predictions.sh'):
            shutil.copy2(REPO / 'scripts' / name, a / 'scripts' / name)
        p = run('bash', '-c', '. scripts/daemon_guard.sh; require_daemon_clone', cwd=a, ok=False)
        assert p.returncode and 'experiment' in p.stderr
        for script in ('deploy.sh', 'deploy_predictions.sh'):
            p = run('bash', a / 'scripts' / script, '--dry-run', ok=False)
            assert p.returncode and 'REFUSING' in p.stderr, p.stderr
            p = run('bash', a / 'scripts' / script, '--production-data', da,
                    '--data-revision', git(da, 'rev-parse', 'HEAD'), '--dry-run', ok=False)
            assert p.returncode and 'production source' in p.stderr, p.stderr
        # A legitimate live source renders using explicit source arguments. The
        # npx stub is a tripwire: even a broken test cannot deploy anything.
        bin_dir = t / 'bin'
        bin_dir.mkdir()
        tripwire = bin_dir / 'npx'
        tripwire.write_text('#!/bin/sh\necho DEPLOY-TRIPWIRE >&2\nexit 93\n')
        tripwire.chmod(0o755)
        old_path = os.environ['PATH']
        os.environ['PATH'] = str(bin_dir) + os.pathsep + old_path
        try:
            (live / 'results.json').write_text(json.dumps({
                'leaders': [], 'diagnostics': {'grades_used': 0, 'grade_files_read': 0}}))
            (live / 'predictions/index.json').write_text(json.dumps({
                'leaders': [], 'corpus': {'accepted': 0, 'transcripts_with_accepted': 0},
                'run_ids_seen': [], 'generated_at_utc': 'fixture', 'files_read': 0, 'records_read': 0}))
            (live / 'roster').mkdir()
            (live / 'roster/final.json').write_text('{}')
            renderer = """import pathlib, sys
args = sys.argv[1:]
source_flag = '--results' if '--results' in args else '--index'
assert pathlib.Path(args[args.index(source_flag) + 1]).resolve().is_relative_to(pathlib.Path(sys.argv[0]).resolve().parents[2] / 'data')
out = pathlib.Path(args[args.index('--out') + 1])
out.parent.mkdir(exist_ok=True)
out.write_text('rendered from explicit production source')
"""
            for name in ('build_site.py', 'build_predictions_site.py'):
                (a / 'scripts' / name).write_text(renderer)
            for script in ('deploy.sh', 'deploy_predictions.sh'):
                p = run('bash', a / 'scripts' / script, '--production-data', live,
                        '--data-revision', revision, '--dry-run')
                assert 'published nothing' in p.stdout and 'content sha256' in p.stdout
                assert 'DEPLOY-TRIPWIRE' not in p.stderr
            # A changed input during render is rejected even when counts match.
            with (a / 'scripts/build_site.py').open('a') as f:
                f.write("\npathlib.Path(args[args.index('--results') + 1]).write_text(' {\"leaders\":[],\"diagnostics\":{\"grades_used\":0,\"grade_files_read\":0}}')\n")
            p = run('bash', a / 'scripts/deploy.sh', '--production-data', live,
                    '--data-revision', revision, '--dry-run', ok=False)
            assert p.returncode and 'changed during rendering' in p.stderr, p.stderr
            # Existing count drift blocks publication before npx too.
            (live / 'predictions/index.json').write_text(json.dumps({
                'leaders': [], 'corpus': {'accepted': 0, 'transcripts_with_accepted': 0},
                'run_ids_seen': [], 'generated_at_utc': 'fixture', 'files_read': 1, 'records_read': 0}))
            p = run('bash', a / 'scripts/deploy_predictions.sh', '--production-data', live,
                    '--data-revision', revision, '--dry-run', ok=False)
            assert p.returncode and 'stale production index' in p.stderr, p.stderr
        finally:
            os.environ['PATH'] = old_path
        run_dir = D.new_run(a, 'unique-new-run', 'astra', 'fable', 'gpt-6-astra')
        manifest = json.loads((run_dir / 'experiment.json').read_text())
        assert manifest['input_data_commit'] == git(da, 'rev-parse', 'HEAD')
        assert manifest['code_commit'] == git(a, 'rev-parse', 'HEAD')
        assert manifest['requested_models']['astra_model'] == 'gpt-6-astra'
        assert manifest['policy_release']['contracts']['extract'] == manifest['extraction_contract']['contract_id']
        assert len(manifest['verification_contract']['spec_sha256']) == 64
        try:
            D.new_run(a, 'unique-new-run', 'astra', 'fable', 'gpt-6-astra')
        except FileExistsError:
            pass
        else:
            raise AssertionError('duplicate experiment name was reused')
        assert (live / '.git/index').read_bytes() == live_index
    print('PASS: independent data clone workflow')
    return 0


if __name__ == '__main__':
    sys.exit(main())
