#!/usr/bin/env python3
"""Every judge profile denies the transcript labeling service's port and home (VI-59). No quota.

The service keeps human labels, its bearer token and its local-only datasets under
its home folder and serves them on 127.0.0.1. These tests pin the rules that
labeling_service_jail.rules() adds to every sandbox-exec profile, and that all
three profile builders carry them. test_judge_jail.py runs the rules live.

  HOMES     the default home under the operator's home directory, this process's
            non-empty TL_HOME, and TL_HOME in the service's launchd plist are all
            denied for read and write, as resolved real paths; `~` expands to the
            operator's home directory from the password database, never $HOME
  PORTS     port 8790 and any port a found home's config.json names are denied for
            outbound connections and for binding, on localhost
  REFUSALS  a plist or config.json that exists but cannot be read, a port that is
            not an integer, and a path that would break the profile's quoting
            raise instead of returning a quieter profile
  BUILDERS  grade, date_recordings and p3_judge_probe each append the rules
  CONTRACT  the pundits contract ID does not depend on the profile text

  .venv/bin/python scripts/test_labeling_service_jail.py
"""
from __future__ import annotations

import json
import os
import plistlib
import pwd
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import labeling_service_jail as LSJ  # noqa: E402

USER_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
DEFAULT_HOME = (USER_HOME / ".local/share/transcript-labeling").resolve()


def denies_path(rules: str, path: Path) -> bool:
    return (f'(deny file-read* (subpath "{path}"))' in rules
            and f'(deny file-write* (subpath "{path}"))' in rules)


def denies_port(rules: str, port: int) -> bool:
    return (f'(deny network-outbound (remote ip "localhost:{port}"))' in rules
            and f'(deny network-bind (local ip "localhost:{port}"))' in rules)


class Homes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name).resolve()
        self.no_plist = self.dir / "absent.plist"

    def tearDown(self):
        self.tmp.cleanup()

    def plist(self, env: dict | None) -> Path:
        p = self.dir / "service.plist"
        body = {"Label": "local.transcript-labeling.server", "ProgramArguments": ["/x/tl", "serve"]}
        if env is not None:
            body["EnvironmentVariables"] = env
        p.write_bytes(plistlib.dumps(body))
        return p

    def test_the_default_home_and_port_are_denied_with_nothing_else_set(self):
        rules = LSJ.rules(env={}, plist=self.no_plist)
        self.assertTrue(denies_path(rules, DEFAULT_HOME), rules)
        self.assertTrue(denies_port(rules, 8790), rules)
        self.assertEqual(LSJ.homes(env={}, plist=self.no_plist), [DEFAULT_HOME])

    def test_an_empty_tl_home_counts_as_unset_as_the_service_reads_it(self):
        self.assertEqual(LSJ.homes(env={"TL_HOME": ""}, plist=self.no_plist), [DEFAULT_HOME])

    def test_this_process_tl_home_is_denied_too(self):
        home = self.dir / "svc-home"
        rules = LSJ.rules(env={"TL_HOME": str(home)}, plist=self.no_plist)
        self.assertTrue(denies_path(rules, DEFAULT_HOME))
        self.assertTrue(denies_path(rules, home), rules)

    def test_a_tilde_expands_to_the_operators_home_not_to_HOME(self):
        homes = LSJ.homes(env={"TL_HOME": "~/tl-elsewhere", "HOME": "/nonexistent-profile"}, plist=self.no_plist)
        self.assertIn((USER_HOME / "tl-elsewhere").resolve(), homes)

    def test_the_plists_tl_home_is_denied(self):
        home = self.dir / "plist-home"
        rules = LSJ.rules(env={}, plist=self.plist({"TL_HOME": str(home), "PATH": "/usr/bin"}))
        self.assertTrue(denies_path(rules, home), rules)
        self.assertTrue(denies_path(rules, DEFAULT_HOME))

    def test_a_plist_without_tl_home_adds_nothing(self):
        self.assertEqual(LSJ.homes(env={}, plist=self.plist({"PATH": "/usr/bin"})), [DEFAULT_HOME])
        self.assertEqual(LSJ.homes(env={}, plist=self.plist(None)), [DEFAULT_HOME])

    def test_a_home_under_tmp_is_written_as_its_real_path(self):
        rules = LSJ.rules(env={"TL_HOME": "/tmp/tl-jail-test-home"}, plist=self.no_plist)
        self.assertTrue(denies_path(rules, Path("/private/tmp/tl-jail-test-home")), rules)
        self.assertNotIn('(subpath "/tmp/', rules)

    def test_one_home_named_twice_is_denied_once(self):
        rules = LSJ.rules(env={"TL_HOME": str(DEFAULT_HOME)}, plist=self.no_plist)
        self.assertEqual(rules.count(f'(deny file-read* (subpath "{DEFAULT_HOME}"))'), 1)


