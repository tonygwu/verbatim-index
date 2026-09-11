#!/bin/sh
# Run the Antigravity judge as another macOS user, inside THAT user's GUI
# session, so it can reach that user's login Keychain.
#
# WHY THIS EXISTS. `agy` keeps its credential in one Keychain item per macOS
# user: service "gemini", account "antigravity". Two HOME directories under one
# user therefore share one account, which is how all 567 Gemini grades in the
# corpus came from gptwufamily@gmail.com while two profiles alternated. A
# second macOS user has its own login Keychain and is the only real second
# account on one machine.
#
# `sudo -u other` alone is NOT enough. MEASURED 2026-09-11: the sudoers rule was
# correct, the binary was readable, and the call still failed with
#   error getting token source: You are not logged into Antigravity.
#   consumerOAuth: starting OAuth flow
# because a process started from another user's terminal sits in the WRONG
# security session and cannot read the target user's Keychain. `launchctl
# asuser <uid>` puts it in that user's session, where the Keychain is unlocked
# for as long as that user stays logged in. With it the same call answered and
# its log recorded "ChainedAuth: authenticated via keyring".
#
# INSTALL, as root, so one sudoers rule covers it and no password is needed
# per call:
#
#   sudo install -o root -g wheel -m 755 scripts/agy_as_user.sh \
#        /usr/local/libexec/agy-as-user
#   sudo visudo -f /etc/sudoers.d/agy-as-user     # containing, on one line:
#     <you> ALL=(root) NOPASSWD: /usr/local/libexec/agy-as-user
#
# The binary path is checked against ALLOWED_BINARY rather than trusted, so the
# rule cannot be turned into "run anything as that user". The target user may
# not be root.
#
# Usage:  agy-as-user <macos-user> <agy-binary> [agy args...]

set -eu

ALLOWED_BINARY=/usr/local/bin/agy

if [ "$#" -lt 2 ]; then
    echo "usage: $0 <macos-user> <agy-binary> [args...]" >&2
    exit 64
fi

user=$1
binary=$2
shift 2

if [ "$binary" != "$ALLOWED_BINARY" ]; then
    echo "$0: refusing to run '$binary'; this wrapper only runs $ALLOWED_BINARY." >&2
    echo "  Install the judge binary there, or edit ALLOWED_BINARY in this script." >&2
    exit 77
fi

if [ ! -x "$ALLOWED_BINARY" ]; then
    echo "$0: $ALLOWED_BINARY is missing or not executable." >&2
    exit 77
fi

uid=$(id -u "$user" 2>/dev/null) || {
    echo "$0: no such user '$user'." >&2
    exit 67
}

if [ "$uid" -eq 0 ]; then
    echo "$0: refusing to run the judge as root." >&2
    exit 77
fi

# A user with no GUI session has a locked login Keychain, and the judge would
# fall through to an interactive sign-in that never completes. Say so here
# rather than letting every call time out.
if ! /bin/launchctl print "user/$uid" >/dev/null 2>&1; then
    echo "$0: user '$user' (uid $uid) has no active login session, so its" >&2
    echo "  Keychain is locked. Log that user in, for example with Fast User" >&2
    echo "  Switching, and leave the session open." >&2
    exit 75
fi

exec /bin/launchctl asuser "$uid" /usr/bin/sudo -u "$user" -H "$ALLOWED_BINARY" "$@"
