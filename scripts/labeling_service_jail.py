"""The sandbox-exec rules that keep a jailed judge away from the transcript labeling service (VI-59).

The service, from the public transcript-labeling repository, runs on this Mac as
the launchd agent `local.transcript-labeling.server`. It listens on 127.0.0.1,
port 8790 unless its config.json names another, and keeps its config, bearer
token, local-only datasets and state under its home folder. A judge that reached
either could read human labels, so every judge profile appends rules() after its
own: grade.sandbox_profile, date_recordings.sandbox_profile, and through
grade.sandbox_profile the pundits harness and the probes.

Every home found is denied, because a home missed is a hole nobody sees:
  - the default, ~/.local/share/transcript-labeling under the operator's home
    directory, read from the password database, because a judge call may run
    with HOME pointed at a profile folder;
  - this process's TL_HOME when it is not empty (the service treats an empty one
    as unset);
  - TL_HOME in the service's launchd plist, when the plist exists, because that
    is where a non-default home is set for the running service.

A plist or config.json that exists but cannot be read raises instead of
returning a quieter profile. The rules are read when a profile is built, so a
service whose port changes later is covered from the next build.

Standard library only, so date_recordings can import it without importing grade.
"""
from __future__ import annotations

import json
import os
import plistlib
import pwd
from pathlib import Path

DEFAULT_PORT = 8790
LABEL = "local.transcript-labeling.server"


def _user_home() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def _expand(value: str) -> Path:
    """`~` and `~/...` against the operator's home directory, never $HOME."""
    if value == "~" or value.startswith("~/"):
        return _user_home() / value[2:]
    return Path(value).expanduser()


def default_plist() -> Path:
    return _user_home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def homes(env=None, plist: Path | None = None) -> list[Path]:
    """Every home folder the service may use, resolved, without duplicates."""
    env = os.environ if env is None else env
    plist = default_plist() if plist is None else plist
    found = [_user_home() / ".local" / "share" / "transcript-labeling"]
    if env.get("TL_HOME"):
        found.append(_expand(env["TL_HOME"]))
    if plist.exists():
        try:
            data = plistlib.loads(plist.read_bytes())
        except Exception as exc:  # noqa: BLE001 -- re-raised below with the file named
            raise RuntimeError(f"REFUSING: cannot read the labeling service's plist {plist}: {exc}") from exc
        value = (data.get("EnvironmentVariables") or {}).get("TL_HOME") if isinstance(data, dict) else None
        if value:
            found.append(_expand(str(value)))
    out: list[Path] = []
    for h in found:
        r = h.resolve()
        if r not in out:
            out.append(r)
    return out


def ports(found: list[Path]) -> list[int]:
    """Port 8790 and every port a found home's config.json names, sorted."""
    out = {DEFAULT_PORT}
    for h in found:
        cfg = h / "config.json"
        if not cfg.exists():
            continue
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"REFUSING: cannot read the labeling service's config {cfg}: {exc}") from exc
        port = data.get("port") if isinstance(data, dict) else None
        if type(port) is not int or not 0 < port < 65536:
            raise RuntimeError(f"REFUSING: {cfg} names no usable port ({port!r})")
        out.add(port)
    return sorted(out)


def rules(env=None, plist: Path | None = None) -> str:
    """The sandbox-exec rules that deny the service's ports and homes, to append to a profile."""
    found = homes(env, plist)
    parts = []
    for port in ports(found):
        parts.append(f'(deny network-outbound (remote ip "localhost:{port}"))')
        parts.append(f'(deny network-bind (local ip "localhost:{port}"))')
    for h in found:
        if '"' in str(h) or "\\" in str(h):
            raise RuntimeError(f"REFUSING: the labeling service home {h} cannot be written into a sandbox profile")
        parts.append(f'(deny file-read* (subpath "{h}"))(deny file-write* (subpath "{h}"))')
    return "".join(parts)