class Ports(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve() / "home"
        self.home.mkdir()
        self.no_plist = Path(self.tmp.name) / "absent.plist"

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, body) -> None:
        (self.home / "config.json").write_text(body if isinstance(body, str) else json.dumps(body))

    def test_a_port_from_a_found_homes_config_is_denied_with_the_default(self):
        self.config({"port": 9123, "operator_id": "operator", "allowed_hosts": [], "access": {}})
        rules = LSJ.rules(env={"TL_HOME": str(self.home)}, plist=self.no_plist)
        self.assertTrue(denies_port(rules, 9123), rules)
        self.assertTrue(denies_port(rules, 8790), rules)

    def test_a_home_with_no_config_yet_leaves_the_default_port(self):
        self.assertEqual(LSJ.ports([self.home]), [8790])


class Refusals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_an_unreadable_plist_raises(self):
        p = self.dir / "bad.plist"
        p.write_text("not a plist")
        with self.assertRaisesRegex(RuntimeError, "REFUSING"):
            LSJ.homes(env={}, plist=p)

    def test_a_config_that_is_not_json_raises(self):
        (self.dir / "config.json").write_text("{port: 8790")
        with self.assertRaisesRegex(RuntimeError, "REFUSING"):
            LSJ.ports([self.dir])

    def test_a_config_without_an_integer_port_raises(self):
        for body in ({}, {"port": "8790"}, {"port": True}, {"port": 0}, {"port": 70000}, []):
            (self.dir / "config.json").write_text(json.dumps(body))
            with self.subTest(body=body), self.assertRaisesRegex(RuntimeError, "REFUSING"):
                LSJ.ports([self.dir])

    def test_a_home_whose_path_would_break_the_profiles_quoting_raises(self):
        for bad in ('/tmp/a"b', "/tmp/a\\b"):
            with self.subTest(path=bad), self.assertRaisesRegex(RuntimeError, "REFUSING"):
                LSJ.rules(env={"TL_HOME": bad}, plist=self.dir / "absent.plist")


class Builders(unittest.TestCase):
    MARK = '(deny network-outbound (remote ip "localhost:8790"))'

    def test_every_profile_builder_appends_the_rules(self):
        import date_recordings as DR  # noqa: PLC0415
        import grade as G  # noqa: PLC0415
        import p3_judge_probe as P3  # noqa: PLC0415
        root = Path("/x/verbatim-index")
        with mock.patch.object(LSJ, "rules", return_value=self.MARK):
            for name, prof in (("grade", G.sandbox_profile(root)),
                               ("date_recordings", DR.sandbox_profile([root])),
                               ("p3_judge_probe", P3.sandbox_profile(root))):
                with self.subTest(builder=name):
                    self.assertTrue(prof.startswith("(version 1)(allow default)"), prof)
                    self.assertIn(f'(deny file-read* (subpath "{root}"))', prof)
                    self.assertTrue(prof.endswith(self.MARK), prof)

    def test_the_real_profiles_carry_the_real_rules(self):
        import grade as G  # noqa: PLC0415
        self.assertIn(LSJ.rules(), G.sandbox_profile(Path("/x/verbatim-index")))


class Contract(unittest.TestCase):
    def test_the_pundits_contract_id_does_not_depend_on_the_profile_text(self):
        import grading_contract as GC  # noqa: PLC0415
        import study_profile as SP  # noqa: PLC0415
        ids = set()
        for text in ("", '(deny network-outbound (remote ip "localhost:1"))'):
            with mock.patch.object(LSJ, "rules", return_value=text):
                ids.add(GC.contract_v2(SP.load("pundits"))["contract_id"])
        self.assertEqual(len(ids), 1, ids)


if __name__ == "__main__":
    unittest.main()
