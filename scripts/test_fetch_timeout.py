#!/usr/bin/env python3
"""Guards on the fetcher's HTTP timeout.

WHY THIS EXISTS. youtube_transcript_api constructs a plain requests.Session and
sets no timeout anywhere in its own source, so a server that accepts a
connection and then never answers blocks the calling thread until the kernel
gives up. On 2026-09-08 one fetch worker sat ESTABLISHED at 0.0% CPU for
21h19m. Nothing detected it: the process was alive, so fetch_loop.sh reported
itself running and grade_loop.sh printed "fetch loop is still running. waiting."
every six minutes for the whole stall.

What is asserted here:

  STALL     a request through TimeoutSession to a server that accepts and never
            replies raises inside the budget, rather than blocking. The control
            arm is a plain requests.Session against the SAME server, which is
            shown still blocking after the budget has passed. Without the
            control the test would also pass against a server that simply
            closed the connection.
  LABEL     a timeout is classified as http_timeout, never as "other". The
            stall was invisible partly because nothing in the taxonomy named
            it.
  BACKOFF   a timeout feeds the circuit breaker like a throttle does, so a
            silently stalling endpoint is backed off instead of hammered at
            full pace. It keeps its own label while doing so.
  DEFAULT   the timeout is on by DEFAULT. A stall is exactly the situation in
            which nobody remembers to pass the flag.
  WIRED     fetch_one hands its timeout to the API client, so the setting
            reaches the calls that actually stalled.

Run: .venv/bin/python scripts/test_fetch_timeout.py
"""

from __future__ import annotations

import inspect
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests  # noqa: E402

import fetch_transcripts as ft  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   [{detail}]"))


class BlackHole:
    """A server that completes the TCP handshake and then says nothing.

    This is the shape of the real stall. A server that refuses or resets would
    raise on its own and would not exercise the timeout at all.
    """

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.held: list[socket.socket] = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        self.sock.settimeout(0.2)
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except (socket.timeout, OSError):
                continue
            self.held.append(conn)  # keep it open, never write

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def close(self) -> None:
        self.stop.set()
        for c in self.held:
            try:
                c.close()
            except OSError:
                pass
        try:
            self.sock.close()
        except OSError:
            pass


def blocks_for(fn, budget: float) -> bool:
    """True if fn is STILL running after `budget` seconds."""
    done = threading.Event()

    def run() -> None:
        try:
            fn()
        except Exception:
            pass
        finally:
            done.set()

    threading.Thread(target=run, daemon=True).start()
    return not done.wait(budget)


def test_stall() -> None:
    print("\n[1] a server that never answers must not hold a worker for ever")
    server = BlackHole()
    budget = 2.0
    try:
        # Control arm: the library's own default. If this does NOT block, the
        # fixture is not reproducing a stall and every result below is void.
        check("a plain Session is still blocked after the budget",
              blocks_for(lambda: requests.Session().get(server.url), budget + 1.0),
              "the black-hole server is not stalling; the rest of this file proves nothing")

        # Built OUTSIDE the try. A missing class must fail here as a missing
        # class, not be swallowed by the except below and reported as "it
        # raised", which is technically true and completely misleading.
        session = ft.TimeoutSession(timeout=budget)
        started = time.monotonic()
        try:
            session.get(server.url)
            raised: Exception | None = None
        except Exception as exc:  # noqa: BLE001 - the type is the assertion
            raised = exc
        elapsed = time.monotonic() - started

        check("TimeoutSession raises instead of blocking", raised is not None,
              "the request returned normally from a server that sent nothing")
        check("it raises a requests Timeout",
              isinstance(raised, requests.exceptions.Timeout), type(raised).__name__)
        check("it gives up close to the budget, not minutes later",
              elapsed < budget + 2.0, f"{elapsed:.1f}s against a {budget}s budget")

        check("an explicit per-call timeout still wins over the default",
              blocks_for(lambda: ft.TimeoutSession(timeout=30.0).get(server.url, timeout=0.5),
                         2.0) is False,
              "setdefault must not overwrite a caller's own timeout")
    finally:
        server.close()


def test_label_and_backoff() -> None:
    print("\n[2] a stall is labelled and backed off, not filed as 'other'")
    check("a Timeout classifies as http_timeout",
          ft.classify(requests.exceptions.ReadTimeout("stalled")) == ft.E_TIMEOUT,
          ft.classify(requests.exceptions.ReadTimeout("stalled")))
    check("a ConnectTimeout classifies the same way",
          ft.classify(requests.exceptions.ConnectTimeout("stalled")) == ft.E_TIMEOUT,
          ft.classify(requests.exceptions.ConnectTimeout("stalled")))
    check("http_timeout is its own label, not a rename of the block label",
          ft.E_TIMEOUT != ft.E_BLOCKED, f"{ft.E_TIMEOUT} == {ft.E_BLOCKED}")

    # The retry wrapper resets the breaker on any failure it does not consider a
    # throttle. If a stall reset it, a stalling endpoint would never trip the
    # circuit and would be retried at full pace for ever.
    src = inspect.getsource(ft.fetch_with_retry)
    check("a stall feeds the circuit breaker like a throttle does",
          "E_TIMEOUT" in src and "record_ok" in src,
          "fetch_with_retry treats a timeout as an ordinary failure")


def test_default_and_wiring() -> None:
    print("\n[3] the timeout is on by default and reaches the stalling calls")
    for fn in (ft.fetch_one, ft.fetch_with_retry, ft.fetch_leader):
        d = inspect.signature(fn).parameters["timeout"].default
        check(f"{fn.__name__} defaults its timeout to a real number",
              isinstance(d, (int, float)) and d > 0, repr(d))
    check("the default is finite and not absurdly long",
          0 < ft.HTTP_TIMEOUT_DEFAULT <= 300, str(ft.HTTP_TIMEOUT_DEFAULT))

    src = inspect.getsource(ft.fetch_one)
    check("fetch_one builds the API client with the timeout session",
          "YouTubeTranscriptApi(http_client=TimeoutSession(timeout))" in src,
          "the client is constructed without an http_client, so no timeout applies")


def main() -> int:
    print("fetcher HTTP-timeout guards")
    test_stall()
    test_label_and_backoff()
    test_default_and_wiring()
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
